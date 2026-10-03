# TradingAgents Architecture

This is the current-state architecture map. Canonical machine contracts remain
in the referenced Python and TypeScript models; plans and reviews are not a
source of runtime truth.

## Consumers And Entry Flow

Three consumer shapes share the same execution core:

- `cli/main.py` is the Typer CLI adapter.
- `tradingagents/web/` is the loopback-only FastAPI workbench. It creates and
  reads runs, streams durable events through SSE, and serves the bundled SPA.
- Programmatic callers use the consumer-neutral execution boundary: classic
  constructs `TradingAgentsGraph`, while explicit native research uses
  `NativeRunner` with its durable observer and publication authorizer.

The default classic flow is:

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

The Web manager routes explicit `catalyst_v1` requests to
`execution/catalyst_runner.py:CatalystRunner`. This neutral executor coordinates
`dataflows/catalyst_sources.py`, the retry-free budgeted HTTP transport, and
`graph/catalyst_workflow.py`. The classic graph facade rejects catalyst requests
instead of silently running classic. The explicit Web entry is gated by
`catalyst_profile_enabled`; classic remains the default.

Explicit `evidence_v1` requests route to `execution/native_runner.py:NativeRunner`
for A-share company, catalyst and holding research. The creation-only Web flag
`TRADINGAGENTS_EVIDENCE_ENABLED=true` is independent of the catalyst flag;
omitted profiles and existing forms retain classic defaults. The native trial
is exposed through the Web API and neutral runner, without a new workbench
selector or CLI profile option. Its `evidence-policy-v1` fixes historical source
windows and is distinct from both catalyst lookahead and runtime horizon policy.

## Workflow And Research Routing

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
The SPA exposes an explicit catalyst form with the fixed 84-day outlook;
classic selection and historical reading remain available. See
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
Markdown and the single native Reader consume that same record. The native
first screen prioritizes judgement, key claims, primary challenge, next check
and quantitative context; source content and per-dimension limits are expandable.
Completion, readability, completeness and quality remain separate. Missing
valuation or original-thesis inputs constrain their own dimensions, and a
successful condition check cannot close an economic challenge. Default migration
and paid accuracy evaluation remain separate from this engineering path. See
[native trial operations](docs/operations/evidence-research.md) and
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
