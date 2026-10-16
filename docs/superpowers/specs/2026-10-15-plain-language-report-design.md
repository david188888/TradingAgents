# Plain-language report and evidence explanations

- **Status: Frozen Design**
- 日期：2026-10-15。

Date: 2026-10-15. Status: approved by the user in chat; implemented and validated locally on
2026-10-16. This document records the design, not a release or deployment. The user approved the hybrid direction: deterministic metric and number
presentation plus model explanations of saved professional analysis.

## Purpose

A reader without a finance background should understand what an indicator means,
what the saved observation or analysis says, and what remains uncertain. Keep the
professional statement, dates, scope and source accessible beside the explanation.
Cover the final native report, its related-evidence rail/drawer and supported
facts in the complete record. Preserve the saved professional report as an artifact.

Success means that the example financial fields and historical-risk statistics
are understandable without decoding source field names, and that narrative
judgements have a short explanation of their existing reasoning. An explanation
must not become a second investment assessment.

## Confirmed scope and proposed execution

Approved: rules and models both participate; professional material remains
available; numbers are formatted for reading without changing their stored values.

Proposed: after a newly created native study completes with a qualified published
record, schedule a bounded explanation job. Its outcome is independent of research
success. Opening Reader, changing a selection, following evidence or exporting
never starts a model request.

The user explicitly selected: generate model explanations only for new studies.
Apply supported deterministic explanations and number formatting to readable
historical records, without a historical model-generation action. Opening or
resuming a historical study does not opt it into model explanation generation.

## User experience

Each supported data card starts with a precise metric name and concise value.
Below it, show a short plain explanation: definition, the limited meaning of this
observation and any essential qualification. Professional wording, method and
unrounded value remain reachable through an adjacent disclosure. Keep source
inspection visible rather than burying it inside technical metadata.

For model-explained analysis, show the saved plain explanation beside the
professional paragraph. Label its origin as Model explanation; label deterministic
content as Indicator explanation where the distinction affects understanding.
Do not duplicate three generic warnings on every card. Specific uncertainty,
conditions, negation, partial coverage and missing overall rating stay visible.

The rail and narrow-screen drawer reuse the same target explanations as the main
report. Replace repeated full professional sentences as headings with short entity
labels; retain their complete content below. Source quotations stay verbatim.
Explain how a cited source relates to the selected claim rather than rewriting
the source as a newly verified fact.

Show generation state in the report, with a retry action only after an explicit
failure or interrupted attempt. Switching views/runs must not show another run's
explanation. Preserve keyboard access, focus return and existing source links.

## Deterministic interpretation and formatting

One backend-owned presentation builder reads the validated public record and
produces typed display values, definitions, bounded interpretations and provenance
references. Frontend consumers reuse this result. Frontend components do not
independently invent financial rules. Existing Markdown remains unchanged;
adding a new export surface is outside this change.

Start with revenue, consolidated/parent net income, total assets, total liabilities,
operating cash flow, quotes, PE/PB, annualized volatility, historical return
percentile, historical ES, maximum drawdown, ATR and Beta. Explain consolidated
scope, report versus observation dates and actual versus forecast values when
applicable. Do not infer reporting frequency just from an end date, turn total
liabilities into interest-bearing debt, or describe net income as cash received.
Do not calculate new valuation or leverage ratios for this feature.

Use qualified typed metrics, known source selectors and admitted numeric bindings.
For old statements, accept only explicitly supported, exact producer grammars
with matching source/metric identity. Never guess an arbitrary statement's unit
from a label or apply global decimal replacement to prose or source excerpts.
Unsupported material keeps its professional text and a clear explanation status.

Formatting rules:

- Return fractions become percentages; a percentage already in percent units
  is not multiplied again. Preserve signs, including positive return quantiles.
- CNY uses yuan, ten-thousand yuan or hundred-million yuan by magnitude; share
  prices use yuan/share; multiples and dimensionless metrics keep their meaning.
- Normally show at most two decimal places, with grouping where appropriate.
  Keep a tiny nonzero value visible using additional significant digits rather
  than rounding it to zero; normalize rounded negative zero only for exact zero.
- Missing, invalid and nonfinite values remain unavailable, distinct from zero.
  Dates, periods, sample counts and source identifiers are not decimal values.
- Keep the exact saved representation, raw unit and method in the professional
  disclosure; do not claim to recover precision lost upstream.
  A formatted display is approximate when rounding changes the shown precision.

