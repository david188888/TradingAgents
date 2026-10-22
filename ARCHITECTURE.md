# TradingAgents Architecture

Status: Current

This is the current-state architecture map. Canonical machine contracts remain
in the referenced Python and TypeScript models; plans and reviews are not a
source of runtime truth.

## Consumers And Entry Flow

The maintained product entry is the Web workbench. Its adapters delegate to the
consumer-neutral execution layer; legacy callers retain compatibility paths:

- `cli/main.py` launches Web through `tradingagents web`. CLI analysis is legacy code outside continued product maintenance.
- `tradingagents/web/` is the loopback-only FastAPI workbench. It creates and
  reads runs, streams durable events through SSE, and serves the bundled SPA.
- Programmatic callers use the consumer-neutral execution boundary: classic
  constructs `TradingAgentsGraph`, while explicit native research uses
  `NativeRunner` with its durable observer and publication authorizer.

Each analysis binds its effective dataflow configuration to the run's execution
context, so concurrent Web runs route through their own configured providers.
Optional DeepSeek effort overrides are keyed by actual call task in
`llm_clients/task_effort.py`. Native/catalyst executors freeze configuration
before source collection; classic roles with explicit overrides use separate
clients, while news helpers bind immutable invocation settings. Task policies
participate in saved effective configuration and resume identity. Effort overrides
do not add model phases or change default effort; see
[reasoning configuration](docs/operations/llm-reasoning.md).

The Web `chatgpt` provider injects a shared official SIWC authentication service
into `NativeRunner`/`NativeModelCaller`. `llm_clients/chatgpt_auth.py` owns OAuth,
protected registrations, refresh rotation and account-specific model catalogs;
`chatgpt_client.py` owns the fixed streamed Responses route. Runs freeze only a
non-secret account reference. Credentials live outside run artifacts; safe
failure diagnostics and measured token usage are checkpointed for projections.
Fresh ChatGPT native identities freeze `siwc-reasoning-v1` for explicit Responses
effort transmission; old unmarked resumes and their explanation retries retain
omission. The authentication service persists earliest-refresh metadata and
per-registration transient backoff under the existing rotation lock; valid-token
fallback never bypasses semantic permission/quota failures or dispatch guards.
See [ChatGPT subscription operations](docs/operations/chatgpt-subscription.md).
The frontend `useChatGPT` hook serializes local status → account catalog reads
after entry, account mutations and login completion, with stale-response guards.
Single/batch creation share `ModelConfiguration`; recovery uses the safe model
diagnostic carried by the optional Web error-envelope field. Stored authorization,
catalog readiness and actual inference permission remain distinct.

## Native Research Architecture

```text
Web form / API -> manager and scheduler -> NativeRunner
  -> qualified, frozen source evidence -> native research kernel
  -> validated research-record-v1 -> local run store -> Reader / Markdown
```

The maintained kernel is `graph/native_research.py`. Operating, event and
market specialists receive separate frozen fact views and cannot read each
other's drafts. Outputs merge in a fixed role order before independent challenge,
bounded verification and synthesis. Independence means task-context isolation,
not statistical independence or a guarantee of correctness.
`NativeRunner` calls this Python kernel directly, with bounded specialist workers
and a durable ledger; the retained classic workflow uses LangGraph.

Models propose evidence-bound hypotheses, counterarguments and dimensional
judgements. The code host owns source qualification, input/reference validation,
deterministic calculations, execution limits and durable publication. Missing
inputs remain explicit; a successful computable check cannot establish economic
causality. The canonical boundaries are in `agents/schemas/` and `research/`;
see the [contract index](docs/contracts/README.md) for producers and consumers.

Fresh scoped synthesis requests validate section references before compiling
numeric prose and require complete challenge/adjudication arrays in the prompt
schema. Saved prompts retain their version; bounded repair receives all detected
reference-section failures without weakening publication validation.

