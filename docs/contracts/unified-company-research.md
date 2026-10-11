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

The closed investment stance is favorable, neutral, unfavorable or insufficient
evidence. Up to three supporting and three opposing reasons bind to saved claims
and optional reply IDs. Public change conditions bind to an original hypothesis,
its exact invalidation text and index. Every challenge has a separate synthesis
adjudication linked to its reply. The deterministic V2 local evidence outcomes
remain unchanged; a reply/adjudication cannot resolve the economic parent question.

Missing actual operating or valuation support requires insufficient evidence.
A critical unresolved challenge or absent cited valuation anchor prohibits a
favorable stance. A valuation object elsewhere in the record, or a low multiple
alone, is insufficient. These are evidence gates, not a price forecast or an
invented confidence score.

## Execution and adapters

V7 permits at most eight main calls (three initial specialists, critic, three
replies and synthesis), one optional post-baseline focus and twelve actual model
attempts total. Repairs and network retries consume that same attempt ceiling.
The two-repair/shared-three-retry limits and data/verification ceilings remain.
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
