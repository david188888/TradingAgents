# `tradingagents/` Package Guide

This directory owns the Python runtime. Use the root [AGENTS.md](../AGENTS.md)
for repository-wide setup and finish rules.

## Boundaries

- `execution/` is the consumer-neutral execution boundary. `AnalysisRequest`,
  `AnalysisResult` and cancellation are shared contracts. `NativeRunner` owns
  maintained Web research; `AnalysisRunner` retains classic execution for
  compatibility callers. Neither should import consumer-specific UI concerns.
- `graph/insight_research.py` owns new V9 Insight research, with isolated
  specialists, bounded supplementary search, one review/reply round and synthesis.
  `graph/native_research.py` retains the kernels for older frozen research tasks.
  `setup.py` assembles the retained classic LangGraph nodes/edges;
  `trading_graph.py` owns its compatibility-facing facade.
- `dataflows/` owns provider interfaces, vendor selection, normalization, and
  capability results. Provider failures must remain typed and source-labelled.
- `agents/schemas/` and `research/` own public research artifacts, evidence
  binding, case assembly, and thesis comparison. Start public artifact changes
  from these canonical models rather than rendered Markdown or a web DTO.
- `runtime/` and `observability/` own durable run contracts, persistence,
  checkpoint reconciliation, event semantics, and report publication.
- `web/` is a local FastAPI/SSE adapter and projection layer, not the source of
  neutral execution or domain contracts.

## Dependency Direction

For new code, keep dependencies pointed inward: adapters (`cli/`, `web/`) call
execution and runtime; execution coordinates graph, research, dataflows, and
runtime; graph invokes agents and dataflows; projections read durable artifacts.
Avoid importing Web/HTTP types into `execution/`, `graph/`, `research/`, or
`dataflows/`. Keep provider-specific code behind `dataflows/` interfaces and
avoid a UI projection becoming a domain-schema dependency.

## Contract Changes

Public contracts include `execution/models.py`, exported
`agents/schemas/` models, `runtime/` contracts and persisted event/store models,
and Web/API models where they are exposed. A contract change requires:

1. Update the canonical model and its validation first.
2. Update every producer, adapter, persistence path, projection, and client
   facade that consumes it.
3. Preserve explicit compatibility/degradation behavior for older persisted
   runs where the reader or audit endpoint supports it.
4. Add or adjust focused tests when the relevant tracked test scaffolding
   is available.

`runtime/contracts.py` selects `horizon-policy-v2` for production. The v3
selection is an internal test gate and must not be enabled or documented as
production behavior without an explicit runtime-policy change.

## Validation

Follow the [scoped validation matrix](../CONTRIBUTING.md#scoped-validation).
For localized behavior changes, lint changed Python files (including tests)
with Ruff and run relevant pytest files or test cases. Expand to affected
consumers for shared contracts, persistence, recovery or pipeline changes.
Use broader offline regression for version releases or broad shared changes;
do not run full pytest after every local optimization or repeat covered subsets.

Documentation-only changes need documentation and diff checks. Add or adjust
tests for meaningful behavior or regression gaps, not every small edit. Reuse
passing checks while their relevant inputs remain unchanged, including when
publishing to GitHub; preserve the Ruff pre-commit gate.