`scripts/eval_benchmark.py` measures committed saved runs without constructing a
runtime or making network/model calls. It separates synthesis delivery, formed
stances and missing token measurements; it does not replace Reader eligibility
validation. See the [benchmark measurement contract](docs/contracts/evidence-benchmark.md).

`scripts/profile_native_inputs.py` reconstructs V7 stage inputs in memory and
checks saved context/prompt hashes before measuring serialized sizes. Its
`native_input_inventory.py` helper records a conservative content/scope floor,
separate from token usage and semantic quality. These standalone diagnostics do
not select evidence or alter production budgets. `scripts/compare_native_prompt_views.py`
uses the offline-only `execution/native_prompt_view.py` codec to compare a reversible
metadata representation, adopting only positive full-prompt byte savings in its
hypothetical result. Production prompts and identities remain unchanged. See
[input measurement](docs/contracts/native-input-measurement.md).

Fresh V7 runs freeze an anchored numeric narrative policy. `numeric_catalog.py`
qualifies saved numeric inputs, `numeric_narrative.py` compiles model references
before entity IDs, and `numeric_integration.py` binds receipts to cached and public
records. Reader/exports validate those receipts without new model calls. Historical
identities retain their original behavior; numeric fragments do not certify the
surrounding economic explanation. See [numeric narrative](docs/contracts/numeric-narrative.md).
Fresh V7 also freezes `factual-premises-v1`: `research/factual_premises.py` builds
source observations and bounded directions from the existing catalog, scopes
per-field bindings and stores them in numeric receipts. Reader, stage output,
Markdown and explanation targets preserve these boundaries. This proves binding
and arithmetic, not whole-sentence entailment. See [factual premises](docs/contracts/factual-premises.md).

New Web single and batch requests default to `evidence_v1` and route to
`execution/native_runner.py:NativeRunner`. The React creation form offers one company investment research workflow, with an optional supplementary focus. Historical catalyst/holding modes remain read/resume only; fresh creation/retry of those modes returns 422.
Roles and challenge count are code-owned. Old-profile creation and retry return
410; legacy read/resume stays available. `TRADINGAGENTS_EVIDENCE_ENABLED=false`
disables fresh native work without disabling reads or existing recovery.

The `evidence-policy-v1` fixes source windows separately from outlook and runtime
horizon policy. New workflow `evidence-production-v7` retains V5 collection through
`dataflows/minimum_sources.py:MinimumEvidenceSources`, an isolated extension of
the native collector. `disclosure_documents_v2.py` admits bounded official
reports/summary/operating notices and explicit numeric rows; supplementary
valuation parses dated institution EPS and same-session industry candidates.
`research/minimum_evidence.py` recomputes three closed checks from frozen V0.
The critic selects optional check/risk/date bindings; the host owns assessment
v2 outcomes and keeps economic parent questions unresolved. Saved record
validation recomputes checks and challenge outcomes, so Reader/exports cannot
relabel a successful data check as resolved economics. V5 introduced these
checks without an extra model stage. V6 freezes the independent baseline first,
then optionally answers the user focus once through `execution/native_focus.py`.
The collector and core kernel never receive that focus. `research/native_versions.py`
owns V6 frozen mode objectives and V7 investment objective/kernel/budget identity. V7 adds one bounded targeted reply per challenged specialist before synthesis, a versioned dialogue and V3 investment assessment. Fresh V7 identities freeze a company policy for timestamped current-session valuation, cautious judgement with missing valuation anchors, and role-local enumerated model references. Older identities retain their admission, prompts and judgement gates. Old V1–V6 prompts, roles, budgets and report semantics remain versioned. See the [unified research contract](docs/contracts/unified-company-research.md).

Fresh V7 also selects `hypothesis-directed-checks-v1`: `_native_stage.py` owns
challenge V3 admission; `_challenge_verification.py` owns classification and task
outcomes; `research/challenge_checks.py` validates qualified V0 inputs and compiles
`verification-plan-v2`. Independent propositions preserve the original hypothesis
conditions. Their saved outcomes and numeric/F02 receipts flow through replies,
synthesis, Reader and Markdown. History without the policy retains V1 tasks.
See the [challenge-check contract](docs/contracts/hypothesis-directed-checks.md).

