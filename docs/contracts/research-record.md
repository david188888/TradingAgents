# V9 Insight research contract

Status: Current

## Canonical ownership

CLI and Web accept only `evidence_v1` / `evidence-production-v9`. The public report is `insight-research-v1`, defined in [the Insight schema](../../tradingagents/agents/schemas/_insight.py). [Execution requests](../../tradingagents/execution/models.py), [the runner](../../tradingagents/execution/native_runner.py), [the graph](../../tradingagents/graph/insight_research.py), [saved-report validation](../../tradingagents/research/insight_report.py) and [the reader projection](../../tradingagents/web/research_record_projection.py) own machine behavior. Older workflows, readers and recovery are removed. Unsupported old runs are not upgraded or rewritten.

## Insight-first V9

Each specialist submits claim, evidence references, reasoning and counterevidence/limitations. Code assigns stable IDs, resolves E references and N numeric tokens against qualified saved facts, renders quantities with subject/period/unit, and saves valid siblings when another proposal fails. Unsupported ideas remain pending; only effective accepted Insights can support synthesis. Corrections preserve saved versions and superseded content cannot support the final conclusion.

Narrative references bind in the original proposal's catalog. When a later stage receives a different catalog, the host translates fact labels by stable identity and carries already resolved numeric values. A targeted specialist repair receives the failed draft and diagnostics. Its reply identifies each original target explicitly; a missing, duplicate, or unresolved repair leaves that item uncorrected. Accepted siblings are kept as saved.

Operating, event and market specialties receive isolated fact views. Explicit outer `search_requests` use the dual-search budgets; explicit `capability_requests` use the structured capability catalog and `SUPPLEMENT_CAPABILITIES` accounting. Company/date constraints, deduplication and source admission remain code-owned. Capability supplements are independent of the web-search enable switch. New material reopens only affected specialties. Exactly one critique/reply round reviews existing Insights. Reviews explain their scope even when no effective counterevidence is found. A synthesis judgement must cite saved accepted Insights; critical unresolved concerns or missing overall support suppress the rating while keeping usable research. Missing valuation inputs are explicit limitations rather than automatic directional prohibitions.

## Source and numeric boundaries

Dedicated interfaces supply identity, company and quantitative facts. DeepSeek/Tavily discovery adds context only after original-source qualification. Source cutoff, reporting period, currency, adjustment basis and availability remain explicit. Empty or failed retrieval is not proof of absence. Financial calculations retain exact inputs and reproducible lineage. The collected EvidenceRecord is internal V9 infrastructure, not an older model-output contract.

The model sees only qualified saved-source passages and deterministic number labels. It cannot invent citation identifiers, numeric receipts or new factual quantities. Program validation proves reference/number consistency; it does not establish causal entailment, economic correctness or predictive accuracy.

## Budgets and durable execution

[budget.py](../../tradingagents/execution/budget.py), [search_budget.py](../../tradingagents/execution/search_budget.py), [capability_catalog.py](../../tradingagents/dataflows/capability_catalog.py) and [native_versions.py](../../tradingagents/research/native_versions.py) own exact limits. Frozen source/model policy, capability-catalog digests and request configuration are part of identity. Each attempt is reserved before dispatch, including failed attempts. Unknown dispatched outcomes remain spent and are not repeated by recovery. Supplementary search, capability calls, repairs, focus and optional explanations keep their defined independent accounting. Capability backends accept the run's budgeted HTTP session: CNINFO announcements, shareholder counts, dragon-tiger and insider-change rows, the THS consensus screen and northbound series, SSE/CNINFO IR Q&A, and the Tushare valuation fallback count against `DATA_HTTP_ATTEMPTS`. Two backends stay outside it by design — baostock's TCP session for valuation history and the Wind CLI for risk metrics — while capability call counts apply to every card. Gateway calls are frozen in the journal, as `supplement_capabilities` attempts, and rendered in the Audit Center capabilities section. `financials_detail` and `industry_peers` stay prefetch-only: the minimum evidence chain already collects detail fields and peer context, so no duplicate requestable card exists.

The current journal is [research_checkpoint.py](../../tradingagents/runtime/research_checkpoint.py). Resume requires a matching V9 identity and intact saved artifact references. Reading and replay never acquire new data or models.

The updated handoff policy applies to new runs. A run interrupted under the previous policy cannot resume with the new prompts. Completed reports keep their original saved references and remain readable.

## Publication and projections

A frozen candidate, lifecycle authorization and committed journal barrier must precede the public Insight artifact. Cancellation and authorization are serialized by the lifecycle owner. Report completion additionally requires the canonical Markdown tree. Failed publication never becomes completion, and no legacy fallback exists.

`/api/runs/{id}/reader/record` exposes only `insight_ready` or an explicit unavailable response. Process and per-agent routes show qualified saved intermediate content without presenting it as a final judgement. Reader, audit and Markdown refer to the same validated report and saved evidence.

## Reader, focus and explanations

The baseline excludes the optional user focus. A focus response follows saved synthesis, cannot rewrite it, and uses existing evidence/budget. Web schedules a bounded plain-language explanation job after completion, independently of research acceptance. Explanations cover saved baseline and focus Insights and cannot change baseline ratings, numbers or references. GET reads saved artifacts; POST explicitly starts or retries an eligible job. Default jobs and saved V9 batched jobs have different limits; see [Web reading operations](../operations/evidence-research.md#read-a-result). Batched retry preserves accepted entries and the original request/deadline limits. [Explanation execution](../../tradingagents/execution/report_explanation.py) and [its schemas](../../tradingagents/agents/schemas/_report_explanation.py) own these policies; unsupported older workflows do not gain explanation support.

Completed, readable, evidence-complete and research-quality are separate claims. Empty output or a successful parser is not evidence of completed analysis. Real-model and human-reader acceptance remain separate from offline regression.

<a id="insight-first-v9"></a>
<a id="reader-focus-and-explanations"></a>

<a id="search-and-execution-limits"></a>
<a id="financial-and-price-calculations"></a>
<a id="numeric-and-factual-support"></a>
<a id="challenge-and-verification"></a>
<a id="publication-and-judgement"></a>
