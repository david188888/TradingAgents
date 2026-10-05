# Research Reader Architecture

- **Status: Current**（current-state 文档；graph/契约变化时对照 `tradingagents/graph/setup.py`、`tradingagents/execution/` 与 `tradingagents/web/` 校验）

This page maps the classic, catalyst and native research read paths. The public surface is read-only and research-only; it does not create orders, portfolio actions, or investment advice.

## Entry And Modes

The maintained entry is the Web workbench, launched by `tradingagents web`.
New single and batch studies use `evidence_v1`; old `classic` and `catalyst_v1`
records remain readable and compatible interrupted runs resume their original
version and spent budget. New creation/retry for those old profiles returns
`410 research_profile_retired`. CLI analysis remains legacy code outside
continued maintenance. The neutral [`AnalysisRequest`](../../tradingagents/execution/models.py)
still supports compatibility consumers and is not the Web default policy.

Native research supports company, catalyst and holding scopes without classic
scheduling overrides. Holding research requires `HoldingContext`; company and
catalyst modes cannot carry it. The retained classic contract accepts company
and holding modes with a horizon, while `catalyst_v1` uses company mode and its
fixed outlook. See [legacy catalyst recovery](../operations/catalyst-research.md)
and [Web operations](../operations/evidence-research.md).

Classic is assembled by [`graph/setup.py`](../../tradingagents/graph/setup.py) and executed through [`TradingAgentsGraph`](../../tradingagents/graph/trading_graph.py) and [`AnalysisRunner`](../../tradingagents/execution/runner.py). Catalyst and native profiles use their neutral executors. The workbench observes runs through FastAPI/SSE adapters and persists events and artifacts in the local [`RunStore`](../../tradingagents/runtime/store.py), normally under `~/.tradingagents/web/runs/`.

## Native Research Path

New studies use workflow V5: freeze qualified sources, isolate operating/event/
market specialists, merge in fixed order, run independent challenge and bounded
checks, synthesize once, validate and publish the saved `research-record-v1`.
`NativeRunner` and `graph/native_research.py` own execution; the host derives
assessment v2 from admitted bindings and recomputed local results.