Workflow `evidence-production-v4` uses `dataflows/native_valuation.py:ValuationSources`,
which extends the v3 bounded disclosures collector with qualified valuation
sources before optional documents. `research/native_valuation.py` admits source
fields and assembles deterministic inputs for the existing pure valuation chain.
The optional record valuation includes saved inputs, input hash, evidence IDs,
recomputed assessment and limitations. Company/holding valuation claims are
restricted to valuation facts; synthesis receives allowed claim IDs per dimension.
V4 validates dimension references during the existing bounded model repair
opportunity. Failed synthesis remains explicitly partial, without relaxed gates.

V4 and its original valuation chain remain recoverable. V3 uses `native_disclosures.py`; V2 uses `native_sources.py`; V1 uses
`catalyst_sources.py`. Recovery retains each collector and its original
facts/views/policy/kernel/prompt semantics, or replays saved V0/output. Source
families, publication times, global coverage and specialist scope remain distinct.
See [native source policy](docs/operations/evidence-research.md#evidence-and-workflow).

## Legacy Workflow And Research Routing

The legacy neutral classic flow is:

```text
AnalysisRequest -> TradingAgentsGraph -> AnalysisRunner -> LangGraph workflow
```

`AnalysisRequest` and `AnalysisResult` in
`tradingagents/execution/models.py` define the shared input/output boundary.
`TradingAgentsGraph` validates effective configuration, builds tools and a
workflow, and delegates run execution to `AnalysisRunner`. The runner resolves
run context, creates state, invokes or streams LangGraph, handles cancellation
and checkpoint coordination, then returns a result.

`tradingagents/graph/setup.py` builds a deterministic prefix before analysis:
adjusted-price, news-window, and fundamentals prefetch tasks always run; the
A-share supplement task runs when a selected analyst needs it. Selected market,
social, news, and fundamentals analysts then execute in their requested order.
The Evidence Steward gates the Bull/Bear research debate; a gate error ends the
workflow instead of manufacturing a decision.

Bull and Bear debate through the Research Manager. The classic profile accepts
the typed modes `company_research` and `holding_review`; both route
from Research Manager directly to Portfolio Manager, and the runner reports the
`research_only` signal. The former Trader and three-role risk debate have been
retired from the execution graph; older state and report fields may remain for
compatibility. This routing is defined in `graph/setup.py`; do not infer it from
an older report layout or UI projection.

Research runs use a deterministic evidence registry and data-window plan to
assemble `ResearchCaseV2` from a validated draft when possible. The same typed
run also promotes a `research-package-v1` artifact after the research case
commit. The package is a public, provider-neutral fact layer containing the
code-owned metric dictionary, current-run evidence labels, and explicit
unknowns; structured observations, peer comparisons, and logic edges are added
only when their inputs pass point-in-time and evidence validation. Failures
retain an explicit partial or fail-stop artifact rather than pretending complete
coverage. The thesis-diff code compares committed research cases; derived
artifacts are promoted only after durable graph commit barriers.

## Publication And Projections

### Legacy Catalyst Publication

The following describes retained `catalyst_v1` execution and recovery. Current
native publication is described below.

Catalyst freezes one cutoff-qualified evidence draft, then executes three
specialists, independent refutation and one synthesis. Model proposals pass
the canonical `CatalystResearchCase` validation and deterministic priority
ceiling. Its model adapter reuses configured quick/deep clients, disables SDK
retries and charges every dispatch. Process-wide model and data concurrency
ceilings are two each. Active execution defaults to 300 seconds, excluding
scheduler queue time.

The bounded price path admits directly observed Tushare REST attempts. It
validates daily bars, dated factors and complete settled-session calendars,
anchors OHLC to the last price session, and rejects unverified retrospective
factor vintage. Code-computed risk and ATR statistics are included in the
frozen price evidence payload, with independent sample/input degradation;
saved results are projected into the additive `research-record-v1` contract
and the Reader's quantitative context, independently of valuation.

`runtime/catalyst_checkpoint.py` persists attempt transitions, source results,
frozen inputs, prompt digests, role results, stage status and the final candidate
as committed run artifacts. Recovery checks identity and integrity, reuses saved
results and counts uncertain dispatched attempts as spent. The catalyst frontier
is always durable; `checkpoint_enabled` controls classic LangGraph checkpoints.
The catalyst evidence policy does not extend the horizon runtime-policy enum.

The manager arbitrates cancellation and durable publication authorization
under the same lifecycle lock. Cancellation first forbids publication;
authorization first starts terminalization and rejects late cancellation.
A crash after authorization resumes from the saved candidate. The committed
`catalyst-research-case-v1` artifact has a durable parent; its Markdown report is
derived from that same case. No classic debate-summary call is scheduled.

`/api/runs/{id}/catalyst` projects the committed case and durable stage facts.
Reading, refreshing and reconnecting do not invoke models or providers.
`ready`, run completion, evidence completeness and quality are separate axes.
The SPA retains these historical case readers. New creation uses the native form. See
[catalyst operations](docs/operations/catalyst-research.md) for qualification limits.

### Shared Projections And Native Publication

`observability/` records run events and graph-task candidates. `execution/`
promotes committed state, public role outputs, evidence bundles, report
revisions, `research-case-v2`, `thesis-diff-v1`, and the derived
`valuation-assessment-v1` position chain artifact. `runtime/` owns the
durable run store, reconciliation, resume fingerprints, and final report
publication.

The FastAPI adapter exposes raw run/artifact access plus read-only projections:
the Reader (`/api/runs/{id}/reader`), the structured package
(`/api/runs/{id}/reader/package`), run view, and audit views.
The shared record (`/api/runs/{id}/reader/record`) adapts committed company,
holding and catalyst cases into source content, claims, hypotheses, challenges,
verification records and metrics. It checks artifact and source-case integrity;
historical absence remains explicit, without backfill. Current adapters label
inferences as converted and never treat model dispositions as executed tool
verification. `execution/verification_executor.py` provides a
bounded round for native V0 records in all three modes. It uses
the existing durable ledger, saves predicate-scoped results and V1 lineage,
and replays saved output without work. The native kernel in
`graph/native_research.py` connects facts-only V0, isolated specialists,
one challenge, C1 and dimension-gated synthesis. Its SDK adapter and mandatory
record publisher live in `execution/native_model.py` and
`execution/native_publication.py`. `NativeRunner` supplies the bounded collector,
saved V0, role lifecycle events, deadline and shared cancellation/publication
authorization. The Web manager creates, retries and resumes native runs with
profile-specific identity guards; native checkpoints do not depend on the
classic checkpoint toggle. Unknown dispatched calls remain spent and are not
automatically repeated. Persisted adapter responses can recover the gap before
the kernel's MAIN result without another model call.

For V7, the adapter checks condition evidence against its own hypothesis before
saving specialist proposals; the kernel repeats that shared rule at merge.
`execution/native_references.py` gives fresh synthesis requests deterministic
prompt-local aliases, restored to canonical IDs before unchanged record gates
and caching. Frozen prompts retain their original format. Binding guidance and
safe repair feedback remain within the existing repair budget; see the
[unified research contract](docs/contracts/unified-company-research.md).

Fresh V7 identities also freeze the specialist reference-isolation policy.
After one bounded repair fails or is refused, the adapter can preserve only
the original schema-valid hypotheses whose references pass the shared rule.
Durable candidate/acceptance envelopes retain original indices and closed
rejection reasons; the kernel and Reader use the same binding. Effective
rejections produce partial/LOW_CONFIDENCE output. Cancellation, deadlines and
checkpoint conflicts do not trigger this fallback. Legacy identities keep
their adapter behavior and saved prompts.

Fresh V7 identities freeze `execution/native_retry.py`'s model retry policy.
The adapter permits three transient retries per call with 2/5/10-second waits,
bounded by the existing shared three-retry/twelve-attempt ledger limits. Repair
retries retain their origin and each SDK request owns its usage exactly once;
Reader counts include retry authorizations. Historical identities without this
policy retain their original behavior, and the optional focus remains one call.
See [retry accounting](docs/operations/observability-replay.md#原生模型有限网络重试).

Native publication requires an assessed `research-record-v1` and its durable
authorization barrier; failure cannot complete the run or fall back to a case.
Fresh V7 identities freeze a separate report-delivery policy. The optional
`company_basics` pack binds public profile, fundamental and quantitative fields
to saved facts. `research/report_delivery.py` restores host-owned copied
synthesis bindings and assembles effective saved findings after unusable
synthesis. V3 `report_status` separates delivery from coverage; an unfinished
synthesis with no accepted sections has a null stance and preserves provenance.
Fresh numeric synthesis freezes reference-schema 3 and uses
`research/synthesis_sections.py`: four dimensions, each challenge adjudication,
overall judgement and conditions are validated independently with durable numeric
receipts. One targeted repair fills only failed sections. Missing overall or
critical adjudication blocks the rating; other pending sections retain a valid
stance and show partial/LOW_CONFIDENCE with explicit unfinished status. Host
placeholders, publication, recovery and Reader share deterministic proof replay.
Fresh V7 identities also freeze `structured-financial-checks-v1` and
`financial-detail-fields-v1`. The latter saves one `*.financial_detail` record
per statement table with 11 detail fields; the six-field financial-statements
records, frozen checks, supplier cross-checks and valuation are unchanged.
`research/structured_financial_checks.py` adds two finite comparisons to a
calculation-v3 five-check pack, independently of PDF coverage. The original full
cash-bridge question remains separate. Saved v1/v2 pack replay and legacy prompt
choices retain their existing behavior. See the [check contract](docs/contracts/structured-financial-checks.md).
Historical serialization and identities remain unchanged. See the
[unified contract](docs/contracts/unified-company-research.md).
Markdown and the single native Reader consume that same record. The desktop
V7 Reader starts with the independent scope, investment stance, referenced support/counterevidence and original falsifiers, then key claims, primary
challenge and proposed next check, executed checks, valuation and quantitative
context. Linked facts, source content and fixed concept explanations appear in
a side panel or narrow-container drawer. Evidence, process, Agent outputs and
the complete record are explicit navigation destinations. The optional response
appears last; historical reports keep their original question-led presentation.
`research-focus-response-v1` is a separate closed artifact bound to the frozen
baseline digest. `execution/native_focus_publication.py` commits it only after
the mandatory record, using the same lifecycle authorization. Durable publication
dispositions make local optional failure stable across report generation and
recovery. Cancellation or global persistence corruption still fails the run.

`web/reader_process_models.py` owns the additive process and per-role DTOs.
`web/reader_process_projection.py` captures an event-sequence boundary, validates
the native workflow/input/output/seed identities and maps proposals to their
published IDs. `web/native_reader_versions.py` freezes read qualification for
the supported saved V1–V7 workflows; unknown versions or failed bindings degrade
without exposing unqualified proposals. The process endpoint reads summary
metadata; the selected-role endpoint returns only closed research schema fields,
never prompts, adapter responses or checkpoint envelopes. Both are read-only.
V7 stages also qualify independently before final publication through
`web/reader_stage_projection.py`. Selected-role DTOs can carry an unassessed
public stage record and provisional proposal; process summaries expose only
counts/status. Frozen evidence, role scopes, numeric receipts and saved
verification bindings are checked without executing research. Existing final
publication checks remain mandatory; stage material is never a final report.
`runtime/native_observation.py` records SDK observation coverage before MAIN
authorization for new SDK-adapter runs. Public process DTOs retain separate
budget, SDK main/focus/repair, data-capability and HTTP authorizations; the UI
shows these only in Audit technical troubleshooting. Audit defaults to public
research availability, failed-role explanations and limitations; main stage
reviews omit execution counts. Legacy incomplete
coverage is nullable or a lower bound. This marker does not change recovery
identity, prompts, role selection or the research record. The separate
`/reader/focus` projection validates committed supplemental bytes and their
checkpoint barrier at the selected sequence; it never serves a saved candidate.
V6 and V7 focus have one dedicated model bucket within the unchanged twelve total
attempts. It has no repair, retry or tool access and uses remaining active time;
optional timeout allows publication of the already-completed baseline.

Completion, readability, completeness and quality remain separate. Missing
valuation constrains investment stance; historical original-thesis inputs constrain holding review, and a
successful condition check cannot close an economic challenge. Web creation
already defaults to native research; paid accuracy evaluation remains a separate
acceptance task. See [Web research operations](docs/operations/evidence-research.md) and
[the contract](docs/contracts/research-record.md).
`frontend/src/api/contracts.ts` is the TypeScript facade for those wire
contracts. The client consumes server-projected data; it does not define the
domain schema or recover unavailable evidence by making provider calls.

## Persistence

Default local data is under `~/.tradingagents/`:

| Purpose | Default location |
| --- | --- |
| Reports and non-web logs | `~/.tradingagents/logs/` |
| Data cache and LangGraph checkpoints | `~/.tradingagents/cache/` |
| Legacy decision memory (read-only; the write side was retired, only parsing and prompt injection remain) | `~/.tradingagents/memory/trading_memory.md` |
| Durable Web run records | `~/.tradingagents/web/runs/` |
| Web server log | `~/.tradingagents/web/logs/server.log` |

The run store writes snapshots, append-only events, artifacts, report
revisions, and final reports per run. These are local user records, not source
fixtures or disposable development output.

## Module Ownership And Extension Points

| Need | Primary owner | Extension rule |
| --- | --- | --- |
| Input/result or cancellation behavior | `execution/` | Evolve typed models before adapters. |
| Role sequence, routing, tools | `graph/` and `agents/` | Preserve policy-owned prefetch and evidence gates. |
| Provider capability or market data | `dataflows/` | Add a provider behind typed, source-labelled results. |
| Evidence-bound research artifact | `agents/schemas/` and `research/` | Bind claims to evidence; retain explicit degradation. |
| Durable runs, checkpoints, replay | `runtime/` and `observability/` | Keep events/artifacts durable and compatibility-aware. |
| HTTP, SSE, Reader/Audit UI | `web/` and `frontend/` | Adapt canonical contracts; do not reverse the dependency. |

New adapters may call execution/runtime boundaries. Execution may coordinate
graph, dataflows, research, runtime, and observability. Core domain modules
must not import FastAPI, SSE, React, or browser contract types. Provider code
belongs in `dataflows/`, not graph routing or UI projection modules.

## Runtime Policy

The current production runtime contract is `horizon-policy-v2`, selected by
`PRODUCTION_RUNTIME_CONTRACT` in `tradingagents/runtime/contracts.py`.
`horizon-policy-v3` is currently an internal test-gated selection requiring
injected preflight inputs; it is not production runtime policy.

## Plain-language reading supplement

The native Web Reader shares deterministic indicator definitions and numeric
presentation across report and related evidence. New-study creation metadata
opts into an independent, bounded post-completion model explanation job using
the frozen quick-model configuration and maintained API/subscription transport.
Its own manifest and artifact bind to the published baseline/focus and never
change research checkpoints, ratings, stage counts or original Markdown.
Historical reports receive supported definitions and formatting only. GETs are
read-only; eligible new-study retries require an explicit POST. See the
[explanation contract](docs/contracts/report-explanation.md) for ownership, limits and failure semantics.
