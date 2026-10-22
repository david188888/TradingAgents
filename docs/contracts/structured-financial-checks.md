# Structured financial checks

Status: Current

Fresh V7 identities freeze `structured_financial_policy=structured-financial-checks-v1`.
`research/native_record.py` applies the matching seed marker and selects
`minimum-evidence-v3`; resumed runs without the policy keep their existing checks.
The outer record and check pack remain `research-record-v1` / `evidence-checks-v1`.

Canonical contracts live in `agents/schemas/_evidence_checks.py` and
`_research_record.py`. `research/structured_financial_checks.py` owns the new
finite comparisons; `minimum_evidence.py` owns pack assembly and challenge outcomes.

## Independent questions

V3 contains exactly five unique checks in canonical order: the three original
operating-disclosure, full reported cash-bridge and valuation questions, followed
by `financial_baseline` and `cashflow_comparison`. The original scopes and their
requirements are unchanged.

`financial_baseline.structured_coverage` requires revenue, parent-attributable
income and operating cash flow for the current and prior-year matching period
from one qualified structured supplier. `cashflow_comparison.same_period_endpoints`
requires consolidated net income and operating cash flow on that same basis.
It reports the saved amounts, amount changes, positive-base percentage changes
and CFO minus consolidated net income. Parent-attributable income cannot replace
consolidated income in that comparison. Neither question proves operational
volume coverage, a complete accounting bridge, persistence or economic causes.

Only frozen, available, qualified financial sources with complete source fields,
valid disclosure dates and matching periods enter. The target is the latest
disclosed quarter end in the qualified income/cash-flow tables, independently
of PDF rows. Values use cumulative consolidated CNY statements and compare the
same month/day in the prior year. Missing latest-period data never falls back
to an older complete pair. Duplicate periods and mixed-supplier cell assembly
cannot produce a complete comparison. Nonpositive bases omit percentage growth
with an explicit limitation while retaining amount comparisons.

Inputs remain exact decimal strings. New arithmetic uses a fixed 80-digit
Decimal context, not binary float coercion. Different structured supplier values
are compared exactly. Host-computed v3 comparison anchors use the existing
100-character anchor contract so repeating 80-digit results remain intact;
external supplier values retain the original 64-character parser, finite-value
and magnitude guards. A supplier discrepancy produces conflict; no tolerance
is guessed. Available official
same-period cells are additionally compared using their saved raw-cell precision.
Absent official rows are an explicit limitation, not a prerequisite for these
two structured questions. Multiple supplier wrappers do not establish source
independence. Conflicting observations retain conflict labels and provenance.

## Publication and compatibility

Every check and observation is recomputed from frozen V0, including its scope,
period, input hash, source IDs and method. Numeric catalog entries bind the
observation to its check ID, status, period and calculation version. Reader,
related evidence, explanations and Markdown share those saved observations.
Passing a structured subquestion can yield `evidence_sufficient` for that exact
binding; `economic_outcome` remains unresolved. It never passes the original full
cash bridge or changes the investment stance by itself.

V2 still recomputes exactly its original three checks. V1 retains its existing
saved-result read and challenge-validation policy. Legacy prompts retain their
original three check choices and hashes; new choices appear only under the new
identity policy. No historical record is rewritten. Reads perform no model/data
calls, and this policy adds no research call, source request or budget slot.
