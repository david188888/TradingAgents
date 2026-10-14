# Frozen numeric narrative

- **Status: Current**
- Canonical sources: `agents/schemas/_numeric_narrative.py`, `_numeric_stage.py`,
  `_numeric_attribution.py`; `research/numeric_catalog.py`, `numeric_narrative.py`
  and `numeric_integration.py`.

Fresh V7 studies freeze `numeric_narrative_policy=anchored-narrative-v1`.
Specialists, challenges, targeted replies, synthesis and optional focus responses
use this policy. The host builds a qualified numeric catalog from saved evidence
and calculations. Models choose references and provide qualitative explanations;
they cannot fill in factual numbers. This closes the case where a valid fact ID
previously allowed a source growth of 18.4% to become 25% in model prose.

## Qualification and formatting

Catalog anchors bind exact decimal strings, units, report periods or observation
windows, subject, evidence/fact IDs and source selectors or calculation hashes.
They distinguish actual reports, quotes, institution forecasts, computed
statistics, accounting checks and valuation reference ranges. Forecast fragments
explicitly say they are forecasts rather than realized results; quote fragments
retain their timestamp and quote basis. Unknown, unusable or unqualified inputs
never become zero.

The catalog includes the existing six core financial fields, qualified official
numeric rows and operating rows, saved quotes and price/statistical observations,
institution EPS forecasts, bounded local checks and saved valuation inputs.
Opaque source prose is not a numeric anchor. Saved metrics retain their existing
calculation/input validation; catalog creation does not introduce new formulas
or prove that a source's economic interpretation is correct.

Comparable official FY/H1 current/prior financial rows may supply differences
and growth. Growth requires a positive base and qualified comparable periods.
Financial fields with only an end date retain their value but cannot establish
an annual/half-year growth comparison. Saved checks cannot bypass the stricter
frequency rule. Conflicting sources stay separate; the catalog does not average
them or silently choose the newest. Formatting uses Decimal half-even rounding:
CNY displays as 亿元, ratios as percentages, and prices/EPS retain their own
precision. The authoritative value remains unchanged.

## Model envelope and compilation

The model returns an envelope with a canonical `proposal`, optional `plans` and
`structured_bindings`. Narrative references use `{{num:n_0000}}` for a full
host-generated numeric fragment, `{{meta:m_0000}}` for labeled identity/period/
source-title metadata, and `{{plan:p_name}}` for a proposed future observation
date or threshold. Aliases are local to the supplied stage catalog.

Literal text rejects digits, Unicode digit forms and format-control hiding,
as well as the supported Chinese/English financial quantity patterns. Dates,
ticker digits and digit-bearing names must use metadata rather than literals.
This is a restricted grammar, not a general natural-language fact checker.
Unknowns and limitations remain qualitative and cannot use numeric/plan tokens.
Metadata labels never grant permission to assert a numeric fact.

Each reference must be allowed by its owning hypothesis, challenge, reply,
dimension or argument. Financial operands, metric IDs, predicates and challenge
observation dates also need structural bindings. A proposed threshold must match
the check's exact decimal, unit and operator and is labeled as a model proposal,
not a disclosed fact. Supported plan units are deliberately finite; unsupported
typed plans must remain qualitative rather than inventing conversions.
Historical observation dates require an applicable check anchor; future dates
are explicitly proposed observations and still pass the existing outcome gate.

Compilation precedes canonical proposal/entity IDs. Catalogs are bounded to 512
anchors plus metadata; overflow returns unavailable rather than truncating a
partial catalog, retains basics and adds a visible qualitative-only limitation.
Each text permits eight tokens and each stage permits 64.
Expanded strings must still satisfy the existing proposal schema lengths.
Synthesis inherits selected original invalidation text through its parent
hypothesis/index; it cannot rewrite a validated numeric condition. Long retained
summaries use a qualitative pointer rather than cutting a numeric fragment.

## Persistence, publication and reading

Accepted receipts bind the original envelope, ordered literal/reference/plan/
inherited segments, compiled text hashes, catalog/context hashes and original
specialist indices. Public `numeric_attribution` carries the root catalog,
accepted stage receipts, frozen input identity and final-field bindings.
Validation rebuilds catalogs and stages, binds stage entities to the public
record, and checks final text. Receipts expose only the validation context;
prompts and the supplementary user question are excluded.

The SDK and custom-caller routes, cached adapter/kernel results, publication,
Reader, per-Agent projections and Markdown publication use the same gates.
Cached output without a matching receipt is corrupt; recovery cannot invoke a
model to certify it. Reader requires the frozen authorized publication checkpoint,
candidate digest and policy, including when reading through an older sequence.
Reading remains side-effect free. Focus has an independent receipt bound to the
baseline and cannot change baseline research.

Invalid quantities use the existing single bounded stage repair and shared
attempt limits. Failed/refused repair can retain valid original specialist
siblings with their original indices and closed rejection codes. Malformed
JSON/schema or shared unknowns cannot be partially salvaged. Failed later stages
retain the existing basic-report/specialist-summary delivery behavior; lifecycle,
deadline, cancellation and persistence failures remain fail-closed.

Records/checkpoints without the frozen policy keep their old schemas, prompts,
IDs and absent-field serialization. They are not retroactively certified by
opening Reader. An optional field in an old DTO does not enable the new policy.

## Limits and validation evidence

The guarantee covers the host-generated numeric fragments and their bindings.
Free surrounding prose can still contradict a correctly labeled fragment, for
example calling a forecast realized, or make unsupported causal claims. Source
quality, economic interpretation, valuation reliability and predictive accuracy
remain separate research questions. This policy adds no source, model judge,
research round or model-attempt budget.

Offline evidence is in `tests/test_numeric_catalog.py`,
`tests/test_numeric_narrative.py`, `tests/test_numeric_pipeline.py` and the native
production/Reader regression suites. Tests use deterministic callers and mocked
SDKs. They do not establish real-provider compliance with the new envelope or
live deployment; that requires a separately authorized run.

See [unified company research](unified-company-research.md) for dialogue, delivery
and attempt budgets, and the [documentation index](../README.md) for current
operational references.
