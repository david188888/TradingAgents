"""A saved Insight pipeline with one research review/response and bounded repair."""

import contextlib

from pydantic import ValidationError

from tradingagents.agents.schemas._insight import (
    CapabilityRequest,
    EvidenceCard,
    InsightBatch,
    InsightCatalog,
    InsightRepairItem,
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
from tradingagents.execution.insight_model import DecisionVerificationFailed, InsightUnavailable
from tradingagents.llm_clients.decisions_client import TARGETED_REVIEW_POLICY
from tradingagents.research.evidence_retrieval import related_fact_refs, retrieve_evidence
from tradingagents.research.insight_report import parse_insight_report, validate_saved_synthesis
from tradingagents.research.insight_supplement import compile_delta, rebase_catalog, supported_prior
from tradingagents.research.insights import (
    compile_insights as _compile_insights,
    normalize_insight_references,
    project_insight_text,
)
from tradingagents.research.jev_candidates import select_jev_candidates
from tradingagents.research.native_versions import (
    EXPERIMENTAL_INSIGHT_CONTEXT_POLICY,
    LEGACY_INSIGHT_CONTEXT_POLICY,
    SLIM_INSIGHT_CONTEXT_POLICIES,
)
from tradingagents.research.numeric_catalog import render_numeric_anchor
from tradingagents.runtime.research_checkpoint import ResearchCheckpointConflict

CAPABILITY_CALLS_PER_ROLE = 2
MAX_DECISION_CONFLICT_QUESTIONS = 126  # Leave two of 128 slots for support and reasoning.


def catalog_prompt(catalog, query='', *, compact=False, include_passages=True, omit_empty=False, coalesce=False, source_aliases=None):
    """All facts remain visible; quote bounded original passages without full payload duplication."""
    sources = [s.model_dump(mode='json') for s in catalog.sources]
    passages = []
    if include_passages:
        context = {'sources': sources, 'facts': [{'evidence_ids': e.source_ids} for e in catalog.evidence]}
        passages = retrieve_evidence(context, query or ' '.join(e.text for e in catalog.evidence), coalesce=coalesce)
    metadata = [{**{k: value[k] for k in ('evidence_id', 'source_name', 'source_kind', 'published_at',
        'usable_as_of', 'public_url', 'limitations')}, 'locator': (value.get('content') or {}).get('locator_label')}
        for value in sources]
    evidence = [e.model_dump(mode='json') for e in catalog.evidence]
    if compact:
        aliases = source_aliases if source_aliases is not None else {s.evidence_id: f'S{i}' for i, s in enumerate(catalog.sources, 1)}
        for fact in evidence:
            fact.pop('fact_id')  # Host identity is not a model-written research field.
            fact['source_ids'] = [aliases[s] for s in fact['source_ids']]
        for source in (*metadata, *passages):
            source['evidence_id'] = aliases[source['evidence_id']]
    numbers = [{'ref': n.ref, 'description': render_numeric_anchor(n.anchor.model_dump(mode='json')),
                'limitations': n.anchor.limitations} for n in catalog.numbers]
    if omit_empty:
        for item in (*evidence, *metadata, *numbers):
            for key in ('limitations', 'locator', 'published_at', 'public_url'):
                if key in item and item[key] in (None, '', [], ()):
                    del item[key]
    return {'evidence': evidence, 'sources': metadata,
        **({'source_passages': passages,
            'passage_scope': 'Selected exact excerpts; full saved sources remain available in the report.'}
           if include_passages else {}),
        'numbers': numbers}


def _catalog_for_refs(catalog, refs):
    evidence = tuple(card for card in catalog.evidence if card.ref in refs)
    fact_ids = {card.fact_id for card in evidence}
    source_ids = {sid for card in evidence for sid in card.source_ids}
    return catalog.model_copy(update={
        'evidence': evidence,
        'sources': tuple(source for source in catalog.sources if source.evidence_id in source_ids),
        'numbers': tuple(n for n in catalog.numbers if set(n.anchor.required_fact_ids) <= fact_ids
                         and set(n.anchor.input_evidence_ids) <= source_ids),
    })


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
                         ensure_active, on_stage=lambda stage, status: None, source_gaps=(), supplement=None, focus_question=None, company_basics=None, foundation_catalog=None,
                         capability=None, capability_catalog=None):
    capability_catalog = capability_catalog or {}
    identity = {'run_id': run_id, 'ticker': ticker, 'date': analysis_date.isoformat(),
                'catalogs': {r: c.model_dump(mode='json') for r, c in catalogs.items()}, 'gaps': list(source_gaps), 'focus_question': focus_question,
                'company_basics': company_basics.model_dump(mode='json') if company_basics else None,
                'foundation': foundation_catalog.model_dump(mode='json') if foundation_catalog else None}
    digest = canonical_sha256(identity)
    prior = journal.state.get('insight.input_digest')
    if prior is not None and prior != digest:
        raise ResearchCheckpointConflict('insight input changed')
    if prior is None:
        journal.put('insight.input_digest', digest)
        journal.put('insight.catalogs', identity['catalogs'])
    if journal.state.get('insight.report') is not None:
        return parse_insight_report(journal.state['insight.report'])
    ensure_active()
    policy = journal.state['identity'].get('insight_context_policy')
    experiment = policy == EXPERIMENTAL_INSIGHT_CONTEXT_POLICY
    slim = policy in SLIM_INSIGHT_CONTEXT_POLICIES
    compact = slim or policy == LEGACY_INSIGHT_CONTEXT_POLICY
    review_config = journal.state['identity'].get('config', {})
    targeted_review = review_config.get('insight_review_policy') == TARGETED_REVIEW_POLICY
    gaps, stages, insights = list(source_gaps), {}, []
    catalog_history = {canonical_sha256(c.model_dump(mode='json')): c for c in catalogs.values()}
    if foundation_catalog is not None:
        catalog_history[canonical_sha256(foundation_catalog.model_dump(mode='json'))] = foundation_catalog
    superseded_ids = []
    if experiment:
        aliases = {role: {prefix: {} for prefix in 'ESN'} for role in catalogs}
        catalogs = {role: rebase_catalog(catalog, aliases[role]) for role, catalog in catalogs.items()}
        catalog_history.update((canonical_sha256(c), c) for c in catalogs.values())
        frozen_contexts = {}
    journal.put('insight.catalog_history', {key: c.model_dump(mode='json') for key, c in catalog_history.items()})

    def compile_insights(payload, **kwargs):
        kwargs.setdefault("analysis_date", analysis_date if experiment else None)
        return _compile_insights(payload, **kwargs)

    def ask(stage, context, phase='main'):
        ensure_active()
        on_stage(stage, 'running')
        try:
            raw = caller(stage, context, phase=phase)
            if (phase == 'main' or phase.startswith('supplement_')) and stage in catalogs and isinstance(raw, dict):
                suffix = '' if phase == 'main' else '.' + phase
                questions = raw.get('search_requests', [])
                if isinstance(questions, list):
                    valid = tuple(dict.fromkeys(q.strip() for q in questions if isinstance(q, str) and 0 < len(q.strip()) <= 400))
                    journal.put('insight.search_requests.' + stage + suffix, list(valid))
                    if len(valid) != len({q.strip() for q in questions if isinstance(q, str)}):
                        gaps.append('search_request_invalid')
                else:
                    gaps.append('search_request_invalid')
                if 'capability_catalog' in context:
                    values = raw.get('capability_requests', [])
                    accepted = {}
                    for value in values if isinstance(values, list) else ():
                        try:
                            request = CapabilityRequest.model_validate(value).model_dump(mode='json')
                        except ValidationError:
                            gaps.append('capability_request_invalid')
                            continue
                        accepted[canonical_sha256(request)] = request
                    if not isinstance(values, list):
                        gaps.append('capability_request_invalid')
                    journal.put('insight.capability_requests.' + stage + suffix, list(accepted.values()))
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
            context = {**catalog_prompt(catalog, compact=compact, omit_empty=slim, coalesce=slim), 'search_requests_allowed': supplement is not None,
                **({'capability_catalog': capability_catalog.get(role, [])} if capability is not None else {})}
            if experiment:
                frozen_contexts[role] = {key: value for key, value in context.items()
                                         if key in {'evidence', 'sources', 'numbers', 'source_passages', 'passage_scope'}}
            if key + '.main' in journal.state:
                saved = journal.state[key + '.main']
                main = InsightBatch.model_validate(saved['batch'])
                repair_items = saved['repair_items']
            else:
                raw = ask(role, context)
                try:
                    main = compile_insights(raw, catalog=catalog, role=role, normalize_refs=True)
                except ValueError:
                    main = InsightBatch()
                repair_items = [
                    {'target': item.index, 'proposal': item.proposal.model_dump(mode='json'),
                     'issues': list(item.issues), 'fields': []}
                    for item in main.items if item.status != 'accepted']
                for rejected in main.rejected:
                    draft = raw['insights'][rejected.index]
                    # Save only the known fields of the rejected draft for the repair task.
                    draft = {k: v for k, v in draft.items()
                             if (k in {'claim', 'reasoning', 'limitations'} and isinstance(v, str))
                             or (k == 'evidence_refs' and isinstance(v, list)
                                 and all(isinstance(ref, str) for ref in v))} if isinstance(draft, dict) else {}
                    if draft:
                        repair_items.append({'target': rejected.index, 'proposal': draft,
                            'issues': [rejected.code], 'fields': list(rejected.fields)})
                journal.put(key + '.main', {'batch': main.model_dump(mode='json'), 'repair_items': repair_items})
            batch = main
            unknown = journal.state.get(f'insight.failure.{role}.main') == 'response_unknown'
            if not unknown and repair_items:
                failed = {task['target'] for task in repair_items}
                repair_context = context
                if slim and all(task['issues'] == ['insight_schema_invalid'] and task['fields'] == ['<undeclared>']
                                for task in repair_items):
                    # The saved drafts already dropped undeclared keys. Shrink only if the remaining
                    # drafts independently validate; never guess missing or malformed E/N references.
                    checked = compile_insights({'insights': [task['proposal'] for task in repair_items]},
                        catalog=catalog, role=role, normalize_refs=True)
                    if not checked.rejected and all(item.status == 'accepted' for item in checked.items):
                        facts = {fact_id for item in checked.items for fact_id in item.fact_ids}
                        scoped = _catalog_for_refs(catalog, {card.ref for card in catalog.evidence if card.fact_id in facts})
                        repair_context = {**catalog_prompt(scoped, compact=True, include_passages=False, omit_empty=True),
                                          'search_requests_allowed': False}
                raw = ask(role, {**repair_context, 'repair_items': repair_items}, 'repair')
                entries = raw.get('repairs') if isinstance(raw, dict) and set(raw) == {'repairs'} else None
                replacements, seen, duplicates = {}, set(), set()
                for entry in entries if isinstance(entries, list) else ():
                    try:
                        repair = InsightRepairItem.model_validate(entry)
                    except ValidationError:
                        continue
                    if repair.target not in failed:
                        continue
                    if repair.target in seen:
                        duplicates.add(repair.target)
                    seen.add(repair.target)
                    if repair.proposal is not None:
                        replacements[repair.target] = repair.proposal
                for target in duplicates:
                    replacements.pop(target, None)
                repaired = compile_insights({'insights': list(replacements.values())}, catalog=catalog,
                    role=role, indices=list(replacements), normalize_refs=True)
                valid = {i.index: i for i in repaired.items if i.status == 'accepted'}
                items = {item.index: item for item in main.items} | valid
                batch = InsightBatch(items=tuple(items[index] for index in sorted(items)),
                    rejected=tuple(item for item in main.rejected if item.index not in valid))
            elif not unknown and not main.items and not main.rejected:
                # No usable response to repair. Keep the existing bounded retry.
                raw = ask(role, context, 'repair')
                with contextlib.suppress(ValueError):
                    batch = compile_insights(raw, catalog=catalog, role=role, normalize_refs=True)
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
    # Structured capability requests run before web questions each round and keep separate budgets.
    cap_pending, cap_seen, cap_used = [], set(), {}

    def queue_capabilities(role, suffix=''):
        for value in journal.state.get('insight.capability_requests.' + role + suffix, ()):
            identity = (role, canonical_sha256(value))
            if identity in cap_seen:
                continue
            cap_seen.add(identity)
            if cap_used.get(role, 0) >= CAPABILITY_CALLS_PER_ROLE:
                gaps.append('capability_role_limit:' + role)
                continue
            cap_used[role] = cap_used.get(role, 0) + 1
            cap_pending.append((role, value))

    if capability is not None:
        for role in catalogs:
            queue_capabilities(role)
    last_round = 2 if experiment else 3
    for round_id in range(1, last_round + 1):
        web = supplement is not None and bool(pending)
        if not cap_pending and not web:
            break
        affected = []
        prior_catalogs = catalogs
        round_gaps = []
        if cap_pending:
            selected, cap_pending = cap_pending, []
            scoped = {}
            for owner, value in selected:
                scoped.setdefault(owner, []).append(value)
            ensure_active()
            result = capability({role: tuple(values) for role, values in scoped.items()}, round_id)
            gaps.extend(result['gaps'])
            round_gaps.extend(result['gaps'])
            if not result['affected_roles']:
                gaps.append('capability_no_qualified_delta')
            affected.extend(result['affected_roles'])
            catalogs = result['catalogs']
        if web:
            selected, pending = pending[:3], pending[3:]
            scoped = {role: tuple(question for owner, question in selected if owner == role) for role in catalogs}
            scoped = {role: values for role, values in scoped.items() if values}
            ensure_active()
            result = supplement(scoped, round_id)
            gaps.extend(result['gaps'])
            round_gaps.extend(result['gaps'])
            if not result['affected_roles']:
                gaps.append('search_no_qualified_delta')
            affected.extend(result['affected_roles'])
            catalogs = result['catalogs']
        if experiment:
            catalogs = {role: rebase_catalog(catalog, aliases[role]) for role, catalog in catalogs.items()}
            for role, catalog in catalogs.items():
                old = prior_catalogs[role]
                if ({e.ref for e in catalog.evidence} != {e.ref for e in old.evidence}
                        or {n.ref for n in catalog.numbers} != {n.ref for n in old.numbers}):
                    affected.append(role)
        affected = [role for role in catalogs if role in affected]
        if experiment:
            round_key = f'insight.supplement.round.{round_id}.input'
            round_digest = canonical_sha256({'catalogs': {role: c.model_dump(mode='json') for role, c in catalogs.items()},
                                              'affected': affected, 'gaps': round_gaps})
            if journal.state.get(round_key, round_digest) != round_digest:
                raise ResearchCheckpointConflict('insight supplement catalog changed')
            if round_key not in journal.state:
                journal.put(round_key, round_digest)
        if not affected:
            break
        catalog_history.update((canonical_sha256(c.model_dump(mode='json')), c) for c in catalogs.values())
        journal.put('insight.catalog_history', {key: c.model_dump(mode='json') for key, c in catalog_history.items()})
        for role in affected:
            key = f'insight.batch.{role}.supplement_{round_id}'
            supplement_ok = True
            if experiment:
                current = catalogs[role]
                previous = {i.insight_id: i for i in insights if i.role == role and i.status == 'accepted'}
                frozen = frozen_contexts.get(role, {})
                full = catalog_prompt(current, compact=True, omit_empty=True, coalesce=True,
                                      source_aliases=aliases[role]['S'])
                delta, removed = {}, []
                for field in ('evidence', 'sources', 'numbers', 'source_passages'):
                    ref_key = 'ref' if field in {'evidence', 'numbers'} else 'evidence_id'
                    base = frozen.get(field, [])
                    if field == 'source_passages':
                        # Direct excerpts belonging to newly seen sources only. Previously selected
                        # excerpts remain in the exact frozen prefix; facts are always sent in full.
                        original_sources = {row['evidence_id'] for row in frozen.get('sources', [])}
                        delta[field] = [row for row in full[field] if row['evidence_id'] not in original_sources]
                    else:
                        original_rows = {row[ref_key]: row for row in base}
                        delta[field] = [row for row in full[field] if row != original_rows.get(row[ref_key])]
                        removed.extend(sorted(original_rows.keys() - {row[ref_key] for row in full[field]}))
                old = prior_catalogs[role]
                new_e = {e.ref for e in current.evidence} - {e.ref for e in old.evidence}
                new_n = {n.ref for n in current.numbers} - {n.ref for n in old.numbers}
                delta_refs = new_e | new_n
                critical = new_n | {e.ref for e in current.evidence if e.ref in new_e and
                    any('conflict' in flag.lower() for flag in e.limitations)}
                if any('conflict' in gap.lower() for gap in round_gaps):
                    critical |= new_e
                if key in journal.state:
                    saved = journal.state[key]
                    batch = InsightBatch.model_validate(saved['batch'])
                    excluded = saved['excluded']
                    supplement_ok = saved['ok']
                else:
                    context = {**frozen, 'delta_catalog': delta, 'retired_refs': removed,
                        'round_delta_refs': sorted(delta_refs), 'material_delta_refs': sorted(critical),
                        'search_requests_allowed': supplement is not None and round_id < last_round,
                        **({'capability_catalog': capability_catalog.get(role, [])}
                           if capability is not None and round_id < last_round else {}),
                        'previous_findings': [{'target': target, **project_insight_text(i, catalog_history[i.catalog_id], current)}
                                              for target, i in previous.items()]}
                    raw = ask(role, context, f'supplement_{round_id}')
                    try:
                        batch, excluded = compile_delta(raw, previous=previous, catalog=current,
                            history=catalog_history, delta_refs=delta_refs, critical_refs=critical,
                            role=role, revision=round_id + 1, analysis_date=analysis_date)
                    except (ValueError, ValidationError):
                        batch, supplement_ok = InsightBatch(), False
                        usable = supported_prior(previous, current, catalog_history) if not critical else set()
                        excluded = [target for target in previous if target not in usable]
                    journal.put(key, {'batch': batch.model_dump(mode='json'), 'excluded': excluded, 'ok': supplement_ok})
                superseded_ids.extend(excluded)
                insights = [i.model_copy(update={'status': 'excluded'}) if i.insight_id in excluded else i for i in insights]
            else:
                previous = [i for i in insights if i.role == role and i.status != 'excluded']
                superseded_ids.extend(i.insight_id for i in previous)
                insights = [i.model_copy(update={'status': 'excluded'}) if i in previous else i for i in insights]
                if key in journal.state:
                    batch = InsightBatch.model_validate(journal.state[key])
                else:
                    context = {**catalog_prompt(catalogs[role], compact=compact, omit_empty=slim, coalesce=slim),
                        'search_requests_allowed': supplement is not None and round_id < last_round,
                        **({'capability_catalog': capability_catalog.get(role, [])}
                           if capability is not None and round_id < last_round else {}),
                        'previous_findings': [project_insight_text(i, catalog_history[i.catalog_id], catalogs[role])
                            for i in previous],
                        'instruction': '资料已更新。重新核查本专项观点；旧观点不会自动用于综合。'}
                    raw = ask(role, context, f'supplement_{round_id}')
                    try:
                        batch = compile_insights(raw, catalog=catalogs[role], role=role, revision=round_id + 1, normalize_refs=True)
                    except ValueError:
                        batch = InsightBatch()
                    journal.put(key, batch.model_dump(mode='json'))
            if supplement_ok and supplement is not None:
                for question in journal.state.get(f'insight.search_requests.{role}.supplement_{round_id}', ()):
                    if (role, question) not in seen_questions:
                        seen_questions.add((role, question))
                        pending.append((role, question))
                        requests[role] = (*requests.get(role, ()), question)
            if supplement_ok and capability is not None:
                queue_capabilities(role, f'.supplement_{round_id}')
            insights.extend(batch.items)
            usable = insights if experiment else batch.items
            finish(role, 'completed' if any(i.status == 'accepted' and i.role == role for i in usable) else 'failed')
            if not supplement_ok or not experiment and (not batch.items or batch.rejected or any(i.status != 'accepted' for i in batch.items)):
                gaps.append(role + '_supplement_unresolved')
    if pending:
        gaps.append('search_requests_remaining')
    if cap_pending:
        gaps.append('capability_requests_remaining')

    merged = merge_catalogs(catalogs)
    journal.put('insight.review_catalog', merged.model_dump(mode='json'))
    merged_id = canonical_sha256(merged.model_dump(mode='json'))
    catalog_history[merged_id] = merged
    journal.put('insight.catalog_history', {key: c.model_dump(mode='json') for key, c in catalog_history.items()})
    targets = {f'I{i}': item for i, item in enumerate((s for s in insights if s.status == 'accepted'), 1)}
    merged_refs = {card.fact_id: card.ref for card in merged.evidence}
    def project_targets(values):
        result = []
        for ref, item in values.items():
            texts = project_insight_text(item, catalog_history[item.catalog_id], merged)
            result.append({'ref': ref, 'insight_id': item.insight_id, **texts,
                'evidence_refs': [e.ref for e in merged.evidence if e.fact_id in item.fact_ids]})
        return result

    def note(text, refs, *, claim='研究审阅', catalog=merged):
        compiled = compile_insights({'insights': [{'claim': claim, 'evidence_refs': list(refs),
            'reasoning': text, 'limitations': '研究意见，不能视为事实证明。'}]}, catalog=catalog, role='review', normalize_refs=True)
        if compiled.rejected:
            raise ValueError(compiled.rejected[0].code)
        compiled = compiled.items[0]
        if set(compiled.issues) - {'evidence_missing'}:
            raise ValueError(next(issue for issue in compiled.issues if issue != 'evidence_missing'))
        # The subset shares the merged aliases and identities. Persist the canonical catalog once.
        return compiled.model_copy(update={'catalog_id': merged_id}) if catalog is not merged else compiled

    # ===== Jev Verification Stage =====
    from tradingagents.agents.schemas._insight import JevVerificationMeta
    pre_reviews = []  # verified / failed reviews produced by Jev, not by Challenge LLM
    challenge_targets = dict(targets)  # default: all targets go to Challenge
    if 'insight.jev_verifications' not in journal.state:
        jev_enabled = journal.state['identity'].get('jev_verification_enabled', False)
        threshold_clear = journal.state['identity'].get('jev_threshold_clear', 0.85)
        threshold_risk = journal.state['identity'].get('jev_threshold_risk', 0.15)

        if jev_enabled and targets:
            on_stage('jev_verify', 'running')
            verifications = {}
            jev_diagnostics = []

            projected = {item['ref']: item for item in project_targets(targets)}
            for ref, item in targets.items():
                evidence_cards = [e for e in merged.evidence if e.fact_id in item.fact_ids]

                # Build per-evidence conflict questions (each evidence gets its own noul)
                questions = {
                    "evidence_sufficient": {
                        "type": "noul",
                        "instructions": "引用的证据卡片是否充分支持该观点的程度与范围？",
                        "criteria": {
                            "true": "证据直接覆盖观点主张，数量与质量足够",
                            "false": "证据不足、证据与观点主张存在程度差距、或推理需要额外假设"
                        }
                    },
                    "reasoning_sound": {
                        "type": "noul",
                        "instructions": "从证据到观点的推理链是否严密？",
                        "criteria": {
                            "true": "每步推理都有明确依据，无因果跳跃",
                            "false": "存在未说明的因果假设、或将相关性当作因果、或忽略其他可能解释"
                        }
                    }
                }
                conflict_candidates = merged.evidence
                partial_coverage = targeted_review and len(conflict_candidates) > MAX_DECISION_CONFLICT_QUESTIONS
                if experiment:
                    view = projected[ref]
                    conflict_candidates, partial_coverage = select_jev_candidates(merged.evidence,
                        cited=view['evidence_refs'], claim=view['claim'], reasoning=view['reasoning'])
                elif partial_coverage:
                    cited = projected[ref]['evidence_refs']
                    related = related_fact_refs(merged.evidence,
                        projected[ref]['claim'] + ' ' + projected[ref]['reasoning'],
                        excluded=set(cited), limit=MAX_DECISION_CONFLICT_QUESTIONS)
                    priority = dict.fromkeys((*cited, *related, *(e.ref for e in merged.evidence)))
                    chosen = set(list(priority)[:MAX_DECISION_CONFLICT_QUESTIONS])
                    conflict_candidates = tuple(e for e in merged.evidence if e.ref in chosen)
                if experiment and len(conflict_candidates) > MAX_DECISION_CONFLICT_QUESTIONS:
                    verifications[item.insight_id] = {'scores': {}, 'conflicts': [], 'risk_level': 'jev_uncertain',
                                                      'partial_conflict_coverage': True}
                    continue
                for e in conflict_candidates:
                    questions[f"conflict_{e.ref}"] = {
                        "type": "noul",
                        "instructions": (f"完整证据 {e.ref} 是否与该观点冲突？" if experiment else
                                         f"证据 {e.ref}（{e.text[:80]}）是否与该观点冲突？"),
                        "criteria": {
                            "true": "存在时间、数值、方向性矛盾",
                            "false": "与观点一致或互补或不相关"
                        }
                    }

                insight_state = {
                    "insight": {field: projected[ref][field]
                                for field in ('claim', 'reasoning', 'limitations')},
                    "cited_evidence": [
                        {"ref": e.ref, "text": e.text, "limitations": list(e.limitations)}
                        for e in evidence_cards
                    ],
                    "global_evidence": [
                        {"ref": e.ref, "text": e.text if experiment else e.text[:200]}
                        for e in (conflict_candidates if experiment else conflict_candidates[:50])
                    ]
                }

                try:
                    ensure_active()
                    scores, meta = caller.call_jev_verification(
                        item.insight_id, insight_state, questions
                    )

                    if experiment and not questions.keys() <= scores.keys():
                        partial_coverage = True

                    # Extract base scores
                    sufficient = scores.get('evidence_sufficient', 0)
                    sound = scores.get('reasoning_sound', 0)

                    # Find conflicts (any evidence scored high for conflict)
                    conflicts = tuple(
                        k.removeprefix('conflict_')
                        for k, v in scores.items()
                        if k.startswith('conflict_') and (not experiment or k in questions) and v >= threshold_clear
                    )

                    # Classify
                    is_clear = (
                        sufficient >= threshold_clear
                        and sound >= threshold_clear
                        and not conflicts
                        and not partial_coverage
                    )
                    has_low_score = (
                        sufficient <= threshold_risk
                        or sound <= threshold_risk
                    )

                    if is_clear:
                        risk_level = 'jev_clear'
                    elif has_low_score or conflicts:
                        risk_level = 'jev_high_risk'
                    else:
                        risk_level = 'jev_uncertain'

                    verifications[item.insight_id] = {
                        'scores': {k: v for k, v in scores.items() if not k.startswith('conflict_')},
                        'conflicts': list(conflicts),
                        'risk_level': risk_level,
                        **({'partial_conflict_coverage': True} if partial_coverage else {}),
                        'meta': meta
                    }

                except InsightUnavailable as exc:
                    if review_config.get('jev_fallback_model'):
                        journal.put('insight.diagnostics.jev', [{'insight_id': item.insight_id, 'error': str(exc)}])
                        finish('jev_verify', 'failed')
                        raise DecisionVerificationFailed(str(exc)) from None
                    verifications[item.insight_id] = {
                        'scores': {},
                        'conflicts': [],
                        'risk_level': 'jev_failed',
                        'meta': {},
                        'error': str(exc)
                    }
                    gaps.append(f'jev_failed:{item.insight_id}')
                    jev_diagnostics.append({
                        'insight_id': item.insight_id,
                        'error': str(exc)
                    })

            journal.put('insight.jev_verifications', verifications)
            if jev_diagnostics:
                journal.put('insight.diagnostics.jev', jev_diagnostics)
        else:
            journal.put('insight.jev_verifications', {})

    # Route targets based on Jev results
    jev_verifications = journal.state['insight.jev_verifications']
    finish('jev_verify', 'completed' if jev_verifications else 'skipped')
    if jev_verifications:
        challenge_targets = {}
        for ref, item in targets.items():
            v = jev_verifications.get(item.insight_id, {})
            risk = v.get('risk_level')

            if risk == 'jev_clear':
                # Auto-verify: no Challenge needed
                pre_reviews.append(SavedReview(
                    target_id=item.insight_id,
                    status='verified',
                    concern=None,
                    reasoning=f"决策核验通过（充分性 {v['scores'].get('evidence_sufficient', 0):.2f}，推理 {v['scores'].get('reasoning_sound', 0):.2f}，无冲突证据）",
                    source_ids=(),
                    note=None,
                    jev_scores=v['scores'],
                    jev_conflicts=(),
                    jev_meta=JevVerificationMeta(**v['meta']) if v.get('meta') else None,
                ))
            elif risk == 'jev_failed':
                # Jev failed: mark as failed, do NOT fall back to Challenge
                pre_reviews.append(SavedReview(
                    target_id=item.insight_id,
                    status='failed',
                    concern=None,
                    reasoning=f"Jev 验证失败：{v.get('error', '未知错误')}",
                    source_ids=(),
                    note=None,
                ))
            else:
                # jev_uncertain or jev_high_risk → Challenge LLM
                challenge_targets[ref] = item

    review_scopes = {}
    review_context = {'insights': []}
    if not targeted_review:
        review_context = {**catalog_prompt(merged, compact=compact, omit_empty=slim, coalesce=slim), 'insights': project_targets(challenge_targets)}
        conflict_notes = []
        for ref, item in challenge_targets.items():
            conflicts = jev_verifications.get(item.insight_id, {}).get('conflicts', [])
            if conflicts:
                conflict_notes.append(f"{ref}（{item.insight_id}）：Jev 检测到与 {', '.join(conflicts)} 冲突")
        if conflict_notes:
            review_context['jev_conflict_notes'] = conflict_notes
    if targeted_review and challenge_targets:
        projected = project_targets(challenge_targets)
        for view in projected:
            ref = view['ref']
            verification = jev_verifications.get(view['insight_id'], {})
            conflicts = verification.get('conflicts', [])
            required = set(view['evidence_refs']) | set(conflicts)
            if experiment and verification.get('partial_conflict_coverage'):
                # The primary reviewer must still be able to find conflicts excluded by Jev.
                scoped = merged
            else:
                related = related_fact_refs(merged.evidence, view['claim'] + ' ' + view['reasoning'], excluded=required)
                scoped = _catalog_for_refs(merged, required | set(related))
            review_scopes[ref] = scoped
            view.update(allowed_evidence_refs=[e.ref for e in scoped.evidence],
                        allowed_number_refs=[n.ref for n in scoped.numbers],
                        flagged_conflicts=conflicts)
            if verification.get('partial_conflict_coverage'):
                view['partial_conflict_coverage'] = True
        shared = _catalog_for_refs(merged, {e.ref for scope in review_scopes.values() for e in scope.evidence})
        query = ' '.join(view['claim'] for view in projected)
        context = catalog_prompt(shared, query, compact=compact, omit_empty=slim, coalesce=slim)
        # A numeric anchor assembled from multiple scopes belongs to none of those targets.
        visible_numbers = {n.ref for scope in review_scopes.values() for n in scope.numbers}
        context['numbers'] = [n for n in context['numbers'] if n['ref'] in visible_numbers]
        review_context = {**context, 'insights': projected}

    def scoped_review_context(refs):
        # Slice the shared prompt so surviving E/N/S aliases never change.
        views = [item for item in review_context['insights'] if item['ref'] in refs]
        context = {**review_context, 'insights': views}
        if targeted_review:
            evidence_refs = {ref for view in views for ref in view['allowed_evidence_refs']}
            number_refs = {ref for view in views for ref in view['allowed_number_refs']}
            evidence = [card for card in context['evidence'] if card['ref'] in evidence_refs]
            source_ids = {sid for card in evidence for sid in card['source_ids']}
            context.update(evidence=evidence, numbers=[n for n in context['numbers'] if n['ref'] in number_refs],
                sources=[source for source in context['sources'] if source['evidence_id'] in source_ids],
                source_passages=[p for p in context['source_passages'] if p['evidence_id'] in source_ids])
        return context

    reviews = []
    if 'insight.reviews' in journal.state:
        reviews = [SavedReview.model_validate(v) for v in journal.state['insight.reviews']]
    else:
        def parse_reviews(raw, allowed=None):
            accepted, duplicates, diagnostics = {}, set(), []
            candidates = raw.get('reviews', []) if isinstance(raw, dict) else []
            for index, value in enumerate(candidates if isinstance(candidates, list) else []):
                try:
                    review = ReviewProposal.model_validate(value)
                    if review.target not in targets:
                        diagnostics.append({'index': index, 'target': None, 'code': 'target_unknown'})
                        continue
                    if targeted_review and review.target not in challenge_targets:
                        diagnostics.append({'index': index, 'target': review.target, 'code': 'target_not_assigned'})
                        continue
                    if allowed is not None and review.target not in allowed:
                        diagnostics.append({'index': index, 'target': review.target, 'code': 'repair_target_unexpected'})
                        continue
                    if not review.reasoning.strip() or (review.concern is not None and not review.concern.strip()):
                        diagnostics.append({'index': index, 'target': review.target, 'code': 'blank_text'})
                        continue
                    checked = note(review.reasoning, review.evidence_refs, claim=review.concern or '未发现有效反证',
                                   catalog=review_scopes.get(review.target, merged))
                    if review.target in accepted:
                        duplicates.add(review.target)
                    accepted[review.target] = SavedReview(target_id=targets[review.target].insight_id,
                        status='challenged' if review.concern else 'no_counterevidence',
                        concern=checked.rendered.claim if review.concern else None, reasoning=checked.rendered.reasoning,
                        source_ids=checked.source_ids, note=checked)
                except (ValueError, ValidationError) as exc:
                    code = (str(exc) if str(exc) in {'numeric_literal_unbound', 'numeric_scope', 'reference_unknown',
                        'source_unavailable', 'evidence_missing', 'reference_range_invalid'} else 'review_shape_invalid')
                    target = value.get('target') if isinstance(value, dict) else None
                    diagnostics.append({'index': index,
                        'target': target if isinstance(target, str) and target in targets else None, 'code': code})
                    continue
            return accepted, duplicates, diagnostics

        raw = ask('challenge', review_context) if challenge_targets else None
        accepted, duplicates, diagnostics = parse_reviews(raw)
        missing = [ref for ref in challenge_targets if ref not in accepted or ref in duplicates]
        repaired = False
        if (missing and raw is not None
                and journal.state.get('insight.failure.challenge.main') != 'response_unknown'):
            repaired = True
            issues = [item for item in diagnostics if item.get('target') in set(missing)]
            repair_context = {**(scoped_review_context(missing) if slim else review_context),
                              'repair_targets': missing, 'issues': issues}
            if any(item.get('code') in {'numeric_literal_unbound', 'numeric_scope'} for item in issues):
                repair_context['instruction'] = (
                    'Rewrite only the listed targets and remove every Arabic digit from concern/reasoning '
                    '(write dates and amounts in Chinese words, or cite the saved [N] token); cite only saved E references.')
            repair_raw = ask('challenge', repair_context, 'repair')
            repaired_accepted, _, repair_diagnostics = parse_reviews(repair_raw, allowed=set(missing))
            accepted.update(repaired_accepted)
            diagnostics.extend(repair_diagnostics)
            for ref in repaired_accepted:
                duplicates.discard(ref)
        missing = [ref for ref in challenge_targets if ref not in accepted or ref in duplicates]
        for ref in missing:
            diagnostics.append({'index': None, 'target': ref,
                'code': 'repair_unresolved' if repaired else 'review_unavailable' if raw is None else 'target_missing'})
        journal.put('insight.diagnostics.challenge', diagnostics)
        challenge_reviews = [accepted[key] if key in accepted and key not in duplicates else SavedReview(target_id=value.insight_id,
            status='unreviewed' if raw is not None else 'failed') for key, value in challenge_targets.items()]

        # Merge pre-reviews (verified/failed from Jev) with challenge reviews
        reviews = pre_reviews + challenge_reviews

        journal.put('insight.reviews', [r.model_dump(mode='json') for r in reviews])
    if any(r.status in {'unreviewed', 'failed'} for r in reviews):
        gaps.append('unreviewed_insights')
    if targeted_review and not challenge_targets:
        finish('challenge', 'skipped')
    else:
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
            if slim:
                refs_by_id = {item.insight_id: ref for ref, item in assigned.items()}
                role_reviews = [{
                    'target_ref': refs_by_id[r.target_id], 'status': r.status, 'concern': r.concern,
                    'reasoning': r.reasoning, 'evidence_refs': [merged_refs[f] for f in r.note.fact_ids] if r.note else [],
                } for r in reviews if r.target_id in refs_by_id and r.status == 'challenged']
                reply_context = scoped_review_context(assigned)
            else:
                role_reviews = [r.model_dump(mode='json') for r in reviews]
                reply_context = review_context
            raw = ask(stage, {**reply_context, 'assigned': list(assigned), 'reviews': role_reviews})
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
                    reply_catalog = review_scopes.get(reply.target, merged)
                    checked = note(reply.reasoning, reply.evidence_refs, catalog=reply_catalog)
                    replacement = None
                    if reply.action == 'revise':
                        if reply.replacement is None:
                            diagnostics.append({'index': index, 'target': reply.target, 'code': 'replacement_missing'})
                            continue
                        replacement = compile_insights({'insights': [reply.replacement.model_dump(mode='json')]},
                            catalog=reply_catalog, role=role, revision=current.revision + 1, indices=[current.index], normalize_refs=True)
                        if replacement.rejected:
                            diagnostics.append({'index': index, 'target': reply.target, 'code': replacement.rejected[0].code})
                            continue
                        replacement = replacement.items[0]
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
                        replacement_items.append(replacement.model_copy(update={'catalog_id': merged_id})
                                                 if reply_catalog is not merged else replacement)
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
            'reviews': [{'target_id': r.target_id, 'status': r.status, 'concern': r.concern, 'reasoning': r.reasoning,
                         'evidence_refs': [merged_refs[f] for f in r.note.fact_ids] if r.note else []}
                        if slim else r.model_dump(mode='json') for r in reviews],
            'responses': [{'target_id': r.target_id, 'action': r.action, 'reasoning': r.reasoning, 'replacement_id': r.replacement_id,
                           'evidence_refs': [merged_refs[f] for f in r.note.fact_ids]}
                          if slim else r.model_dump(mode='json') for r in responses],
            'reviewed_targets': [{'ref': i['ref'], 'insight_id': i['insight_id']} for i in review_context['insights']], 'gaps': gaps,
            'sources': catalog_prompt(synthesis_catalog, compact=compact, include_passages=not slim, omit_empty=slim)}
        for phase in ('main', 'repair'):
            raw = ask('synthesis', context, phase)
            try:
                value = SynthesisProposal.model_validate(raw)
                aliases = set(targets)
                value = value.model_copy(update={field: normalize_insight_references(getattr(value, field), aliases)
                    for field in ('judgement', 'reasoning', 'limitations', 'next_check')})
                checked = compile_insights({'insights': [{'claim': value.judgement,
                    'evidence_refs': list(value.insight_refs), 'reasoning': value.reasoning,
                    'limitations': value.limitations + '\n' + value.next_check}]}, catalog=final_catalog, role='synthesis', analysis_date=None).items[0]
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
            raw = ask('focus_response', {**catalog_prompt(merged, query=focus_question, compact=compact, omit_empty=slim, coalesce=slim),
                'question': focus_question, 'insights': project_targets(targets), 'search_requests_allowed': False,
                'synthesis': synthesis.model_dump(mode='json') if synthesis else None})
            with contextlib.suppress(ValueError):
                focus_batch = compile_insights(raw, catalog=merged, role='focus_response', normalize_refs=True)
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
