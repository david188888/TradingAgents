"""A saved Insight pipeline with one research review/response and bounded repair."""

import contextlib
import re

from pydantic import ValidationError

from tradingagents.agents.schemas._insight import (
    EvidenceCard,
    InsightBatch,
    InsightCatalog,
    InsightReport,
    NumericReference,
    ResponseProposal,
    ReviewProposal,
    SavedResponse,
    SavedReview,
    SavedSynthesis,
    SynthesisProposal,
)
from tradingagents.agents.schemas._verification_plan import canonical_sha256
from tradingagents.execution.insight_model import InsightUnavailable
from tradingagents.research.insight_report import parse_insight_report, validate_saved_synthesis
from tradingagents.research.insights import compile_insights
from tradingagents.research.numeric_catalog import render_numeric_anchor
from tradingagents.runtime.catalyst_checkpoint import CatalystCheckpointConflict


def catalog_prompt(catalog, query='', *, compact=False):
    """All facts remain visible; quote bounded original passages without full payload duplication."""
    from tradingagents.research.evidence_packets import retrieve_evidence
    sources = [s.model_dump(mode='json') for s in catalog.sources]
    context = {'sources': sources, 'facts': [{'evidence_ids': e.source_ids} for e in catalog.evidence]}
    passages = retrieve_evidence(context, query or ' '.join(e.text for e in catalog.evidence))
    metadata = [{**{k: value[k] for k in ('evidence_id', 'source_name', 'source_kind', 'published_at',
        'usable_as_of', 'public_url', 'limitations')}, 'locator': (value.get('content') or {}).get('locator_label')}
        for value in sources]
    evidence = [e.model_dump(mode='json') for e in catalog.evidence]
    if compact:
        aliases = {s.evidence_id: f'S{i}' for i, s in enumerate(catalog.sources, 1)}
        for fact in evidence:
            fact.pop('fact_id')  # Host identity is not a model-written research field.
            fact['source_ids'] = [aliases[s] for s in fact['source_ids']]
        for source in (*metadata, *passages):
            source['evidence_id'] = aliases[source['evidence_id']]
    return {'evidence': evidence, 'sources': metadata,
        'source_passages': passages, 'passage_scope': 'Selected exact excerpts; full saved sources remain available in the report.',
        'numbers': [{'ref': n.ref, 'description': render_numeric_anchor(n.anchor.model_dump(mode='json')),
                    'limitations': n.anchor.limitations} for n in catalog.numbers]}


def merge_catalogs(catalogs):
    sources, facts, numbers = {}, {}, {}
    snapshots = {c.snapshot_id for c in catalogs.values()}
    if len(snapshots) != 1:
        raise ValueError('insight_catalog_snapshots_mismatch')
    for catalog in catalogs.values():
        sources.update((s.evidence_id, s) for s in catalog.sources)
        facts.update((e.fact_id, e) for e in catalog.evidence)
        numbers.update((n.anchor.anchor_id, n.anchor) for n in catalog.numbers)
    return InsightCatalog(snapshot_id=next(iter(snapshots)), sources=tuple(sources[s] for s in sorted(sources)),
        evidence=tuple(facts[f].model_copy(update={'ref': f'E{i}'}) for i, f in enumerate(sorted(facts), 1)),
        numbers=tuple(NumericReference(ref=f'N{i}', anchor=numbers[n]) for i, n in enumerate(sorted(numbers), 1)))


