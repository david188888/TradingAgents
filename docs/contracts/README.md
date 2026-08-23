# Contract Index

- **Status: Current**（契约地图；机器属实的 schema 始终以代码为准）

This page is a map, not a second schema. Python and TypeScript definitions remain the machine-owned truth; do not copy complete field lists into Markdown.

## Canonical Sources

| Surface | Canonical source | Consumers and adapters |
| --- | --- | --- |
| Shared execution input/output | [`tradingagents/execution/models.py`](../../tradingagents/execution/models.py) | [`execution/runner.py`](../../tradingagents/execution/runner.py), graph callers, web request normalization |
| Agent-produced public research artifacts | [`tradingagents/agents/schemas/`](../../tradingagents/agents/schemas/) | Research Manager, [`research/case_assembly.py`](../../tradingagents/research/case_assembly.py), eligibility |
| Research evidence and cross-run artifacts | [`research/case_assembly.py`](../../tradingagents/research/case_assembly.py), [`research/thesis_diff.py`](../../tradingagents/research/thesis_diff.py), [`research/research_package.py`](../../tradingagents/research/research_package.py) | Execution publisher, web Reader/package projection |
| Research package and public hashing | [`research/research_package.py`](../../tradingagents/research/research_package.py), [`research/public_hash.py`](../../tradingagents/research/public_hash.py) | External Agent skill consumers, web Reader/package projection |
| Runtime compatibility and replay contracts | [`tradingagents/runtime/`](../../tradingagents/runtime/) | Runner, observer, checkpoint and resume paths |
| Web request and response models | [`tradingagents/web/schemas.py`](../../tradingagents/web/schemas.py), [`reader_models.py`](../../tradingagents/web/reader_models.py), [`audit_models.py`](../../tradingagents/web/audit_models.py), [`batch_models.py`](../../tradingagents/web/batch_models.py) | FastAPI routes (including `/api/batches`), projections, API clients |
| Reader and Companion projection | [`tradingagents/web/reader_models.py`](../../tradingagents/web/reader_models.py), [`reader_projection.py`](../../tradingagents/web/reader_projection.py) | `/api/runs/{run_id}/reader` and `/reader/companion` |
| Audit Center projection | [`tradingagents/web/audit_models.py`](../../tradingagents/web/audit_models.py), [`audit_projection.py`](../../tradingagents/web/audit_projection.py) | `/api/runs/{run_id}/audit` and `/audit/detail` |
| Browser wire facade | [`frontend/src/api/contracts.ts`](../../frontend/src/api/contracts.ts) | React API client and state consumers |

The frontend facade mirrors the backend wire shape and documents intentional opaque fields. It does not replace the Python models or authorize backend changes.

## Compatibility Rules

- Treat `AnalysisRequest` and web request normalization as the boundary between callers and shared execution. Preserve explicit `company_research` versus `holding_review` validation and legacy portfolio mapping rules.
- Treat `ResearchCaseV2` and `ThesisDiffV1` as versioned public artifacts. Assembly must bind claims to current-run evidence and coverage; readers must not infer a new contract from Markdown reports.
- Keep Reader responses discriminated by `kind`: `typed`, `legacy`, or `unavailable`. Legacy runs remain readable without being upgraded by inference.
- Keep Companion and Audit Center bounded projections. They may expose safe summaries and metadata, but not prompts, raw provider payloads, locators, secrets, or internal debugging state.
- Runtime policy and resume/fingerprint semantics are selected as a coherent versioned family. Production currently selects `horizon-policy-v2`; test-gated variants must not be described as production behavior.

## Change Propagation

1. Change the canonical model or runtime contract and its focused unit tests.
2. Update publishers, API schemas/routes, projections, and the TypeScript facade that consume the changed surface.
3. Update the relevant architecture or operational page, then run the scoped checks in [CONTRIBUTING.md](../../CONTRIBUTING.md).
4. Rebuild committed frontend assets after changes under `frontend/src/`.

For endpoint changes, inspect both [`tradingagents/web/api.py`](../../tradingagents/web/api.py) and [`frontend/src/api/client.ts`](../../frontend/src/api/client.ts). For artifact changes, inspect publication provenance in [`execution/output_publisher.py`](../../tradingagents/execution/output_publisher.py) and the corresponding reader projection.