The single-column Reader prioritizes judgement, unresolved risk, key evidence,
valuation context and the next check. V5 adds expandable operating-disclosure,
cash-reconciliation and valuation-context checks with values, units and saved
source references. A passed evidence question does not resolve economic cause,
persistence or fair value. Old V1–V4 recovery never acquires V5 collection,
prompts or checks. Reader and Markdown consume the same validated record;
the 600803 standalone HTML is a labelled acceptance artifact, not an additional
runtime export endpoint. See the [record contract](../contracts/research-record.md#native-v5-bounded-evidence-checks).

## Retained Classic Research Path

Before role output is published, the classic graph resolves run-scoped identity and analysis cutoff, then follows the configured data-window policy. Its prefetch sequence is (the A-share supplement is conditional):

1. A-share supplement
2. adjusted price window
3. news window
4. fundamentals
5. valuation evidence
6. analyst roles, Evidence Steward gate, debate, and Research Manager

Relevant implementations are [`analysis_cutoff.py`](../../tradingagents/research/analysis_cutoff.py), [`horizon_policy.py`](../../tradingagents/research/horizon_policy.py), [`price_prefetch.py`](../../tradingagents/research/price_prefetch.py), [`news_prefetch.py`](../../tradingagents/research/news_prefetch.py), [`fundamentals_prefetch.py`](../../tradingagents/research/fundamentals_prefetch.py), [`valuation_data_tools.py`](../../tradingagents/agents/utils/valuation_data_tools.py), and [`graph/setup.py`](../../tradingagents/graph/setup.py). Analysts consume the run's prepared evidence context. The Evidence Steward produces the gate verdict used by research assembly and eligibility; model prose alone cannot upgrade eligibility.

## Publication

The Research Manager emits a candidate draft. [`research/case_assembly.py`](../../tradingagents/research/case_assembly.py) resolves evidence and coverage keys, drops claims that cannot be safely resolved, computes eligibility/data quality, and returns a schema-valid `ResearchCaseV2` or an honest partial/fail-stop case.

The execution commit path publishes `research-case-v2` with current-run provenance and a provider-neutral `research-package-v1` fact layer. The package carries the code-owned metric dictionary, evidence labels, and explicit unknowns; it does not fabricate numeric observations when the current provider bundle cannot be transformed safely. See [`execution/runner.py`](../../tradingagents/execution/runner.py), [`research/research_package.py`](../../tradingagents/research/research_package.py), and [`execution/output_publisher.py`](../../tradingagents/execution/output_publisher.py). After `run.completed`, [`web/manager.py`](../../tradingagents/web/manager.py) may publish `thesis-diff-v1` as a best-effort derived artifact. [`research/thesis_diff.py`](../../tradingagents/research/thesis_diff.py) compares the same ticker and horizon structurally; a failed diff does not change the completed run or Research Case.

This case path describes classic publication. Native publication instead requires a committed `research-record-v1` with its dimension-gated assessment, without a paired legacy case or a second summary model. Failure to publish the native record cannot become a completed run. Catalyst publishes its validated case and an additive shared record. See [shared record publication and compatibility](../contracts/research-record.md).

## Reader Projection And Degradation

`GET /api/runs/{run_id}/reader` is implemented by [`web/reader_projection.py`](../../tradingagents/web/reader_projection.py) and validated by [`web/reader_models.py`](../../tradingagents/web/reader_models.py):

- `typed`: a readable `ResearchCaseV2` projection with research tilt, claims, scenarios, review items, analyst cards, coverage, omissions, optional thesis diff, and bounded audit counts.
- `research-package-v1`: a separate read-only structured package at `/api/runs/{run_id}/reader/package` for metric definitions, point-in-time observations, peer comparisons, logic edges, and portable Agent consumption. Its absence or partial unknowns never upgrades a Reader conclusion.
- `research-record-v1`: a committed record at `/api/runs/{run_id}/reader/record`, additive for classic/catalyst and the mandatory main report for native research. It carries admitted public source content, inference dependencies and saved quantitative metrics. Converted legacy inferences are not executed verification; native checks carry explicit execution and lineage. This separate endpoint exposes public content hashes/snapshots; it excludes private locators and raw envelopes. See [contract and compatibility limits](../contracts/research-record.md).
- `legacy`: a historical run without a typed case; it remains explicitly legacy and does not fabricate typed fields.
- `unavailable`: a typed case is missing, unreadable, or unsupported; the response carries a stable reason code and audit counts.

The original Reader projection reads persisted artifacts and events only. It is side-effect free, does not call an LLM or network, and does not expose raw evidence payloads, prompt text, locators, content hashes, or internal snapshots. The separate shared-record endpoint admits only its explicitly public content and provenance.

The workbench routes native runs to `NativeResearchPage`, catalyst cases to their case page, and classic terminal summaries to `LegacyReader`. The original typed Reader/Companion API remains supported but is not a second default classic completion page. A readable or completed result may still be partial or LOW_CONFIDENCE; those states do not establish research adequacy or predictive accuracy.

## Companion And Audit Boundaries

Companion is an on-demand, bounded explanation of one public `role`, `claim`, `evidence`, or `risk` selection: [`reader_projection.py`](../../tradingagents/web/reader_projection.py) and `/api/runs/{run_id}/reader/companion`.

Audit Center is a separate terminal-run projection. Its summary and detail routes are backed by [`audit_models.py`](../../tradingagents/web/audit_models.py), [`audit_projection.py`](../../tradingagents/web/audit_projection.py), and `/api/runs/{run_id}/audit*`. It exposes safe counts, stage/role/capability/tool/artifact metadata, and bounded detail availability. Running analyses use the real-time inspector; Audit Center rejects non-terminal runs and never becomes a raw trace dump.

The frontend wire facade for these routes is [`frontend/src/api/contracts.ts`](../../frontend/src/api/contracts.ts), with request functions in [`frontend/src/api/client.ts`](../../frontend/src/api/client.ts).
