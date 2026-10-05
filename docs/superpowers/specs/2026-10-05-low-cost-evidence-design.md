# Low-cost evidence and bounded challenge checks

Status: Historical

Do not use this document as evidence of current implementation behavior.
See [the documentation index](../../README.md) for current-state references.

Approved direction: user confirmation on 2026-10-05 of the recommendation in
[the investigation](../../reviews/2026-10-05-low-cost-evidence-investigation.md).
This specification expands that confirmed direction without paid acceptance,
remote publication, CLI work, or a new visual design.

## Objective and invariants

Give the Web user a useful, traceable answer from the minimum sufficient
available evidence. A missing optional dataset must not invalidate a supported
local comparison. Acquiring evidence is different from proving an economic
hypothesis. Preserve immutable prior records, provider families, report/quote/
capture dates, units, cancellation, hard budgets, saved-read behavior and old
checkpoint execution. Model text cannot manufacture a successful check.

## Version and ownership

New runs select `evidence-production-v5`; v1–v4 resume with their original
collectors, schemas, graph proposal types, conditions, budget and output rules.
New document selection/parser behavior is isolated from the v3/v4 functions.
Domain additions start in `agents/schemas/`; frozen source admission belongs to
`dataflows/`, local calculations to `research/`, orchestration to `execution/`
and `graph/`, and projections remain read-only.

The outer `research-record-v1` stays compatible through optional additions,
omitted when absent so old serialized checkpoint/snapshot bytes are preserved.
An explicit `research-assessment-v2` discriminant selects new challenge-check
entries. Old assessment-v1 stays strict and continues accepting only unresolved.
New frozen context/check artifacts are versioned, immutable, source-bound and
validated during both production and saved-record parsing.

## Document admission

Recognize annual/interim reports with a company-name prefix or delimiter, then
verify the actual PDF issuer, security, period and publication. Summary titles
are distinct from full reports; revisions without established vintage remain
unavailable. Accept `公司代码` as an explicit security label after the same issuer
checks. Keep the CNINFO attachment-ID/HTTPS allowlist, byte/page ceilings and
current-capture historical-vintage limitation.

Select at most one latest formal report, its matching summary and main operating
notice, and one other recent relevant event: at most four downloads, not a full
catalogue crawl. Prioritize the three evidence questions over incidental events.
Missing supplementary documents retain usable evidence and typed coverage gaps.

For reports, save bounded relevant pages for key financials, operating business,
cash-flow statement/reconciliation and material debt/risk context. At most twelve
excerpts per document, at most 4,000 characters each; full-text scanning remains
within the existing 500-page limit. Save the period, page, original text, PDF hash,
parser version and partial-body coverage. Headers carried across adjacent pages
must be explicit, never guessed from a distant table.

Extend deterministic extraction for explicit current/prior cash-flow bridges,
key financial rows and main operating notices. Distinguish Q2 from H1, physical
units from currency, consolidated from parent income, annual from interim data,
reported percentages from calculated values and blanks from numeric zeros.
Unsupported tables yield excerpts plus explicit unavailable numeric extraction.
Use Decimal arithmetic and disclosed precision; reject unmatched headings,
ambiguous columns, duplicated rows, wrong periods and reconciliation failures.
No OCR or model numeric extraction.

## Optional valuation context

Use inspected a-stock-data endpoint references and existing adapters where
appropriate, without installing an entire toolkit. Add bounded native frozen
capabilities for dated analyst forecasts and industry peer candidates.

THS individual institution rows are the main dated forecast input; EastMoney
reportapi is a bounded fallback/additional report source. Capture analyst/report
identity, publication, explicit forecast year, EPS unit and capture time. Keep
at most eight unique institutions and three forecast years, with a bounded
recent-report window of 180 calendar days. Reject future dates, ambiguous years,
nonpositive/nonfinite EPS and incompatible security identity. Deduplicate the
same institution/report across vendors; a feed is not an independent analyst.
Computed mean/range is over admitted rows, with its institution count and scope,
rather than blindly accepting an undated provider consensus.

Use EastMoney peer candidates as industry context, not automatic business
equivalence. Exclude aggregate rows and the target, retain at most five named
candidates, and obtain target/peer Tencent quotes in one bounded request. Admit
PE/PB comparison only for qualified identity and the same settled quote session.
Preserve candidate selection, incomplete population coverage and business-model
differences. Do not treat `REPORT_DATE` as a quote timestamp. Negative/missing
multiples remain unavailable; fewer than three admitted candidates is explicitly
limited context. No new peer-derived fair-value anchor is enabled by this change.
Existing historical valuation arithmetic remains authoritative.

