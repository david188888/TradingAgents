# TradingAgents Architecture

This is the current-state architecture map. Canonical machine contracts remain
in the referenced Python and TypeScript models; plans and reviews are not a
source of runtime truth.

## Consumers And Entry Flow

The maintained product entry is the Web workbench. Compatibility consumers share the neutral execution core:

- `cli/main.py` launches Web through `tradingagents web`. CLI analysis is legacy code outside continued product maintenance.
- `tradingagents/web/` is the loopback-only FastAPI workbench. It creates and
  reads runs, streams durable events through SSE, and serves the bundled SPA.
- Programmatic callers use the consumer-neutral execution boundary: classic
  constructs `TradingAgentsGraph`, while explicit native research uses
  `NativeRunner` with its durable observer and publication authorizer.

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
Each analysis binds its effective dataflow configuration to the run's execution
context, so concurrent Web runs route through their own configured providers.
Optional DeepSeek effort overrides are keyed by actual call task in
`llm_clients/task_effort.py`. Native/catalyst executors freeze configuration
before source collection; classic roles with explicit overrides use separate
clients, while news helpers bind immutable invocation settings. Task policies
participate in saved effective configuration and resume identity. Effort overrides
do not add model phases or change default effort; see
[reasoning configuration](docs/operations/llm-reasoning.md).

New Web single and batch requests default to `evidence_v1` and route to
`execution/native_runner.py:NativeRunner`. The React creation form offers company,
catalyst (84 calendar days), and holding scopes with a saved optional supplementary focus.
Roles and challenge count are code-owned. Old-profile creation and retry return
410; legacy read/resume stays available. `TRADINGAGENTS_EVIDENCE_ENABLED=false`
disables fresh native work without disabling reads or existing recovery.

The `evidence-policy-v1` fixes source windows separately from outlook and runtime
horizon policy. New workflow `evidence-production-v6` retains V5 collection through
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
owns the V6 mode objectives, kernel identity and frozen focus-budget policy; old
V1–V5 prompt, role and budget semantics remain versioned.

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

`observability/` records run events and graph-task candidates. `execution/`
promotes committed state, public role outputs, evidence bundles, report
revisions, `research-case-v2`, `thesis-diff-v1`, and the derived
`valuation-assessment-v1` position chain artifact. `runtime/` owns the
durable run store, reconciliation, resume fingerprints, and final report
publication.

The FastAPI adapter exposes raw run/artifact access plus read-only projections:
the Reader (`/api/runs/{id}/reader`), the structured package
(`/api/runs/{id}/reader/package`), run view, audit views, and market views.
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

Native publication requires an assessed `research-record-v1` and its durable
authorization barrier; failure cannot complete the run or fall back to a case.
Markdown and the single native Reader consume that same record. The desktop
V6 Reader starts with the independent scope and judgement, then key claims, primary
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
the supported saved V1–V6 workflows; unknown versions or failed bindings degrade
without exposing unqualified proposals. The process endpoint reads summary
metadata; the selected-role endpoint returns only closed research schema fields,
never prompts, adapter responses or checkpoint envelopes. Both are read-only.
`runtime/native_observation.py` records SDK observation coverage before MAIN
authorization for new SDK-adapter runs. Reader and Audit separately report
budget, SDK main/focus/repair, data-capability and HTTP authorizations; legacy incomplete
coverage is nullable or a lower bound. This marker does not change recovery
identity, prompts, role selection or the research record. The separate
`/reader/focus` projection validates committed supplemental bytes and their
checkpoint barrier at the selected sequence; it never serves a saved candidate.
V6 focus has one dedicated model bucket within the unchanged twelve total
attempts. It has no repair, retry or tool access and uses remaining active time;
optional timeout allows publication of the already-completed baseline.

Completion, readability, completeness and quality remain separate. Missing
valuation or original-thesis inputs constrain their own dimensions, and a
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
