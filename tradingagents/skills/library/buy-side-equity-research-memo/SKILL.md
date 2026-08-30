---
name: buy-side-equity-research-memo
description: Turn research into a falsifiable portfolio memo with base, upside, downside, catalysts, and monitoring conditions.
roles:
  - portfolio_manager
triggers:
  - final portfolio decision requires a concise investment memo
  - risk debate and research need a decision-ready synthesis
output_schema:
  - thesis
  - scenarios
  - reverse_case
  - risk_asymmetry
  - catalysts
  - monitoring
---

Lead with the decision and the evidence that changes it. Describe base, upside,
and downside scenarios with stated assumptions; include the strongest reverse
case and the observation that would invalidate the thesis. Identify dated
catalysts and monitoring metrics, with data limitations visible.

This method does not override deterministic portfolio constraints. A suggested
order must remain within the legal action set supplied by the system; when no
action is available, state Hold rather than implying an executable trade.

## Risk asymmetry assessment (advisory)

Close the memo by stating which side risk is asymmetric toward, derived from
the scenarios and the strongest reverse case rather than from a date or a
price level. Cite independent supporting observations (e.g., late-cycle
signals from fundamentals: extreme margins with compressed PE, price-driven
revenue, inventory hoarding, dense long-agreements, debt-funded demand).
When multiple independent such signals coexist, say the asymmetry has
deteriorated and lean conservative, even though the turning point itself is
not predictable. Never output a specific turning-point date or drawdown
target as a conclusion.
