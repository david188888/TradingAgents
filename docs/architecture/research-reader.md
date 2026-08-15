# Research Reader Architecture

- **Status: Current**（current-state 文档；graph/契约变化时对照 `tradingagents/graph/setup.py`、`tradingagents/execution/` 与 `tradingagents/web/` 校验）

This page describes the current learning-research Reader path. The public surface is read-only and research-only; it does not create orders, portfolio actions, or investment advice.

## Entry And Modes

CLI, FastAPI/SSE workbench, and programmatic callers share [`AnalysisRequest`](../../tradingagents/execution/models.py). The request validates `company_research` and `holding_review`, each with `short`, `medium`, or `long` horizon. Holding facts are normalized into `HoldingContext`; a company research request cannot carry holding context.

The graph is assembled by [`graph/setup.py`](../../tradingagents/graph/setup.py) and executed through [`TradingAgentsGraph`](../../tradingagents/graph/trading_graph.py) and [`AnalysisRunner`](../../tradingagents/execution/runner.py). The workbench observes the same run through FastAPI/SSE adapters and persists events and artifacts in the local [`RunStore`](../../tradingagents/runtime/store.py), normally under `~/.tradingagents/web/runs/`.

## Deterministic Research Path

Before role output is published, the graph resolves run-scoped identity and analysis cutoff, then follows the configured data-window policy. The current graph wires the following prefetch sequence (the A-share supplement is conditional):

1. A-share supplement
2. adjusted price window
3. news window
4. fundamentals
5. analyst roles, Evidence Steward gate, debate, and Research Manager

Relevant implementations are [`analysis_cutoff.py`](../../tradingagents/research/analysis_cutoff.py), [`horizon_policy.py`](../../tradingagents/research/horizon_policy.py), [`price_prefetch.py`](../../tradingagents/research/price_prefetch.py), [`news_prefetch.py`](../../tradingagents/research/news_prefetch.py), [`fundamentals_prefetch.py`](../../tradingagents/research/fundamentals_prefetch.py), and [`graph/setup.py`](../../tradingagents/graph/setup.py). Analysts consume the run's prepared evidence context. The Evidence Steward produces the gate verdict used by research assembly and eligibility; model prose alone cannot upgrade eligibility.

## Publication

The Research Manager emits a candidate draft. [`research/case_assembly.py`](../../tradingagents/research/case_assembly.py) resolves evidence and coverage keys, drops claims that cannot be safely resolved, computes eligibility/data quality, and returns a schema-valid `ResearchCaseV2` or an honest partial/fail-stop case.

The execution commit path publishes `research-case-v2` with current-run provenance and a committed sequence. See [`execution/runner.py`](../../tradingagents/execution/runner.py) and [`execution/output_publisher.py`](../../tradingagents/execution/output_publisher.py). After `run.completed`, [`web/manager.py`](../../tradingagents/web/manager.py) may publish `thesis-diff-v1` as a best-effort derived artifact. [`research/thesis_diff.py`](../../tradingagents/research/thesis_diff.py) compares the same ticker and horizon structurally; a failed diff does not change the completed run or Research Case.

## Reader Projection And Degradation

`GET /api/runs/{run_id}/reader` is implemented by [`web/reader_projection.py`](../../tradingagents/web/reader_projection.py) and validated by [`web/reader_models.py`](../../tradingagents/web/reader_models.py):

- `typed`: a readable `ResearchCaseV2` projection with research tilt, claims, scenarios, review items, analyst cards, coverage, omissions, optional thesis diff, and bounded audit counts.
- `legacy`: a historical run without a typed case; it remains explicitly legacy and does not fabricate typed fields.
- `unavailable`: a typed case is missing, unreadable, or unsupported; the response carries a stable reason code and audit counts.

The projection reads persisted artifacts and events only. It is side-effect free, does not call an LLM or network, and does not expose raw evidence payloads, prompt text, locators, content hashes, or internal snapshots.

## Companion And Audit Boundaries

Companion is an on-demand, bounded explanation of one public `role`, `claim`, `evidence`, or `risk` selection: [`reader_projection.py`](../../tradingagents/web/reader_projection.py) and `/api/runs/{run_id}/reader/companion`.

Audit Center is a separate terminal-run projection. Its summary and detail routes are backed by [`audit_models.py`](../../tradingagents/web/audit_models.py), [`audit_projection.py`](../../tradingagents/web/audit_projection.py), and `/api/runs/{run_id}/audit*`. It exposes safe counts, stage/role/capability/tool/artifact metadata, and bounded detail availability. Running analyses use the real-time inspector; Audit Center rejects non-terminal runs and never becomes a raw trace dump.

The frontend wire facade for all four routes is [`frontend/src/api/contracts.ts`](../../frontend/src/api/contracts.ts), with request functions in [`frontend/src/api/client.ts`](../../frontend/src/api/client.ts).
