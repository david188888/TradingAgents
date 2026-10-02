# Shared research record

Status: Current — additive compatibility publication, not a migrated workflow.

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
contract constraints; the independent verification executor is not implemented
by this compatibility layer. Both existing workflows publish empty executed
verification lists. Model challenge dispositions remain reported assessments.

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
