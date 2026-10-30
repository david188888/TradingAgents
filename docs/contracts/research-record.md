# Research record and execution contract

Status: Current

This reference owns the important research invariants; complete fields and enums remain in code.
Use [architecture](../../ARCHITECTURE.md) for responsibilities and
[Web operations](../operations/evidence-research.md) for user actions.

## Versions and canonical sources

| Surface | Canonical owner |
| --- | --- |
| Request/result | [execution/models.py](../../tradingagents/execution/models.py); Web admission in [web/schemas.py](../../tradingagents/web/schemas.py) and [api.py](../../tradingagents/web/api.py) |
| Workflow and frozen policy | [native_versions.py](../../tradingagents/research/native_versions.py), [native_runner.py](../../tradingagents/execution/native_runner.py) |
| Public record and version dispatch | [V1 schema](../../tradingagents/agents/schemas/_research_record.py), [V2 schema](../../tradingagents/agents/schemas/_research_record_v2.py), [record_codec.py](../../tradingagents/research/record_codec.py) |
| Model proposals and acceptance | [agents/schemas](../../tradingagents/agents/schemas/), [native_model.py](../../tradingagents/execution/native_model.py), [native_research.py](../../tradingagents/graph/native_research.py) |
| Publication and read qualification | [native_publication.py](../../tradingagents/execution/native_publication.py), [web/native_reader_versions.py](../../tradingagents/web/native_reader_versions.py) |
| Browser wire shape | [frontend/src/api/contracts.ts](../../frontend/src/api/contracts.ts), mirroring backend DTOs |

Fresh Web research uses `evidence-production-v9` / `insight-research-v1`. V1–V8 keep their saved
identities, contracts and admission rules. Version dispatch is explicit; never infer it from model names.

## Insight-first V9

Canonical owners are [_insight.py](../../tradingagents/agents/schemas/_insight.py),
[insights.py](../../tradingagents/research/insights.py),
[insight_research.py](../../tradingagents/graph/insight_research.py) and
[insight_report.py](../../tradingagents/research/insight_report.py).
Each Insight has exactly claim, evidence references, reasoning and limitations. The outer submission
also accepts `search_requests`; omitted collections retain their original default type, never `null`
unless the canonical model allows it. IDs, catalog versions, compilation receipts and status are host-owned.

The host unions explicit and inline evidence references. Numeric tokens resolve qualified catalog
values with subject, period and units; explicit unbound quantities stay pending. Bare years/codes are
not automatically rejected. Invalid items do not discard accepted siblings; specialist and synthesis
repair is bounded to one attempt. Missing, unknown or stale references cannot support a rating.
Source traceability and bounded arithmetic do not certify all natural-language entailment.

New V9 runs freeze `insight_context_policy=compact-saved-evidence-v1`. Prompt catalogs use short
source labels instead of host hashes; all specialist/reviewer facts, limitations, numeric descriptions
and selected exact source passages remain visible. Synthesis receives the facts and passages already
supporting effective Insights or their review/reply notes, without the unused numeric catalog.
Runs without this policy retain the previous prompt shape on resume. Source labels locate provenance;
only the supplied evidence/numeric references are admissible model citations.

One review/reply round records doubts, alternatives or the absence of effective counterevidence.
Missing/failed review is distinct from no counterevidence. Revisions and withdrawals preserve the old
version but remove it from effective support. Overall synthesis is atomic: invalid support suppresses
that judgement, while independent Insights and company basics survive. The synthesis Agent decides
whether evidence is sufficient; a missing prescribed valuation anchor is a visible gap, not a code veto.
Rejected replies retain per-item safe diagnostics in the checkpoint: missing/duplicate/unassigned targets,
shape errors, invalid references/numbers or replacement failures. Rejected prose is not persisted.
An older run without these diagnostics cannot be retrospectively classified as model omission versus
validation rejection; an unresolved response remains an explicit research gap.

Supplementary questions are plain text, deduplicated by role and normalized question. The host assigns
company, cutoff, role and search IDs, selecting at most three questions per round and three rounds.
Questions come from specialist output; supplementary reanalysis may identify further gaps within
the same three-round ceiling, with previously processed questions deduplicated. No new qualified delta stops collection. New evidence invalidates affected role
versions until reanalysis; failed reanalysis leaves the prior versions visible but excluded. Source,
HTTP, search activity and model ceilings remain those of fresh V8: 8 main, 1 focus, 8 repair slots,
9 supplementary review attempts, at most 29 total. Unknown dispatched outcomes are not resent.