Forecasts and peer context enter the valuation specialist view with their own
source families and limitations. Neither is compulsory for describing qualified
historical PE/PB positioning. A network failure is not absence of coverage.
Yahoo is not required for these A-share questions.

## External project review

The [2026-10-05 source review](../../reviews/2026-10-05-external-projects-evidence-review.md)
checked TradingAgents-astock, Vibe-Research, vibe-astock and Phoenix Tree AI.
It supports the existing bounded implementation rather than an architecture
migration. Reuse the principles of required/optional inputs, closed code-owned
checks, frozen operands and validation-time recomputation. Keep source/parser
versions and original records immutable even when a provider response changes.
Newly acquired data belongs to a new run; opening an old report cannot refresh
its evidence or judgement.

Do not import whole external runtimes, tool loops or short-term market
thresholds. Their industry-ranking functions do not supply individual peer
valuation; undated THS aggregates and guessed forecast years cannot replace
dated institution rows. Shared endpoints retain their original provider family.
User-uploaded PDF retrieval and subscription-model execution are deferred;
neither is necessary to answer the three current evidence questions.

## Deterministic checks and challenge states

Build three named local checks from frozen admitted sources, before model
synthesis: `operating_disclosures`, `cash_conversion`, `valuation_context`.
Each binds record/ticker/cutoff/input snapshot, input evidence IDs/hash,
calculation version, fields/periods and explicit satisfied/missing requirements.
Saved-record validation recomputes them; altered evidence, arithmetic or identity
must fail. Checks use no HTTP or model calls.

The scope registry is closed and code-owned. Its only answered questions are
`operating_disclosures.current_period_coverage`,
`cash_conversion.reported_bridge`, and
`valuation_context.supplementary_positioning`. Models may reference these
immutable questions but cannot rename them, change their requirements or add a
new answered scope. The question and successful result are generated from code,
not from a challenge's free-text statement. An economic parent keeps the separate
`economic_outcome=unresolved` irrespective of the child evidence result. Thus
selecting a passing child check cannot resolve an economic or mixed challenge.
The Reader must show both fields together, including the exact answered scope.

- Operating disclosure check: dated relevant-period official financial fields
  and substantive business/operating disclosure, with units and page locators.
  A full report or summary may supply financial fields; matching complementary
  documents share a disclosure family rather than independent confirmation.
- Cash conversion check: current/prior matching H1 (or annual) operating cash
  flow and consolidated net income, plus a reconciled bridge and its working-
  capital components. Describe observed changes and attribution in the reported
  bridge; do not infer structural persistence from two observations.
- Valuation context check: qualified target valuation and same-date peer context
  or dated analyst EPS input. Record which branch answered the question and
  remaining limitations. Historical positioning alone still supports a bounded
  historical statement when this supplementary check is unavailable.

The registry's minimum operands and boundaries are fixed:

1. Choose the latest admitted annual or H1 report period not after the cutoff;
   never mix rows from other periods to complete coverage. Operating coverage
   requires official current/prior revenue, parent-attributable net income and
   CFO in explicit CNY units, plus at least one quantitative business/operating
   measure with an explicit period and unit. Assets, liabilities, detailed debt
   and every segment are optional for this coverage question. Where a qualified
   supplier exposes the same field/period, compare at the official row's stated
   precision: a discrepancy beyond half the smallest reported unit is a failed
   comparison, not a silently preferred value. Missing supplier data is an
   explicit single-family limitation rather than a fabricated corroboration.
2. Cash conversion requires consolidated net income and CFO for current/prior
   matching H1 or annual periods; current/prior complete cash-bridge tables; and
   explicitly identified inventory, operating-receivable and operating-payable
   adjustments. A bridge spans only adjacent pages with an explicit table/unit
   header, net-income start and CFO end. Each sum of disclosed numeric components
   must match the disclosed CFO within rounding tolerance of half the smallest
   reported unit times the numeric component count plus one. Preserve empty
   cells as undisclosed, never convert them to zero; missing required working-
   capital cells, duplicated components or an unaccounted residual make this
   check unavailable. Preserve disclosed components and the reconciliation
   residual so validation repeats the exact arithmetic.