Example: -0.04471005588515259 signed_return_fraction displays as approximately
-4.47%. Explain that the historical daily-return distribution's fifth percentile
is that threshold, based on the saved sample and window. Do not promise an exact
count of days below an interpolated threshold, a future probability, a maximum
loss or a fair-value interval. Annualized volatility of approximately 49.97%
describes the annualized scale of past return variability, not an expected return
or a guaranteed price band. Negative operating cash flow describes net cash
outflow from operating activities during the stated reporting period, not an
equal accounting loss or a proved cause.

## Model explanation boundary

Build a deterministic target list from report-visible professional fields:
overall judgement, supporting/opposing reasons, dimension judgements, change
conditions, key claims, challenges and next checks, public replies/adjudications,
valuation reasoning and a published focus answer when present. Include supporting
claims used by the evidence rail. Basic financial and quantitative facts use the
deterministic layer first. The same target has one explanation across surfaces.

Each target has a stable key, original text hash, original field path/entity,
qualified claim/evidence references and status. Pass only validated public
content and the scoped dependencies needed to understand that target. Treat all
quoted research/source text as data, never as instructions. Exclude prompts,
credentials, raw provider envelopes, local paths and unrelated runs.

The model returns a closed per-target object: target key, a short plain-language
explanation, what remains uncertain and the supplied references it uses. It may
clarify existing reasoning and conditions; it may not invent causes, comparisons,
forecasts, new ratings, targets or trading instructions. An uncertain or withdrawn
claim stays uncertain or withdrawn. A report with no overall rating still has no
overall rating after explanation.

Model explanation text is qualitative. Numbers, dates, thresholds and financial
units are rendered from the deterministic layer alongside it. Reject unbound
numeric literals using the existing numeric-literal discipline; the model cannot
recalculate or round the report's values. This keeps the explanation outside the
baseline numeric receipt and publication contract.

Validate closed schema, unique target keys, exact source-text binding, allowed
references and numeric discipline before saving. Reject unknown or cross-target
references and duplicate entries. A malformed envelope is not salvaged by string
parsing; a schema-valid batch can retain independently valid entries and mark
other targets unavailable. Structural checks do not prove semantic fidelity;
prompts, representative evaluation cases and review must address whether wording
changes an economic meaning or removes a qualification. Do not label that as
machine-proved economic correctness.

## Saved supplement and generation

Introduce a separate versioned explanation artifact and public DTO, without
adding model-generated explanations to ResearchRecordV1 or altering its digest.
Bind it to run ID, baseline artifact ID and digest, public focus digest if used,
target text hashes, explanation policy/version and language. Persist model/config
identity and creation time as provenance, not as the model identity of the original
research. A stale or corrupted supplement becomes unavailable independently.

Separate generation from projection. A GET projection constructs deterministic
presentation and reads a valid saved supplement only. A generation service owns
bounded model work, cancellation, deduplication and persistence. Automatic new-run
generation and an explicit retry of an eligible new-study job use this same
service. Do not silently start work during recovery of an old run or on app start.
New-study metadata opts into automatic generation; absent policy retains old
execution behavior. Research stage counts and final rating do not include this
reading supplement as a new research Agent.

Use the configured quick model/provider through the maintained model transport,
including the existing ChatGPT subscription path and its recovery semantics.
For automatic new-study jobs and their retries, freeze the original research
configuration and identify the explanation model separately from research output.
No model/provider fallback is introduced. Do not copy the legacy debate-summary
generator's API-only transport or unrestricted exception/retry behavior.

NativeModelCaller is coupled to a native workflow journal and must not be
instantiated with a fabricated native identity or the completed run's ledger.
Extract the request-only provider construction/invocation seam, preserving
provider configuration, ChatGPT authentication, cancellation/deadline and the
global model slot. Inject dispatch, usage and safe-diagnostic callbacks so each
caller records its own attempts. The supplement owns its closed schema,
instructions, repair and independent ledger; existing native callers retain
their original behavior. Register a dedicated aux.report_explanation task key
for configured effort selection rather than reusing a research role identity.
Disable SDK-level retries for supplement requests as well as wrapper retries;
DeepSeek and subscription transports must obey the same two-dispatch ceiling.
This extraction is restricted to the transport needed by these two callers.

A job admits at most 32 model targets and 32,000 input content characters, counting
the target text and scoped dependencies together and preserving each admitted
target whole. Prioritize the overall judgement, its reasons and
conditions, dimensions, next check and main challenge, then linked evidence and
remaining report narrative in stable order. Record excluded targets explicitly as
capacity-limited; do not claim full coverage or silently truncate professional
text. Each returned explanation plus uncertainty is at most 240 characters.
Use one main request and at most one shared structured repair, with a 120-second
overall deadline and existing global model-concurrency control. Record every
dispatched attempt; an unknown outcome counts as spent and is not automatically
replayed after restart. Quota, permission, login and capability failures do not
switch providers or trigger automatic retries. An explicit user retry is a new
bounded attempt with visible state.