Focus uses saved evidence after synthesis, with one focus attempt and no repair. It is stored separately
inside the new record and cannot support or change baseline synthesis. Optional explanations are
post-completion reading aids over saved Insight text; coverage is not a research acceptance criterion.

The same durable candidate/authorization/commit barrier protects new publications. Reads replay
Insight, review/reply and synthesis bindings. The record endpoint returns `insight_ready`; stage output
uses `insight_stage_available` without an uncommitted overall rating. These are explicit new wire
variants, not disguised V2 records. Historical variants remain supported.

**Scope below:** the hypothesis/envelope, executable-condition and four-dimensional assessment rules
below describe retained V1/V2 output contracts through V8. Source qualification and lifecycle rules
remain shared where cited above; legacy model gates do not apply to V9 Insights.

## Evidence and inference

A record distinguishes sources, facts, inference/unknown claims, hypotheses, challenges, executed
checks, metrics and assessment. References are run-local and snapshot-bound. A hypothesis needs
cited facts, original falsifiers and alternatives; a title or management plan is not proof of delivery.
Source availability, evidence qualification and economic conclusion are separate questions.

Models propose; code validates source/date/period/unit/identity, reference scope and calculations.
Unknown or unavailable values never become zero. Reposts or derived calculations do not create new
independent source families. User holding facts are declarations only in retained historical modes.

V2 supports at most eight append-only material/derived snapshots. Field qualification records its
first effective snapshot; later qualification cannot retroactively enter old numeric catalogs or
receipts. New conflicts or invalid comparison bases disable stale derived inputs in current views.
Original facts, checks and proofs remain replayable. V1 retains its original two-snapshot boundary.

## Numeric and factual support

[Numeric catalog](../../tradingagents/research/numeric_catalog.py),
[narrative compiler](../../tradingagents/research/numeric_narrative.py) and
[integration](../../tradingagents/research/numeric_integration.py) own `anchored-narrative-v1`.
The model selects scoped references; code renders numeric fragments with units, periods and
actual/forecast labels before assigning public IDs. Literal unbound quantities are rejected.
Receipts bind catalog/context, original proposal, compiled text and final field paths; cache,
publication, Reader and Markdown replay the same proof without model work.

[factual_premises.py](../../tradingagents/research/factual_premises.py) adds host-owned source and
comparable-direction observations, interpretations and pending questions. Observations must stay
within each field's allowed facts; key/overall support has additional binding gates.
These mechanisms certify bindings and bounded arithmetic, not arbitrary sentence entailment.
A correct revenue reference can still accompany an unsupported free-prose causal claim.
Redundant `premises` bindings on existing fields that do not require factual premises (such as
`unknowns` and condition text) are discarded before validating the unused binding contents and
saving the replay envelope, including malformed or over-limit unused contents. Their text still
passes the normal numeric checks. Missing paths, out-of-range indices and a `proposal.` prefix
remain invalid; required premise bindings and structured numeric bindings retain their gates.

Fresh V8 runs freeze `challenge_input_policy=search-trace-summary-v1` in their identity. Only the
challenge model view replaces raw search-batch hits and outcome hits with counts, retaining requests,
status, reasons and usage metadata. Qualified evidence bodies, claims, numeric anchors, observations
and validation contexts stay unchanged. Full search logs remain in the saved record for audit.
Saved runs without this policy retain their original prompts on recovery; unknown policies refuse
resume or model dispatch. This policy changes neither evidence admission nor model/repair budgets.

Fresh V8 runs also freeze `search_gap_guidance_policy=supplied-gap-targets-v1`. Gap prompts and
their prompt schemas state the same role, cutoff and saved hypothesis/challenge targets enforced
by validation. An initial specialist with no saved targets must use empty `target_ids`; fact/source
IDs and newly proposed items cannot be gap targets. Unmarked saved runs retain their original
prompts on recovery. Invalid gap roles, dates and targets still reject, using closed diagnostic codes.

