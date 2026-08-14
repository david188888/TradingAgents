# `tradingagents/` Package Guide

This directory owns the Python runtime. Use the root [AGENTS.md](../AGENTS.md)
for repository-wide setup and finish rules.

## Boundaries

- `execution/` is the consumer-neutral execution boundary. `AnalysisRequest`,
  `AnalysisResult`, cancellation, and `AnalysisRunner` serve CLI, Web, and
  programmatic callers without importing consumer-specific UI concerns.
- `graph/` assembles the LangGraph workflow. `setup.py` owns node and edge
  construction; `trading_graph.py` owns configured graph construction and the
  compatibility-facing graph facade.
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
4. Add or adjust focused tests when the relevant local-only test scaffolding
   is available; it is not tracked by the public fork.

`runtime/contracts.py` selects `horizon-policy-v2` for production. The v3
selection is an internal test gate and must not be enabled or documented as
production behavior without an explicit runtime-policy change.

## Validation

Public checks available from a fresh clone are:

```bash
ruff check tradingagents
python scripts/check_agent_docs.py
```

`pytest` suites are optional local scaffolding, not public tracked files. Run
`python -m pytest` or `python -m pytest -m unit` only when that scaffolding is
present. Use narrower local test paths for a localized change, then run the
applicable repository-level checks from the root guide.