Persist separate explanation job state and its attempt ledger. Deduplicate by
baseline/focus digests, target set, language and explanation policy; freeze the
selected model identity at first dispatch. Duplicate button clicks or completion
notifications reuse a pending/valid job. Do not mutate the native research
checkpoint, prior report artifacts or terminal research status. Unfinished jobs
after restart expose interruption/unknown state and require an explicit retry.
Use RunStore atomic writes and locks within the supported single-service process.
No second task queue, database or multi-process execution framework is needed.

## API and presentation ownership

Canonical explanation models belong under agents/schemas; deterministic target
selection/presentation and validation under research; generation orchestration
and its ledger under execution/runtime. Web owns read/write endpoints and job
scheduling, never the financial definitions. Add a read-only explanation endpoint
and an explicit POST generation/retry endpoint. POST allows retrying an opted-in
new-study job only; creating any historical job is rejected. A valid cached job is returned
unchanged, not regenerated by POST.
Closed public states distinguish not generated, generating, available, partial,
failed, interrupted, unsupported and corrupt. A missing published baseline is
unavailable and cannot launch an explanation job. Responses include only public
references and safe reason codes, never credentials or model response dumps.

Frontend api/contracts mirrors canonical DTOs. A run-scoped hook loads the
presentation and saved supplement, follows active-job state with bounded polling
while visible, and stops on terminal state. Shared display components serve
CompanyBasics, report analysis, MetricCard, ReaderEvidence and complete-record
facts that have supported presentations. The same helpers can serve saved stage
facts, but this feature does not generate model explanations of unpublished
proposals or change the pending stage-output implementation.

Keep the original saved Markdown artifact and export behavior unchanged. A new
plain-language export is deferred; this change improves Web reading only.

## Failure behavior

If generation fails or budget/time expires, the professional report and all
supported rule explanations remain available. Partial explanation coverage is
visible per target and in the report status. Failure of an explanation cannot
upgrade or downgrade research quality, complete a missing synthesis, change an
investment stance, close a challenge or fabricate missing data. For basic-report
and specialist-summary delivery, explain only the material that exists and retain
the original missing-synthesis notice. Unsupported historical workflows keep
their existing reading path and expose the supported scope honestly.

## Validation and closeout

- Financial/metric fixtures cover actual versus forecast, cumulative versus
  point-in-time fields, positive/negative/zero/tiny values, unavailable values,
  percent versus fraction, positive VaR, ES, volatility, drawdown, ATR and Beta.
- Test exact target and digest binding, cross-target references, duplicate keys,
  changed baselines/focus, unbound numbers and invalid/partial model output.
  Include qualitative cases for uncertainty, negation, withdrawal, missing
  synthesis, causal overstatement and an explanation that reverses the original.
- Use fake model transports to verify automatic opt-in, rejection of historical jobs,
  config provenance, single dispatch on duplicate requests, bounded repair,
  cancellation/deadline, quota failures and unknown-outcome restart behavior.
- Assert GETs, evidence selection and export cause no model/data calls or writes;
  baseline bytes/digest, original Markdown and research terminal state remain
  identical before and after explanation generation.
- Frontend tests cover the example financial and risk cards, matching rail/drawer
  explanations, professional disclosures, missing/partial jobs and stale-run
  responses. Browser checks cover narrow and desktop reading, source/focus
  navigation and long-content wrapping. Do not claim real-model quality from
  mock tests. Real provider evaluation requires an explicitly scoped run.
- Preserve the pre-existing stage-output changes. Run scoped Python/frontend
  tests, docs checks, Ruff, typecheck/build and diff checks; include rebuilt SPA
  assets. Update both READMEs, ARCHITECTURE, Reader docs and indexed explanation
  contract/operations references to match the final implemented behavior.

## Implementation sequence after approval

1. Canonical explanation/presentation contracts and deterministic formatting,
   including fixture-based compatibility with existing records.
2. Bounded supplement execution, provenance, persistence and read projection;
   automatic opt-in and the confirmed historical policy.
3. Shared frontend rendering for report and evidence plus job/retry state.
   Retain all professional/source disclosures.
4. Integration/browser validation, documentation and generated-asset closeout.

This specification does not authorize a real provider evaluation, service
restart, Git publication or rewriting user research data during development.
