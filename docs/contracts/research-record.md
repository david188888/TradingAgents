# Shared research record

Status: Current — compatibility publication and programmatic bounded verification.

`agents/schemas/_research_record.py` owns `research-record-v1`.
`research/record_assembly.py` adapts committed company research, holding review
and catalyst cases without model calls or provider requests. The original case
remains authoritative for its conclusion, quality and research eligibility.
This record does not establish that a conclusion is more accurate.

## Evidence and inference

The record distinguishes source evidence, fact/inference/unknown claims,
hypotheses, challenges, executed verifications and code-computed metrics.
References are run-local and validated; inference dependencies must point to
facts. A native hypothesis requires an explicit falsification condition.
Existing inferences are labelled `adapted_inference`; the adapter does not
invent assumptions, falsifiers or an original holding thesis.

V0 hashes the saved public evidence content and metadata. V1 preserves that
content and adds verification evidence; it requires an execution record. A
hypothesis cannot depend on evidence absent from its input snapshot. These are
contract constraints. Both existing production workflows still publish empty
executed verification lists. Model challenge dispositions remain reported assessments.

## Programmatic verification

`agents/schemas/_verification_plan.py` owns `verification-plan-v1`.
`execution/verification_executor.py::execute_verification` accepts a validated
V0 native record, a bounded plan and that run's existing `DurableBudgetLedger`.
Company, catalyst and holding records use the same function. Compatibility
inferences cannot be verified through it because they have no saved native
falsification condition. This function is not called by production graphs.

The plan binds a single-target challenge, native hypothesis and exact saved
assumption or invalidation text. Code accepts at most three allowlisted checks
in one supplementary round, critical challenges first. Pure tools read saved,
untruncated, qualified Tushare financial fields or compare a saved metric to an
explicit threshold. Financial operands require matching fields/report periods,
disclosure qualification and CNY amounts; growth requires a positive base and
uses the unit `ratio`. Metric units must match. Tools cannot fetch documents,
query vendors, run models or execute free expressions. Missing or future data
remains unavailable. A saved metric threshold check does not recompute raw prices.

Every new result has `scope=predicate_only` and binds its condition and plan
digest. Necessary-condition truth supports that condition; falsehood contradicts
it. An invalidation condition that is false stays inconclusive. These results
neither prove the whole hypothesis nor close a critical challenge. Text binding
also does not establish the economic sufficiency of its numeric translation.
Older records omit these additive fields and retain `scope=unspecified`.

The executor uses the caller's durable journal and original supplement/data
budgets, including existing consumption. Local execution spends no HTTP/model
attempts. Input identity reaches disk before dispatch. Changed input/plan is a
conflict. Saved task/output caches replay without work; dispatch without saved
result remains unknown and consumed, with no automatic retry. Persistence
failure forbids further dispatch. Cancelled/refused tasks have no execution
timestamp or verification record. Once the output is saved it is terminal,
including unresolved tasks; calling again does not reset the round.

Actual checks append V1 while preserving V0, claims, hypotheses, challenges and
metrics. Successful arithmetic adds derived evidence with input lineage; it
retains its source family and never becomes an independent source. An executed
unavailable check may add V1 without new evidence; zero execution creates no
V1. The validated output and operation outcomes are stored in the checkpoint.
This programmatic output has no native Reader publication path yet; the existing
Reader endpoint still requires a paired source case as described below.

Source content distinguishes excerpts, saved summaries and selected original
fields. The adapter admits only narrow source-specific field allowlists: CNINFO
announcement-list fields, Tushare identity/financial fields and qualified price
fields, plus matching classic financial bundles. Announcement titles are not
document bodies or proof that an event occurred. Missing content is explicit;
analyst prose is never relabelled as original source text. Private storage
locators, response envelopes and prompts are excluded. Content/snapshot hashes
refer to the admitted public content, not private files.

## Metrics and reading

Saved qualified catalyst Tushare price evidence projects annualized volatility,
signed historical return quantile, ES, drawdown, ATR and unavailable Beta when
no qualified benchmark exists. The projection does not recalculate metrics.
Each item carries its input reference/hash, method, unit, window, sample,
version and availability. Classic records currently have no corresponding
local price metrics; the existing valuation artifact is separate. See
[calculation methods](local-price-statistics.md).

The execution layer publishes the record after the existing source-case commit
or catalyst publication authorization. Replay reuses committed output.
Compatibility-record failure preserves the source case and emits a safe
`artifact.projection_unavailable` event. A future native workflow must enforce
its own mandatory publication gate rather than reuse this additive fallback.

`GET /api/runs/{run_id}/reader/record` validates committed artifact bytes,
identity and the paired source-case hash. It returns `ready` or a stable
unavailable reason; missing runs use the existing 404. Missing historical
records remain missing. Reading, expanding and refreshing never backfill,
dispatch models or query providers.

The workbench shows saved quantitative context below the catalyst brief and
alongside the classic Reader, with detailed evidence/hypotheses/verification
records collapsed. The catalyst citation drawer shows saved source content
before locator metadata. Records and source content are bound to the selected
run; missing content or unavailable values are not estimated. This is a limited
integration into existing Readers, not the complete approved unified layout.
