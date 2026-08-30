---
name: juglar-cycle-stock-stage
description: Classify the business cycle with explicit evidence and uncertainty instead of a single deterministic label.
roles:
  - fundamentals_analyst
triggers:
  - company results need macro-cycle context
  - China market or industry-cycle exposure is material
output_schema:
  - cycle_evidence
  - likely_stage
  - alternative_stage
  - confidence
  - top_signals
---

Separate observed facts from the cycle interpretation. Consider demand, capacity,
inventory, margins, credit conditions, capital expenditure, pricing, employment,
and policy only when evidence is available. State the most likely stage and a
plausible alternative, then name the observations that would falsify the view.

Use a cycle label only as context for the company analysis; it is not a trading
signal by itself. Missing China-specific data must reduce confidence, not be
filled with assumptions from another market.

## Late-cycle feature checklist (advisory heuristics)

When evidence supports a late-stage reading, check each feature independently
and report only the ones observable in verified data:

- Extreme-profit/low-PE pairing: gross or net margin at a multi-year high
  percentile while PE(TTM) sits at a multi-year low percentile. The market is
  pricing profit as unsustainable; low PE here is not cheapness.
- Price-vs-volume split: revenue growth driven mainly by price rather than
  volume. A first sequential gross-margin decline after an extreme run is
  itself a signal, even at absolute highs.
- Inventory/hoarding expansion: inventory or construction-in-progress growing
  far faster than revenue (channel hoarding analogue).
- Long-agreement density: dense long-term take-or-pay or capacity-lock
  agreements disclosed near the optimism peak. Treat as risk accumulation,
  not demand certainty.
- Debt-funded demand: concentrated buyers whose capex is funded by debt or
  new financing rather than operating cash flow (capex/OCF near 100%,
  negative free cash flow at the buyers).

Report `top_signals` as the list of observed features with dated evidence, and
name the features that could not be computed. These features indicate the
asymmetry of risk, not a timing forecast: the transition from shortage to
glut is often abrupt, so never present a specific turning-point date.