def run_insight_research(*, run_id, ticker, analysis_date, catalogs, caller, journal,
                         ensure_active, on_stage=lambda stage, status: None, source_gaps=(), supplement=None, focus_question=None, company_basics=None, foundation_catalog=None):
    identity = {'run_id': run_id, 'ticker': ticker, 'date': analysis_date.isoformat(),
                'catalogs': {r: c.model_dump(mode='json') for r, c in catalogs.items()}, 'gaps': list(source_gaps), 'focus_question': focus_question,
                'company_basics': company_basics.model_dump(mode='json') if company_basics else None,
                'foundation': foundation_catalog.model_dump(mode='json') if foundation_catalog else None}
    digest = canonical_sha256(identity)
    prior = journal.state.get('insight.input_digest')
    if prior is not None and prior != digest:
        raise CatalystCheckpointConflict('insight input changed')
    if prior is None:
        journal.put('insight.input_digest', digest)
        journal.put('insight.catalogs', identity['catalogs'])
    if journal.state.get('insight.report') is not None:
        return parse_insight_report(journal.state['insight.report'])
    ensure_active()
    compact = journal.state['identity'].get('insight_context_policy') == 'compact-saved-evidence-v1'
    gaps, stages, insights = list(source_gaps), {}, []
    catalog_history = {canonical_sha256(c.model_dump(mode='json')): c for c in catalogs.values()}
    if foundation_catalog is not None:
        catalog_history[canonical_sha256(foundation_catalog.model_dump(mode='json'))] = foundation_catalog
    superseded_ids = []
    journal.put('insight.catalog_history', {key: c.model_dump(mode='json') for key, c in catalog_history.items()})

    def ask(stage, context, phase='main'):
        ensure_active()
        on_stage(stage, 'running')
        try:
            raw = caller(stage, context, phase=phase)
            if (phase == 'main' or phase.startswith('supplement_')) and stage in catalogs and isinstance(raw, dict):
                questions = raw.get('search_requests', [])
                if isinstance(questions, list):
                    valid = tuple(dict.fromkeys(q.strip() for q in questions if isinstance(q, str) and 0 < len(q.strip()) <= 400))
                    journal.put('insight.search_requests.' + stage + ('' if phase == 'main' else '.' + phase), list(valid))
                    if len(valid) != len({q.strip() for q in questions if isinstance(q, str)}):
                        gaps.append('search_request_invalid')
                else:
                    gaps.append('search_request_invalid')
            return raw
        except InsightUnavailable as exc:
            if journal.failed:
                raise
            journal.put(f'insight.failure.{stage}.{phase}', str(exc))
            return None

    def finish(stage, status):
        stages[stage] = status
        journal.put('insight.stages', dict(stages))
        on_stage(stage, status)

    for role, catalog in catalogs.items():
        key = 'insight.batch.' + role
        if key in journal.state:
            batch = InsightBatch.model_validate(journal.state[key])
        elif not catalog.evidence:
            batch = InsightBatch()
            journal.put(key, batch.model_dump(mode='json'))
        else:
            context = {**catalog_prompt(catalog, compact=compact), 'search_requests_allowed': supplement is not None}
            if key + '.main' in journal.state:
                main = InsightBatch.model_validate(journal.state[key + '.main'])
            else:
                raw = ask(role, context)
                try:
                    main = compile_insights(raw, catalog=catalog, role=role)
                except ValueError:
                    main = InsightBatch()
                journal.put(key + '.main', main.model_dump(mode='json'))
            failed = sorted([i.index for i in main.items if i.status != 'accepted'] + [r.index for r in main.rejected])
            batch = main
            # Unknown dispatches must not become fresh attempts under a repair label.
            unknown = journal.state.get(f'insight.failure.{role}.main') == 'response_unknown'
            if not unknown and (failed or not main.items):
                raw = ask(role, {**context, 'repair_indices': failed,
                    'issues': [{'index': i.index, 'issues': i.issues} for i in main.items if i.status != 'accepted']
                        + [r.model_dump(mode='json') for r in main.rejected]}, 'repair')
                try:
                    repaired = compile_insights(raw, catalog=catalog, role=role, indices=failed or None)
                    replacements = {i.index: i for i in repaired.items}
                    old = {i.index: i for i in main.items}
                    old.update(replacements)
                    errors = {r.index: r for r in main.rejected if r.index not in replacements}
                    errors.update((r.index, r) for r in repaired.rejected)
                    batch = InsightBatch(items=tuple(old[i] for i in sorted(old)), rejected=tuple(errors[i] for i in sorted(errors)))
                except ValueError:
                    pass  # Preserve the compiled main candidate, including valid siblings.
            journal.put(key, batch.model_dump(mode='json'))
        insights.extend(batch.items)
        finish(role, 'skipped' if not catalog.evidence else 'completed' if any(i.status == 'accepted' for i in batch.items) else 'failed')
        if not batch.items or batch.rejected or any(i.status != 'accepted' for i in batch.items):
            gaps.append(role + '_partial')

    requests = {role: tuple(journal.state.get('insight.search_requests.' + role, ())) for role in catalogs}
    pending = list(dict.fromkeys((role, question) for role, questions in requests.items() for question in questions))
    seen_questions = set(pending)
    if pending and supplement is None:
        gaps.append('search_unavailable')
    for round_id in range(1, 4) if supplement is not None else ():
        if not pending:
            break
        selected, pending = pending[:3], pending[3:]
        scoped = {role: tuple(question for owner, question in selected if owner == role) for role in catalogs}
        scoped = {role: values for role, values in scoped.items() if values}
        ensure_active()
        result = supplement(scoped, round_id)
        gaps.extend(result['gaps'])
        if not result['affected_roles']:
            gaps.append('search_no_qualified_delta')
            break
        catalogs = result['catalogs']
        catalog_history.update((canonical_sha256(c.model_dump(mode='json')), c) for c in catalogs.values())
        journal.put('insight.catalog_history', {key: c.model_dump(mode='json') for key, c in catalog_history.items()})
        for role in result['affected_roles']:
            previous = [i for i in insights if i.role == role and i.status != 'excluded']
            superseded_ids.extend(i.insight_id for i in previous)
            insights = [i.model_copy(update={'status': 'excluded'}) if i in previous else i for i in insights]
            key = f'insight.batch.{role}.supplement_{round_id}'
            if key in journal.state:
                batch = InsightBatch.model_validate(journal.state[key])
            else:
                context = {**catalog_prompt(catalogs[role], compact=compact), 'search_requests_allowed': round_id < 3,
                    'previous_findings': [i.rendered.model_dump() for i in previous],
                    'instruction': '资料已更新。重新核查本专项观点；旧观点不会自动用于综合。'}
                raw = ask(role, context, f'supplement_{round_id}')
                try:
                    batch = compile_insights(raw, catalog=catalogs[role], role=role, revision=round_id + 1)
                except ValueError:
                    batch = InsightBatch()
                journal.put(key, batch.model_dump(mode='json'))
            for question in journal.state.get(f'insight.search_requests.{role}.supplement_{round_id}', ()):
                if (role, question) not in seen_questions:
                    seen_questions.add((role, question))
                    pending.append((role, question))
                    requests[role] = (*requests.get(role, ()), question)
            insights.extend(batch.items)
            finish(role, 'completed' if any(i.status == 'accepted' for i in batch.items) else 'failed')
            if not batch.items or batch.rejected or any(i.status != 'accepted' for i in batch.items):
                gaps.append(role + '_supplement_unresolved')
    if pending:
        gaps.append('search_requests_remaining')

    merged = merge_catalogs(catalogs)
    journal.put('insight.review_catalog', merged.model_dump(mode='json'))
    catalog_history[canonical_sha256(merged.model_dump(mode='json'))] = merged
    journal.put('insight.catalog_history', {key: c.model_dump(mode='json') for key, c in catalog_history.items()})
    targets = {f'I{i}': item for i, item in enumerate((s for s in insights if s.status == 'accepted'), 1)}
    def project_targets(values):
        evidence_aliases = {e.fact_id: e.ref for e in merged.evidence}
        result = []
        for ref, item in values.items():
            origin = catalog_history[item.catalog_id]
            aliases = {e.ref: evidence_aliases[e.fact_id] for e in origin.evidence}
            texts = {key: re.sub(r'\[(E[0-9]+)\]', lambda match, aliases=aliases: '[' + aliases[match[1]] + ']', text)
                     for key, text in item.rendered.model_dump().items()}
            result.append({'ref': ref, 'insight_id': item.insight_id, **texts,
                'evidence_refs': [e.ref for e in merged.evidence if e.fact_id in item.fact_ids]})
        return result

    review_context = {**catalog_prompt(merged, compact=compact), 'insights': project_targets(targets)}

    def note(text, refs, *, claim='研究审阅'):
        compiled = compile_insights({'insights': [{'claim': claim, 'evidence_refs': list(refs),
            'reasoning': text, 'limitations': '研究意见，不能视为事实证明。'}]}, catalog=merged, role='review').items[0]
        if set(compiled.issues) - {'evidence_missing'}:
            raise ValueError(next(issue for issue in compiled.issues if issue != 'evidence_missing'))
        return compiled

    reviews = []
    if 'insight.reviews' in journal.state:
        reviews = [SavedReview.model_validate(v) for v in journal.state['insight.reviews']]
    else:
        raw = ask('challenge', review_context) if targets else None
        candidates = raw.get('reviews', []) if isinstance(raw, dict) else []
        accepted, duplicates = {}, set()
        for value in candidates if isinstance(candidates, list) else []:
            try:
                review = ReviewProposal.model_validate(value)
                if review.target not in targets or not review.reasoning.strip() or (review.concern is not None and not review.concern.strip()):
                    continue
                checked = note(review.reasoning, review.evidence_refs, claim=review.concern or '未发现有效反证')
                if review.target in accepted:
                    duplicates.add(review.target)
                accepted[review.target] = SavedReview(target_id=targets[review.target].insight_id,
                    status='challenged' if review.concern else 'no_counterevidence',
                    concern=checked.rendered.claim if review.concern else None, reasoning=checked.rendered.reasoning,
                    source_ids=checked.source_ids, note=checked)
            except (ValueError, ValidationError):
                continue
        reviews = [accepted[key] if key in accepted and key not in duplicates else SavedReview(target_id=value.insight_id,
            status='unreviewed' if raw is not None else 'failed') for key, value in targets.items()]
        journal.put('insight.reviews', [r.model_dump(mode='json') for r in reviews])
    if any(r.status in {'unreviewed', 'failed'} for r in reviews):
        gaps.append('unreviewed_insights')
    finish('challenge', 'completed' if reviews and all(r.status not in {'unreviewed', 'failed'} for r in reviews) else 'failed' if targets else 'skipped')

    responses = []
    for role in catalogs:
        assigned = {key: item for key, item in targets.items() if item.role == role and any(
            r.target_id == item.insight_id and r.status == 'challenged' for r in reviews)}
        stage = 'response_' + role
        if not assigned:
            finish(stage, 'skipped')
            continue
        key = 'insight.responses.' + role
        if key in journal.state:
            saved = journal.state[key]
            role_responses = [SavedResponse.model_validate(v) for v in saved['responses']]
            replacement_items = InsightBatch.model_validate(saved['replacement_items']).items
        else:
            raw = ask(stage, {**review_context, 'assigned': list(assigned), 'reviews': [r.model_dump(mode='json') for r in reviews]})
            candidates = raw.get('responses', []) if isinstance(raw, dict) else []
            role_responses, replacement_items, diagnostics = [], [], []
            used = set()
            reply_targets = [v.get('target') for v in candidates if isinstance(v, dict) and isinstance(v.get('target'), str)] if isinstance(candidates, list) else []
            duplicates = {target for target in reply_targets if reply_targets.count(target) > 1}
            for index, value in enumerate(candidates if isinstance(candidates, list) else []):
                try:
                    reply = ResponseProposal.model_validate(value)
                    if reply.target not in assigned or reply.target in used or reply.target in duplicates:
                        diagnostics.append({'index': index, 'target': reply.target if reply.target in assigned else None,
                            'code': 'duplicate_target' if reply.target in duplicates or reply.target in used else 'target_not_assigned'})
                        continue
                    current = assigned[reply.target]
                    checked = note(reply.reasoning, reply.evidence_refs)
                    replacement = None
                    if reply.action == 'revise':
                        if reply.replacement is None:
                            diagnostics.append({'index': index, 'target': reply.target, 'code': 'replacement_missing'})
                            continue
                        replacement = compile_insights({'insights': [reply.replacement.model_dump(mode='json')]},
                            catalog=merged, role=role, revision=current.revision + 1, indices=[current.index]).items[0]
                        if replacement.status != 'accepted':
                            diagnostics.extend({'index': index, 'target': reply.target, 'code': issue} for issue in replacement.issues)
                            continue
                    elif reply.replacement is not None:
                        diagnostics.append({'index': index, 'target': reply.target, 'code': 'replacement_unexpected'})
                        continue
                    role_responses.append(SavedResponse(target_id=current.insight_id, action=reply.action,
                        reasoning=checked.rendered.reasoning, source_ids=checked.source_ids, note=checked,
                        replacement_id=replacement.insight_id if replacement else None))
                    if replacement:
                        replacement_items.append(replacement)
                    used.add(reply.target)
                except (ValueError, ValidationError) as exc:
                    code = str(exc) if str(exc) in {'numeric_literal_unbound', 'numeric_scope', 'reference_unknown', 'source_unavailable'} else 'response_shape_invalid'
                    target = value.get('target') if isinstance(value, dict) else None
                    diagnostics.append({'index': index, 'target': target if isinstance(target, str) and target in assigned else None, 'code': code})
                    continue
            for target in assigned:
                if target not in used and not any(d['target'] == target for d in diagnostics):
                    diagnostics.append({'index': None, 'target': target, 'code': 'response_unavailable' if raw is None else 'target_missing'})
            journal.put('insight.diagnostics.' + stage, diagnostics)
            journal.put(key, {'responses': [r.model_dump(mode='json') for r in role_responses],
                'replacement_items': InsightBatch(items=tuple(replacement_items)).model_dump(mode='json')})
        responses.extend(role_responses)
        for reply in role_responses:
            if reply.action in {'withdraw', 'revise'}:
                insights = [i.model_copy(update={'status': 'excluded'}) if i.insight_id == reply.target_id else i for i in insights]
                alias = next(k for k, item in targets.items() if item.insight_id == reply.target_id)
                if reply.action == 'revise':
                    replacement = next(i for i in replacement_items if i.insight_id == reply.replacement_id)
                    targets[alias] = replacement
                    insights.append(replacement)
                else:
                    del targets[alias]
        missing = len(role_responses) < len(assigned) or any(r.action == 'uncertain' for r in role_responses)
        if missing:
            gaps.append(stage + '_unresolved')
        finish(stage, 'failed' if missing else 'completed')

    synthesis = None
    final_catalog = InsightCatalog(snapshot_id=merged.snapshot_id, sources=merged.sources,
        evidence=tuple(EvidenceCard(ref=key, fact_id=item.insight_id, text=item.rendered.claim,
            source_ids=item.source_ids) for key, item in targets.items()))
    if 'insight.synthesis' in journal.state:
        saved = journal.state['insight.synthesis']
        synthesis = validate_saved_synthesis(SavedSynthesis.model_validate(saved), insights, merged) if saved is not None else None
    elif targets:
        synthesis_catalog = merged
        if compact:
            # Synthesis may judge saved premises, but cannot introduce uncited raw facts.
            supporting = (*targets.values(), *(r.note for r in reviews if r.note), *(r.note for r in responses))
            facts = {f for item in supporting for f in item.fact_ids}
            sources = {s for item in supporting for s in item.source_ids}
            synthesis_catalog = merged.model_copy(update={
                'evidence': tuple(e for e in merged.evidence if e.fact_id in facts),
                'sources': tuple(s for s in merged.sources if s.evidence_id in sources), 'numbers': ()})
        context = {'insights': project_targets(targets),
            'reviews': [r.model_dump(mode='json') for r in reviews],
            'responses': [r.model_dump(mode='json') for r in responses],
            'reviewed_targets': [{'ref': i['ref'], 'insight_id': i['insight_id']} for i in review_context['insights']], 'gaps': gaps,
            'sources': catalog_prompt(synthesis_catalog, compact=compact)}
        for phase in ('main', 'repair'):
            raw = ask('synthesis', context, phase)
            try:
                value = SynthesisProposal.model_validate(raw)
                checked = compile_insights({'insights': [{'claim': value.judgement,
                    'evidence_refs': list(value.insight_refs), 'reasoning': value.reasoning,
                    'limitations': value.limitations + '\n' + value.next_check}]}, catalog=final_catalog, role='synthesis').items[0]
                if checked.status != 'accepted':
                    raise ValueError('synthesis_reference_invalid')
                synthesis = SavedSynthesis(judgement=value.judgement, stance=value.stance,
                    reasoning=value.reasoning, limitations=value.limitations, next_check=value.next_check,
                    insight_ids=checked.fact_ids, reference_ids={key: item.insight_id for key, item in targets.items()})
                break
            except (ValueError, ValidationError):
                if journal.state.get(f'insight.failure.synthesis.{phase}') == 'response_unknown':
                    break
        journal.put('insight.synthesis', synthesis.model_dump(mode='json') if synthesis else None)
    if synthesis is None:
        gaps.append('synthesis_unavailable')
    finish('synthesis', 'completed' if synthesis else 'failed')
    focus_batch = InsightBatch()
    if focus_question:
        if 'insight.focus' in journal.state:
            focus_batch = InsightBatch.model_validate(journal.state['insight.focus'])
        elif merged.evidence:
            raw = ask('focus_response', {**catalog_prompt(merged, query=focus_question, compact=compact),
                'question': focus_question, 'insights': project_targets(targets), 'search_requests_allowed': False,
                'synthesis': synthesis.model_dump(mode='json') if synthesis else None})
            with contextlib.suppress(ValueError):
                focus_batch = compile_insights(raw, catalog=merged, role='focus_response')
            journal.put('insight.focus', focus_batch.model_dump(mode='json'))
        ok = any(i.status == 'accepted' for i in focus_batch.items)
        finish('focus_response', 'completed' if ok else 'failed')
        if not ok:
            gaps.append('focus_unavailable')
    ensure_active()
    report = InsightReport(run_id=run_id, ticker=ticker, analysis_date=analysis_date,
        catalogs={**catalog_history, **catalogs, 'review': merged}, insights=tuple(insights), reviews=tuple(reviews),
        responses=tuple(responses), synthesis=synthesis, gaps=tuple(dict.fromkeys(gaps)), stages=stages, superseded_ids=tuple(superseded_ids), search_requests=requests, focus_question=focus_question, focus_insights=focus_batch.items, company_basics=company_basics)
    journal.put('insight.report', report.model_dump(mode='json'))
    return report
