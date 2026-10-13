# Unified company investment research

- **Status: Current**
- Canonical: `research/native_versions.py`, `agents/schemas/_research_dialogue.py`,
  `agents/schemas/_research_assessment.py`, `research/unified_assessment.py`.

New Web single and batch studies use `evidence-production-v7` /
`native-research-kernel-v6`. The sole new-study scope is `company_research`:
assess investment attractiveness as of the analysis date using operating quality,
current valuation, event impact/delivery and market context. There is no forced
84-day outlook or mode/debate-round selector. Prior V1–V6 identities and mode
semantics remain available for reading and recovery.

## Bounded evidence dialogue

Three specialists form isolated evidence-bound hypotheses; operating research
also owns valuation interpretation. The anonymous critic raises at most three
challenges. The host executes existing bounded checks, then calls each targeted
specialist once, at most two concurrently. Zero challenges cause zero reply calls;
several challenges for one specialist share one call. Replies add no retrieval
round and trigger no second challenge cycle.

Fresh identities freeze a specialist reference-isolation policy. One bounded
repair precedes fallback to the original response's independently validated
hypotheses; malformed main JSON/schema is never partially accepted. Rejected
hypotheses cannot enter claims, conditions or dialogue. Effective rejections
force partial/LOW_CONFIDENCE and retain original indices plus closed reasons
for kernel/Reader binding. See [Web evidence research](../operations/evidence-research.md)
for persistence, cancellation and legacy recovery boundaries.

`ResearchDialogueV1` binds every original hypothesis to its specialist, the final
input snapshot and exactly one reply per challenge. Replies may maintain, revise,
withdraw or admit they cannot answer. Each uses only the specialist's qualified
V0 facts, targeted verification facts and bound local checks. The reply input
contains no other specialists' drafts. Original hypotheses and falsifiers remain
unchanged. Specialist or synthesis-revised/withdrawn original inference IDs cannot support dimensions,
key claims or affirmative arguments. A revised argument cites the reply ID and
its supporting facts. Failed replies are host-owned unavailable records; they
make research partial/LOW_CONFIDENCE rather than fabricating a model response.

## Saved investment judgement

The outer `research-record-v1` stays unchanged. V7 final records require
`research-assessment-v3` plus `research-dialogue-v1`; absent dialogue is omitted
from old serialized records. Saved workflow qualification prevents a new schema
from masquerading as an old workflow.

Four dimensions use their code-owned order: operating quality, valuation,
`catalyst_delivery` (V7 label “事件影响与兑现”) and market context. This V7 label
does not redefine historical catalyst research or its 84-day outlook.

Legacy investment stances are favorable, neutral, unfavorable or insufficient
evidence. New report-delivery records may be unrated as described below. Up to three supporting and three opposing reasons bind to saved claims
and optional reply IDs. Public change conditions bind to an original hypothesis,
its exact invalidation text and index. Every challenge has a separate synthesis
adjudication linked to its reply. The deterministic V2 local evidence outcomes
remain unchanged; a reply/adjudication cannot resolve the economic parent question.

Earlier V7 runs freeze `company_research_policy=timestamped-quote-cautious-judgement-v1`.
Missing actual operating support requires insufficient evidence. Missing valuation
inputs or a reference range restrict the valuation dimension and prohibit favorable,
but permit neutral/unfavorable conclusions with qualified operating support and
referenced reasons. Missing inputs remain visible; no value range is invented.
Older records without this policy marker retain their original overall gate.
A critical unresolved challenge or absent cited valuation anchor also prohibits a
favorable stance. A valuation object elsewhere in the record, or a low multiple
alone, is insufficient. These are evidence gates, not a price forecast or an
invented confidence score.

Fresh identities additionally freeze
`report_delivery_policy=company-basics-local-gaps-delivery-v1`. Optional
`company_basics` binds explicit public introduction, latest basic financials
and quantitative observations to qualified saved fact IDs. Sina profile fields
are security/exchange verified and admitted only for their capture date; a saved
explicit official main-business excerpt can provide a fallback. Missing PDF
detail, broker forecasts, individual metrics and valuation anchors limit their
own sections. All specialists see a common read-only foundation while hypothesis
references and drafts remain role-scoped.