Fresh numeric V8 runs freeze `model_binding_policy=inline-bindings-v1`. Their model-facing
schema keeps narrative text and its premise observations together, proposed plans beside their
own text/date, and structured check values beside their numeric/plan bindings.
[inline_bindings.py](../../tradingagents/research/inline_bindings.py) derives dotted paths from
the actual object keys and array positions, then converts the response to `NumericStageEnvelopeV1`
before the existing schema, scope, quantity, isolation and publication gates. The model cannot
submit `field_path` or top-level `premises`, `plans` or `structured_bindings` in this format.
Unknowns remain qualitative text; unused premise annotations on non-premise text are discarded.
The adapter neither chooses evidence nor guesses/corrects addresses. Saved proofs and public
records keep their canonical formats. Unmarked history retains its original prompt/parser;
unknown or incompatible policies reject before dispatch. This adds no model stage or budget.

Fresh V8 identities freeze `challenge_reference_policy=hypothesis-condition-index-v1`.
The model selects `hypothesis_id` plus a zero-based `condition_index` from that hypothesis's
supplied choices. Conditions are ordered by their canonical IDs within each hypothesis, so JSON
key sorting cannot change index meaning. The shared resolver generates the ID for validation,
kernel task construction and Reader projections. Legacy `condition_id` remains supported; if both
are supplied they must agree. Absent indices are omitted from serialization to preserve old hashes.
Unmarked saved tasks retain their original model-facing condition-ID schema.

`structured_output_policy=provider-schema-or-json-v1` selects the native request format for fresh
V8 tasks. SIWC/OpenAI use a strict JSON Schema; the existing DeepSeek Chat Completions route uses
`json_object`. Other providers retain their prior transport and explicitly record `none`.
[structured_output.py](../../tradingagents/llm_clients/structured_output.py) closes objects, requires
all fields, preserves nullable types, keeps nonnullable collections as arrays, shares identical enum
definitions and checks provider schema limits. Discriminated unions and branches made disjoint by a required
field with unique constant values become `anyOf`; overlapping `oneOf` branches remain rejected.
String length constraints remain in schema guidance
and canonical local validation. Alias substitution follows adaptation. Each request records its method
and, for strict output, schema hash. Unmarked history keeps the original prompt and transport.
Strict output does not prove evidence scope, entailment or semantic correctness; refusals and
incomplete responses still fail admission. The 2026-10-28 SIWC probe confirmed a trivial schema
for `gpt-6.1-terra`, not acceptance of a complete research run.

Fresh numeric V8 also freezes the exact `research_delivery_policy` payload from `native_versions.py`.
`evidence-packets-v1` uses [evidence_packets.py](../../tradingagents/research/evidence_packets.py) to
render all qualified observations as Markdown cards with source, cutoff and limitations. Up to eight
lexically ranked passages (at most 1200 characters each) quote saved sources within the same role
scope. Retrieval cannot qualify a new fact. Models select short card citations; the host restores
observation IDs and derives fact lists from selected observations and numeric anchors, before the
existing canonical validators. Unknown citations reject locally where existing isolation permits;
they are never guessed. Unmarked history retains its original parser, prompts and budgets.

Malformed shared JSON/schema cannot be salvaged as free text. Within existing repair budgets,
independently valid original specialist siblings can survive reference rejection with original
indices and closed reasons; effective rejection forces partial/LOW_CONFIDENCE. A wrong premise or
structured-binding path inside one existing hypothesis rejects only that hypothesis; invalid shared-field,
out-of-range and unaddressable paths still reject the stage. Diagnostics record a closed path-shape
label, never the path or model text. Valid repairs replace
whole proposals rather than combining incompatible main/repair responses.

## Challenge and verification

Under `evidence-packets-v1`, every supplied hypothesis must appear exactly once in a saved review:
`challenged` must match an accepted challenge, while `no_additional_counterevidence` needs its own
source-bound rationale. An empty challenge array without complete reviews is invalid. These separate
receipts bind the challenge proposal and numeric context, replay on recovery/Reader access, and do
not change canonical challenge proofs. Finding no additional counterevidence does not establish
safety, entailment or absence of risk.

Important challenges under `hypothesis-directed-checks-v1` classify verifiability and may propose an
independent check using additional qualified frozen facts. They do not change the target hypothesis
or its original conditions. [challenge_checks.py](../../tradingagents/research/challenge_checks.py)
compiles `verification-plan-v2`; [verification_executor.py](../../tradingagents/execution/verification_executor.py)
uses the existing durable ledger for at most three local tasks in one bounded round.

