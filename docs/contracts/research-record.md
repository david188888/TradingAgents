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

Fresh Web company research is `evidence-production-v8` / `native-research-kernel-v7` /
`research-record-v2`. Historical V1–V7 workflows retain V1 records and their saved identities, prompts,
budgets and qualification rules. Never infer a workflow version from a model label or optional field.
Classic/catalyst case adapters are compatibility producers, not the current new-study path.

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

Malformed shared JSON/schema cannot be salvaged as free text. Within existing repair budgets,
independently valid original specialist siblings can survive reference rejection with original
indices and closed reasons; effective rejection forces partial/LOW_CONFIDENCE. Valid repairs replace
whole proposals rather than combining incompatible main/repair responses.

## Challenge and verification

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
| Baseline model attempts | 12 total: at most 8 main and 1 focus; repairs/retries consume that same total |
| Baseline repair/retry sub-pools | 2 structured repairs (1 per stage); 3 shared transient retries |
| Dedicated data | 24 capability calls / 64 HTTP attempts |
| All data HTTP | 172 attempts |
| Search activity | 90 seconds, union of overlapping intervals, excluding model thinking |
| Whole research | 300 active seconds by default, excluding queue time; effective timeout is frozen in run identity |

Reservations persist before dispatch. Recovery carries spent/unknown attempts forward. Search retries
at most once; access/payment/security rejection does not gain retries or new quota by rotating keys.
No new qualified material, exhausted pools/deadline or unavailable sources produce explicit gaps and
stop reasons; cancellation propagates. A judgement is updated only after its affected review executes.
Baseline plus review is at most 21 model attempts. Review retries/repairs use the review pool and
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
Plain-language explanations are independent post-completion artifacts with at most one main plus
one repair over 120 seconds. GET reads only; eligible explicit POST retries preserve attempt history.
Their failure does not change research completion, ratings or original Markdown.

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
