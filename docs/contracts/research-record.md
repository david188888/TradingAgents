# Shared research record

Status: Current — compatibility publication and evidence_v1 native research execution.

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
contract constraints. The classic and catalyst_v1 compatibility workflows still publish empty
executed verification lists; evidence_v1 executes bounded native checks. Model challenge dispositions remain reported assessments.

## Programmatic verification

`agents/schemas/_verification_plan.py` owns `verification-plan-v1`.
`execution/verification_executor.py::execute_verification` accepts a validated
V0 native record, a bounded plan and that run's existing `DurableBudgetLedger`.
Company, catalyst and holding records use the same function. Compatibility
inferences cannot be verified through it because they have no saved native
falsification condition. The evidence_v1 shared kernel calls it before final synthesis; old production
graphs do not call it.

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
The native kernel publishes this output through the mandatory publication
gate below. The default Web evidence_v1 request/profile and RunManager integration
cover all three modes and batch company research. The Reader accepts committed native records without a paired case;
the paired-case check applies only to compatibility records.

## Native shared kernel

`research/native_record.py::build_native_record` derives V0 facts from saved,
qualified source fields. It binds source identity and context digests, retains
source families, labels title-only disclosures and user thesis declarations,
and uses the same financial operand parser as C1. It performs no retrieval.

`graph/native_research.py::run_native_research` accepts this facts-only record
and the run's existing durable ledger. Operating, event and market specialists
see separate fact views. Reservations and merge order are fixed, with at most
two specialist workers. Each hypothesis requires cited facts, an invalidation
condition and an alternative explanation. One anonymous challenge stage can
return zero challenges. Immutable condition bindings compile up to three C1
checks before one synthesis; no fixed bullish/bearish stance is required.

The optional `assessment`, owned by `_research_assessment.py`, binds the final
snapshot, ordered mode dimensions, up to three key claims, primary challenge
and next check. Missing valuation inputs or original holding thesis constrain
the corresponding dimension. Announcement titles do not prove delivery;
predicate checks cannot close economic challenges. Unresolved dimensions keep
the assessment partial. No research accuracy improvement has been measured.

Checkpointed stage inputs and validated outputs replay without work. Dispatched
model calls with no saved result stay consumed and are not automatically
redispatched. The exact facts-only V0 is saved before model dispatch;
`load_native_seed` reads it on recovery. Raw provider context must not be used
to rebuild source-family digests after persistence, because RFC 8785 can
normalize `2.0` to `2` while provider JSON used the original representation.
Source-content strings and typed metrics in the saved V0 preserve its identity.
The optional assessment is omitted when absent, preserving old
record bytes/digests. `execution/native_model.py` supplies a bounded SDK adapter;
the kernel itself has no model/provider SDK dependency.

Source content distinguishes excerpts, saved summaries and selected original
fields. The adapter admits only narrow source-specific field allowlists: CNINFO
announcement-list fields, Tushare identity/financial fields and qualified price
fields, plus matching classic financial bundles. Announcement titles are not
document bodies or proof that an event occurred. Missing content is explicit;
analyst prose is never relabelled as original source text. Private storage
locators, response envelopes and prompts are excluded. Content/snapshot hashes
refer to the admitted public content, not private files.

## Metrics and reading

Saved qualified native and catalyst Tushare price evidence projects annualized volatility,
signed historical return quantile, ES, drawdown, ATR and unavailable Beta when
no qualified benchmark exists. The projection does not recalculate metrics.
Each item carries its input reference/hash, method, unit, window, sample,
version and availability. Classic records currently have no corresponding
local price metrics; the existing valuation artifact is separate. See
[calculation methods](local-price-statistics.md).

The execution layer publishes the record after the existing source-case commit
or catalyst publication authorization. Replay reuses committed output.
Compatibility-record failure preserves the source case and emits a safe
`artifact.projection_unavailable` event. Native callers use
`execution/native_publication.py::publish_native_record`: a frozen candidate,
lifecycle authorization and committed checkpoint must precede public promotion.
NativeRunner also reenters consumer lifecycle arbitration when replaying an already
committed record after interruption; the publisher itself retains read-only replay.
Publication failure raises rather than using the additive fallback. Native
Markdown is rendered from that same record without another model call.