3. Supplementary valuation positioning requires the qualified target snapshot
   and either at least three different same-session candidate peers with usable
   PE/PB, or at least one positive, dated, explicit-year institutional EPS
   forecast in the 180-day window. One institution supports only a labelled
   individual forecast scenario. A sampled multi-institution mean requires at
   least three unique institutions, retains the actual count/range and is not
   advertised as a complete consensus. Neither branch proves fair value or
   resolves PE/PB divergence by itself. Zero eligible rows is unavailable;
   fewer-than-required peers and failed optional branches preserve whichever
   bounded branch actually passed, with its limitations.

New challenge proposals select a check ID and explicit question scope, or retain
an unclassified economic question. The code generates bounded outcomes:

| Outcome | Meaning and gate |
| --- | --- |
| `evidence_sufficient` | The named evidence question has its required admitted inputs and passed local checks; economic implications remain conditional |
| `risk_supported` | A saved, executed numeric predicate supports a specifically observed risk fact; not proof of its cause, persistence or the whole hypothesis |
| `future_observation` | A structured observation period is after the cutoff; current analysis uses available evidence and keeps the future follow-up |
| `unresolved` | Required evidence/check is missing, fails, or the economic question exceeds the named check scope |

`risk_supported` is restricted to code-owned observed conditions, initially
`cash_conversion.cfo_yoy_decline`: admitted matching-period CFO growth below
zero, with the saved operand references and calculation. Its immutable label
describes a reported CFO decline; no caller/model can substitute structural
deterioration, solvency or causation. A structured future-period observation
retains its declared period/date, but never changes the current registry check's
status or the economic parent's unresolved status. All outcome decisions,
predicate operands/results, future-date comparisons and scope bindings are
recomputed from saved inputs on record validation, not merely the three check
summaries. A mismatch rejects publication and saved-record parsing.

Every entry retains the original challenge, declared scope, check/verification
references, supporting evidence and remaining uncertainty. Classification alone
cannot close an economic challenge; `predicate_only` keeps its original limit.
A mixed challenge may show an answered evidence sub-question while its economic
question stays unresolved. No language matching or model-supplied status can
produce resolution. Future observation never stands in for missing current
critical inputs. Critical unresolved dependencies remain visible.

Keep dimension judgements conditional when they use inference. Retain the
conservative overall PASS rule: a report with economic challenges does not gain
PASS merely because data arrived. A check outcome is explicitly local, not an
accuracy rating. Existing valid dimension references and all publication barriers
continue to be enforced.

## Budget, errors and recovery

All new fetches use the existing BudgetedSession and durable capability cache;
logical keys include source/parser version and identity. Reuse existing total
data/HTTP limits and five model stages plus the single bounded repair. Do not
add a model stage or hidden provider retry. Stop supplementary fetches when
their existing budget is exhausted and keep earlier qualified results.

Disabled/excluded vendors remain disabled; source failures expose safe typed
reasons. Cancellation, deadline, checkpoint conflict and unknown dispatched
calls never become source fallback. Cached results replay without transport.
All new mutable test/probe data is isolated from `~/.tradingagents/`.

## Reader and exports

Keep the current single-column Reader hierarchy. Show concise Chinese check
labels, answered scope, verified basis and remaining risk in the challenge
details; distinguish future follow-up from current evidence failure. Source
details retain actual document pages, dates, units and capture limitations.
JSON, Web Reader, Markdown and self-contained HTML all derive from the same
validated record; reading or opening citations never initiates data fetching.
Old records retain original labels and outcomes.

## Acceptance

Use 600803. Focused tests cover real-title selection, company-code header,
H1/Q2 units/columns, cash-bridge arithmetic and tampering, optional forecast/peer
paths, forecast date/year/deduplication, timestamp/identity mismatches, critical
economic questions staying open, missing optional context, budget/cancellation,
v1–v4 checkpoint replay and unchanged old serialized hashes. Synthetic graph
tests cover publication and UI contracts without pretending to be real research.

Run available docs/Ruff/Python regression, frontend typecheck/Vitest/build and
tracked browser tests. Independently inspect a new 600803 HTML and actual Web
record view. Real public-source ingestion may run with model transport disabled;
any preview using fixed model proposals is marked as a deterministic fixture,
not a new live AI assessment. No new paid-model acceptance, GitHub publication or
data deletion is authorized in this stage.
