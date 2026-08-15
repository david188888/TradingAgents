# TradingAgents Architecture

This is the current-state architecture map. Canonical machine contracts remain
in the referenced Python and TypeScript models; plans and reviews are not a
source of runtime truth.

## Consumers And Entry Flow

Three consumer shapes share the same execution core:

- `cli/main.py` is the Typer CLI adapter.
- `tradingagents/web/` is the loopback-only FastAPI workbench. It creates and
  reads runs, streams durable events through SSE, and serves the bundled SPA.
- Programmatic callers construct `TradingAgentsGraph` and use its
  consumer-neutral execution path.

The common flow is:

```text
AnalysisRequest -> TradingAgentsGraph -> AnalysisRunner -> LangGraph workflow
```

`AnalysisRequest` and `AnalysisResult` in
`tradingagents/execution/models.py` define the shared input/output boundary.
`TradingAgentsGraph` validates effective configuration, builds tools and a
workflow, and delegates run execution to `AnalysisRunner`. The runner resolves
run context, creates state, invokes or streams LangGraph, handles cancellation
and checkpoint coordination, then returns a result.

## Workflow And Research Routing

`tradingagents/graph/setup.py` builds a deterministic prefix before analysis:
adjusted-price, news-window, and fundamentals prefetch tasks always run; the
A-share supplement task runs when a selected analyst needs it. Selected market,
social, news, and fundamentals analysts then execute in their requested order.
The Evidence Steward gates the Bull/Bear research debate; a gate error ends the
workflow instead of manufacturing a decision.

Bull and Bear debate through the Research Manager. `AnalysisRequest` accepts
only the typed public modes `company_research` and `holding_review`; both route
from Research Manager directly to Portfolio Manager, and the runner reports the
`research_only` signal. Trader and the three-role risk debate remain wired in
the graph as a compatibility/internal legacy branch, but no current typed
public request selects that branch. This routing is defined in `graph/setup.py`;
do not infer it from an older report layout or UI projection.

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

`observability/` records run events and graph-task candidates. `execution/`
promotes committed state, public role outputs, evidence bundles, report
revisions, `research-case-v2`, and `thesis-diff-v1`. `runtime/` owns the
durable run store, reconciliation, resume fingerprints, and final report
publication.

The FastAPI adapter exposes raw run/artifact access plus read-only projections:
the Reader (`/api/runs/{id}/reader`), the structured package
(`/api/runs/{id}/reader/package`), run view, audit views, and market views.
`frontend/src/api/contracts.ts` is the TypeScript facade for those wire
contracts. The client consumes server-projected data; it does not define the
domain schema or recover unavailable evidence by making provider calls.

## Persistence

Default local data is under `~/.tradingagents/`:

| Purpose | Default location |
| --- | --- |
| Reports and non-web logs | `~/.tradingagents/logs/` |
| Data cache and LangGraph checkpoints | `~/.tradingagents/cache/` |
| Decision memory | `~/.tradingagents/memory/trading_memory.md` |
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