Checks compare allowed financial operands or saved metrics; they do not execute free expressions,
fetch sources or call models. Financial comparisons require the same evidence record, matching
fields/periods/units and qualified disclosure dates; a shared supplier name alone is insufficient.
Percentage growth needs a positive base. Future observations remain future, not missing past data.

Task outcomes distinguish no generated task, completion, cancellation, budget refusal and unknown
dispatch. Tool failure is executed but unavailable. `challenge_predicate_only` supports/contradicts
only the concrete proposition, never automatically resolves an economic challenge. Original-condition
plans remain for saved identities without the new policy. Canonical classification/outcome types are
[_challenge_verification.py](../../tradingagents/agents/schemas/_challenge_verification.py).

## Financial and price calculations

[structured_financial_checks.py](../../tradingagents/research/structured_financial_checks.py) and
[minimum_evidence.py](../../tradingagents/research/minimum_evidence.py) own the finite check pack.
Calculation-v3 has five ordered checks: operating-disclosure coverage, full cash bridge, valuation
context, structured baseline and same-period profit/CFO comparison. Older versions retain their
own pack; passing an endpoint comparison does not pass a complete reported cash bridge.

Use latest qualified same-period consolidated statements without mixing supplier cells or falling
back to an older complete pair. Consolidated profit and parent-attributable profit are distinct.
Exact Decimal calculations retain amounts for nonpositive bases but omit unsupported growth rates;
conflicts and missing official crosschecks remain visible. Source qualification, arithmetic and
saved input hashes are recomputed at their applicable snapshot.

[native_valuation.py](../../tradingagents/research/native_valuation.py) assembles qualified saved
quotes/history/profit into the pure [valuation chain](../../tradingagents/research/valuation.py).
A historical-multiple reference range is assumption-dependent, not intrinsic value or a trade target.
Missing valuation can prohibit favorable without erasing supported cautious operating analysis.

[price_statistics.py](../../tradingagents/research/price_statistics.py) and
[risk_metrics.py](../../tradingagents/dataflows/risk_metrics.py) compute saved historical return-risk
and ATR statistics after price/calendar/adjustment qualification. They do not replace valuation or
forecast future losses; unavailable benchmark data must not manufacture Beta. Units, methods,
sample/window and lineage travel with the saved metric.

## Search and execution limits

Dedicated APIs remain first for identity/quantitative inputs. DeepSeek Search/Fetch and Tavily
Search/Extract discover context and field-specific fallback. Default Tavily is basic without generated
answers. Queries bind company, code and cutoff; snippets only aid discovery. Unknown publication,
missing original content, future dates and truncation cannot become qualified numerical evidence.
Historical admission requires a verifiable immutable official PDF, not a current web page labelled old.

Supported identity/profile and recognized FY/H1 consolidated financial rows may recover fields after
exact code, period, currency, unit, scope and source-location/hash checks. Other layouts, full adjusted
price windows and valuation snapshots remain unavailable unless the original requirement is met.
Search never silently overwrites a dedicated value; conflict candidates remain explicit.
PDF download/parse bounds are 20 MiB, 500 pages, up to 12 selected pages × 4000 characters.

| Shared V8 pool | Maximum |
| --- | --- |
| Search requests, including failures/retries | DeepSeek 50; Tavily 50 across keys |
| Extra body attempts, including redirects | 8 across Fetch/Extract/PDF |
| Supplementary rounds | 3, selecting at most 3 gaps per round |
| Supplementary model attempts | 3 per round, 9 total including repairs/retries |
| Baseline model attempts | Fresh `evidence-packets-v1`: 20; unmarked history: 12. At most 8 main and 1 focus; repairs/retries consume that same total |
| Baseline repair/retry sub-pools | Fresh policy: 8 structured repairs, at most 1 per stage; unmarked history: 2. Both retain 3 shared transient retries |
| Dedicated data | 24 capability calls / 64 HTTP attempts |
| All data HTTP | 172 attempts |
| Search activity | 90 seconds, union of overlapping intervals, excluding model thinking |
| Whole research | 900 active seconds for new Web studies (300 for saved requests without a value), excluding queue time; effective timeout is frozen in run identity |