For this policy, code restores the selected hypothesis/index's original
invalidation text and the saved challenge's reply ID/disposition before public
validation. It does not invent reasons or fix fabricated factual references.
A referenced cautious judgement can survive an unresolved dimension; favorable
still requires operating support and a cited valuation anchor without a critical
challenge. An `insufficient_evidence` model proposal becomes an explicitly
unrated delivered analysis, rather than a blanket verdict.

V3 `report_status` separates delivery from analytical coverage: `synthesized`
has a formed stance; `analysis_unrated` has usable synthesis but no overall
rating; `specialist_summary`/`basic_report` retain saved findings after unusable
synthesis. The latter states explicitly mark synthesis unfinished and never
attribute a host summary to the synthesis model. Revised/withdrawn originals
remain excluded. Only new-policy records allow a null stance. Old records omit
the new fields and preserve their bytes, prompts, labels and recovery identity.
Cancellation, deadlines and checkpoint failures remain lifecycle failures.

## Execution and adapters

V7 permits at most eight main calls (three initial specialists, critic, three
replies and synthesis), one optional post-baseline focus and twelve actual model
attempts total. Repairs and network retries consume that same attempt ceiling.
The two-repair/shared-three-retry limits and data/verification ceilings remain.
V7 specialist parsing checks financial condition operands and metric sources
against the evidence of their own hypothesis before saving a proposal. Invalid
bindings use the existing bounded repair opportunity; if repair fails, a fresh
specialist keeps only its independently validated hypotheses, with local rejection
limitations, and the remaining research can publish a limited
record. The kernel repeats the same binding check for supplied proposals;
condition-binding failures are evidence rejection, not missing provider configuration.
New V7 reference repairs include fixed validation feedback about the failed
binding, repeating the allowed dimension IDs when necessary. Previously saved
generic repair prompts keep their exact hashes; unknown dispatches are never
replayed and repair/attempt limits are unchanged.
Known public-record root failures retain distinct closed codes for change-condition
bindings, adjudication/reply bindings, excluded support and argument references.
The same single repair can repeat exact saved condition tuples or reply bindings;
arbitrary exception messages and failed response text remain excluded from diagnostics.
Fresh V7 specialist/synthesis stages also persist a binding-guidance marker
before their first prompt is frozen. They repeat the existing structure and
reference constraints near the response instruction. A stage with an already
saved prompt does not acquire this marker or change its prompt hash on recovery.
Fresh V7 synthesis requests additionally persist a prompt-local reference-alias
marker. Saved identifier definitions are sorted into short aliases by kind;
only reference fields are translated, leaving prose, invalidation text and
closed check IDs unchanged. Responses map exact aliases back to canonical IDs
before the existing schema and public-record gates run. Unknown aliases are
not guessed or repaired by the mapper. Canonical proposals remain the saved
artifact, and already frozen synthesis prompts retain their original format.
The alias prompt also spells out the existing argument-to-reply fact rule:
when an argument cites a response, every cited claim must be one of that
response's supporting facts, including for maintained replies. A fixed
allowlisted diagnostic can supply these saved bindings to bounded repair;
raw response text and arbitrary validator messages are never included.
V6 keeps its original five/one/twelve policy. Stable reservation/merge order,
checkpoint caching and unknown-dispatch non-replay apply to replies too.
Reply tasks reuse the corresponding specialist's configured model effort.

Omitted Web mode means company research even if holding input is present.
Explicit catalyst/holding creation or retry returns HTTP 422
`unified_research_mode_required`; a company request with holding input retains
`holding_not_allowed`. Retired profile admission still precedes mode checks.
Reading and recovering prior modes never rewrites them; the UI offers a separate
new company study when an old scope cannot be retried.

Reader, process/Agent projections and Markdown consume the committed saved record.
They expose stance, reasons, counterevidence, falsifiers, four dimensions and the
original hypothesis → challenge → code check → reply → adjudication chain.
Reply roles and counts are selected by saved workflow version; no-target replies
are explicitly not applicable. The maintained external record entry remains
`/api/runs/{id}/reader/record`; V7 does not create a native research-package endpoint.
Optional focus remains independent and cannot change the baseline judgement.

See [evidence operations](../operations/evidence-research.md),
[record contract](research-record.md) and [Reader architecture](../architecture/research-reader.md).
