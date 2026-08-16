---
name: sector-rotation-detector
description: Relate macro evidence and industry conditions to a sector view without overstating causal attribution, using an explicit cycle-stage and rotation-map prior.
roles:
  - news_analyst
triggers:
  - macro developments may affect sector leadership
  - industry rotation is relevant to company news
output_schema:
  - macro_driver
  - affected_sector
  - company_exposure
  - confidence
---

Identify only evidenced macro drivers, then explain the sector exposure and the
company-specific channel. Compare relative beneficiaries and losers where the
available data supports it. Treat policy headlines, commodity moves, and index
performance as inputs rather than proof of a durable rotation.

State the data window and confidence. Do not claim industry leadership or use a
sector statistic unless a supplied source supports the number and date.

## Cycle-stage and rotation prior (advisory heuristics)

This prior is a classification aid from public macro-rotation practice and
A-share convention; it is not evidence. Every cell you invoke must still be
supported by a dated indicator actually present in the run's data; otherwise
mark that leg unavailable and lower confidence.

### Cycle-stage indicator matrix

| Indicator | Recovery | Expansion | Overheat / stagflation | Contraction |
|---|---|---|---|---|
| GDP growth | bottoming, turning up | above trend | decelerating | clearly falling |
| Manufacturing PMI | back above 50 | sustained >51 | peaking, rolling over | below 50 |
| Social financing growth (社融) | accelerating | steady | slowing | policy-driven reacceleration |
| CPI | low | rising moderately | high | falling |
| PPI | bottoming | positive, widening | high | negative |
| LPR / policy rate | cuts begin | on hold | tightening | cuts begin |

Score the stage by counting matching indicators; a near-tie between two stages
means a transition — report both and lower confidence. China's cycle is heavily
policy-overlaid: name the current policy stance (easing, tightening, reform,
industrial-policy cycle) and treat it as a separate, dated input.

### Classic SW level-1 rotation map (heuristic prior)

- Recovery: overweight brokers/banks/real-estate/nonferrous/construction;
  underweight utilities, agriculture, defense.
- Expansion: overweight electronics/machinery/chemicals/nonferrous/auto;
  underweight utilities, real-estate.
- Overheat/stagflation: overweight coal/petrochemicals/agriculture/staples;
  underweight electronics/computers/brokers/real-estate.
- Contraction: overweight utilities/pharma/staples/high-dividend banks;
  underweight cyclicals, machinery, real-estate.

Use the map only to generate candidate exposures that you then check against
the company's actual revenue lines. Never quote historical sector excess-return
numbers unless a source in the run supplies them.

### A-share-specific drivers

Policy themes (import substitution, carbon neutrality, SOE reform, consumption
stimulus, infrastructure, property easing, AI/digital economy) can dominate
pure macro rotation; treat a theme as a driver only when a dated policy
document or data release is present. Fund-flow structure matters: northbound
money (consumer/pharma/financial tilt), public funds (high-conviction
clusters), margin financing (high-beta), insurance capital (high-dividend),
and national-team flows (index heavyweights) — cite the flow observation and
its window, not the stereotype.

Cross-asset checks (advisory): CNY direction, northbound net flows, treasury
yields, margin balances, copper and rebar prices can confirm or challenge a
rotation call; each check still needs a dated observation.

Sources: macro-rotation practice; finskills China-market sector-rotation
reference (Apache-2.0). A prior raises a hypothesis; only dated data in the run
can support it.