Reservations persist before dispatch. Recovery carries spent/unknown attempts forward. Search retries
at most once; access/payment/security rejection does not gain retries or new quota by rotating keys.
No new qualified material, exhausted pools/deadline or unavailable sources produce explicit gaps and
stop reasons; cancellation propagates. A judgement is updated only after its affected review executes.
Baseline plus supplementary review is at most 29 model attempts for the fresh policy, 21 for unmarked
history. Review retries/repairs use the review pool and
its three-attempt per-round ceiling, rather than replenishing baseline repair/retry allowance.
The code-owned [search policy](../../tradingagents/research/native_versions.py),
[search_budget.py](../../tradingagents/execution/search_budget.py),
[search_reviews.py](../../tradingagents/execution/search_reviews.py) and
[_search.py](../../tradingagents/agents/schemas/_search.py) define exact semantics.

## Publication and judgement

The four-dimensional assessment carries referenced support/counterevidence, original change
conditions, targeted replies and separate adjudications. Revised/withdrawn original inference IDs
cannot silently remain affirmative support. Missing operating evidence, valuation anchors and
critical unresolved challenges constrain the stance according to the saved policy.

Fresh sectioned synthesis validates each dimension, adjudication, overall judgement and conditions
independently. Accepted sections are immutable; one targeted repair fills failed sections. Missing
overall or critical adjudication suppresses the rating; other failures can retain a qualified stance
with partial/LOW_CONFIDENCE and visible unfinished synthesis. Zero usable synthesis retains a basic
report/specialist summary, not a fabricated model decision. Cancellation/deadline/persistence failures
remain lifecycle failures.

A frozen candidate, durable lifecycle authorization and committed checkpoint must precede native
public promotion. Publication failure cannot complete the run. Compatibility projections may be
unavailable without destroying their original case. [report_delivery.py](../../tradingagents/research/report_delivery.py),
[synthesis_sections.py](../../tradingagents/research/synthesis_sections.py) and publication own these gates.

## Reader, focus and explanations

`/api/runs/{id}/reader/record` dispatches committed V1/V2 records; it is the native report entry.
Process and fixed-role stage endpoints qualify saved outputs at a captured sequence, without prompts
or raw envelopes. A stage record is unassessed and provisional; it cannot substitute for failed final
qualification. Unsupported versions, missing/corrupt provenance and absent history remain explicit.

Optional focus is a separate baseline-digest-bound artifact, using one dedicated attempt within the
baseline pool and no repair/retry/tools. It cannot alter baseline judgement; local optional failure
preserves the baseline, while cancellation/global corruption still propagates.
Plain-language explanations are independent post-completion artifacts. Fresh-policy jobs freeze
`batched-explanations-v1`, keep all eligible targets, and batch at most 16 targets / 32000 serialized
characters. A single oversized target stays explicitly unavailable. Accepted entries persist after
each response; one missing-only pass per batch retains valid siblings. Each job has a cumulative
24-request / 300-second wall-clock deadline; explicit retries retain both history and deadline.
Dispatched responses lost before persistence remain unknown and their targets are not resent.
The Reader exposes explained/pending/unavailable counts, including accepted progress while running.
Old jobs retain the original 32-target selector, one main plus one repair and 120-second execution.
GET reads only; eligible explicit POST retries preserve attempt history.
Their failure does not change research completion, ratings or original Markdown.
Rule-based check indicators address each observation by check ID and saved array position; repeated
semantic keys cannot overwrite another observation's displayed number. This display repair does not
change saved observations, numeric proofs or explanation-job target manifests.

Reading/projection/export does not fetch new research, generate a missing historical artifact or
call a model. Native research creates no classic `/reader/package`; external classic consumption is
covered in the [compatibility reference](../operations/catalyst-research.md).

## Change propagation

Change canonical models first, then producers, saved identity/replay, publication, backend DTOs,
frontend wire types and consumers. Keep supported historical bytes and version-specific guards.
Run focused contract tests; rebuild tracked SPA assets for frontend changes. Operational instructions
belong in [Web operations](../operations/evidence-research.md), not duplicated field lists here.

<!-- Compatibility anchors for existing section links. -->
<a id="metrics-and-reading"></a>
<a id="native-shared-kernel"></a>
<a id="native-v4-valuation"></a>
<a id="native-v5-bounded-evidence-checks"></a>
<a id="native-v6-supplementary-focus-contract"></a>
<a id="native-v7-investment-assessment-and-dialogue"></a>
<a id="official-document-content-and-coverage-scope"></a>
<a id="programmatic-verification"></a>
<a id="shared-research-record"></a>