`GET /api/runs/{run_id}/reader/record` validates committed artifact bytes,
identity and, for adapted records, the paired source-case hash. It returns `ready` or a stable
unavailable reason; missing runs use the existing 404. Missing historical
records remain missing. Reading, expanding and refreshing never backfill,
dispatch models or query providers.

The evidence_v1 workbench uses the native record as its single main Reader: judgement,
principal challenge, key grounds, valuation/risk context and next check appear before
collapsed evidence/hypothesis/verification details. It does not fetch or mount the
classic/catalyst case Reader. Creation offers the three native scopes and fixed roles.
Existing profiles retain saved quantitative context below the catalyst brief and
alongside the classic Reader. The catalyst citation drawer shows saved source content
before locator metadata. Records and source content are bound to the selected
run; missing content or unavailable values are not estimated. V4 adds a saved-content modal and deterministic valuation context. Same-evidence
quality/cost comparison and broader human acceptance remain separate from browser
checks and single-symbol operational smoke. See
[evidence research operations](../operations/evidence-research.md).

## Official document content and coverage scope

Native v3 retains the v1 wire shape. `cninfo.document_excerpt` is saved as
`excerpt`, with a PDF page locator and document hash; bounded excerpts are not
full document coverage. `cninfo.operating_detail` retains qualified row fields,
original row/header/unit, period, classification and page/hash. Both are official
company disclosures, not independent implementation verification. Operating rows
are separate from the closed Sina/Tushare financial families accepted by C1.

Collector-produced limitations use `global_coverage:<capability>:<status>` and
`global_gap:<capability>:<reason>`. New specialist unknowns are
`specialist_unknown:<role>:<text>`; the role is code-owned. Synthesis receives
collector coverage in addition to these scoped unknowns. Read projections
label each scope explicitly, and do not upgrade old unscoped unknowns into a
global missing-source finding. These strings are additive annotations, not
new model permissions or a change to the frozen evidence qualification rules.

## Native v4 valuation

The optional `valuation` field carries `NativeValuationV1`: saved typed inputs,
input SHA256, source evidence IDs, deterministic `ValuationAssessmentV1` and
limitations. Validators bind run/ticker/cutoff, require qualified source refs
and recompute the input digest and assessment. Producers admit source payloads
against frozen family hashes and qualified dates. Absence omits this additive
field from serialized records, preserving old record and checkpoint digests.
The code-owned schema, rather than this prose, defines the complete fields.
V1–V3 recovery does not gain V4 facts, source views, valuation policy or prompt
inputs. Reader displays missing valuation explicitly without deriving new data.

## Native v5 bounded evidence checks

The outer wire contract remains `research-record-v1`. Optional `evidence_checks`
and `challenge_bindings` are omitted when absent, preserving old serialization.
V5 uses `research-assessment-v2`; v1 remains accepted for old records. Canonical
definitions are in `agents/schemas/_evidence_checks.py`, `_native_stage.py` and
`_research_assessment.py`, with binding/recomputation in `_research_record.py`.

Official numeric evidence carries explicit units, current/prior periods, raw
cells and row/header page locators. Dated EPS scenarios and target-bound peer
selection/quotes retain their dates and identities. They supplement the existing
valuation artifact without manufacturing additional reference-price anchors.
Official report, summary and notice for one security/period share one disclosure
family; repeated fields and multiple wrappers do not create independent sources.

`research/minimum_evidence.py` owns the finite question scopes, arithmetic and
requirements. Check identity and input content digest bind frozen V0, even after
C1 adds a later snapshot. Validation recomputes all saved checks and challenge
assessments; changing outcome, question, arithmetic or scope rejects the record.
The model may select an admitted check/risk/date binding but cannot write a
resolved economic outcome. Reader distinguishes evidence sufficiency, an observed
CFO-decline risk, future observations and unavailable/conflicting evidence.

Reader and Markdown use this same validated record. Reading performs no external
retrieval or model generation. The standalone 600803 HTML acceptance preview is
an artifact produced from that record, not a new runtime HTML-export endpoint.
V1–V4 recovery never acquires V5 source views, prompts, checks or outcomes.
