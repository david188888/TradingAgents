---
name: financial-statement-analyzer
description: Ground a fundamental view in cash flow, profitability quality, leverage, and explicit red flags, using decomposable quantitative heuristics where statement inputs exist.
roles:
  - fundamentals_analyst
triggers:
  - financial statements are available
  - profitability or governance quality needs assessment
output_schema:
  - dupont_components
  - earnings_quality
  - balance_sheet_risk
  - cash_conversion
  - red_flags
  - price_driven_share
  - inventory_signal
  - off_bs_risk
---

Start from reported figures, not narrative. Reconcile revenue, operating profit,
net income, operating cash flow, free cash flow, debt, and working capital.
Explain material changes with dated evidence. Distinguish sustainable operating
improvement from one-off gains, accounting changes, or balance-sheet financing.

Report a compact scorecard: profitability quality, cash conversion, leverage and
liquidity, working-capital direction, and governance or accounting red flags.
If a metric cannot be computed from the available statements, mark it unavailable
rather than estimating it. Do not make a price target from this method alone.

## Methodology reference (advisory heuristics)

The formulas below are deterministic decompositions; the thresholds are
advisory heuristics from public literature and A-share analyst convention, not
evidence. Compute a metric only when every input is present in verified
statements; otherwise report it as unavailable. Cite the statement period for
each computed value, and never present a heuristic threshold as an observed
fact about the company.

### Five-factor DuPont decomposition

```
ROE = (net income / pretax income)          # tax burden
    x (pretax income / EBIT)                # interest burden
    x (EBIT / revenue)                      # operating margin
    x (revenue / total assets)              # asset turnover
    x (total assets / equity)               # equity multiplier
```

Track each factor across available periods. A flat ROE whose support shifts
from margins toward leverage is a deterioration signal, not stability.

### Earnings-quality screens

| Screen | Formula | Advisory threshold |
|---|---|---|
| Accrual ratio | (Δ current assets − Δ cash − Δ current liabilities + Δ short-term debt − D&A) / average total assets | >10% of assets: investigate; >15%: low quality |
| Cash conversion | operating cash flow / net income | <0.8 for 3+ consecutive years: major red flag |
| Receivables growth | Δ accounts receivable vs Δ revenue | receivables growth >1.5x revenue growth: red flag |
| Contract liabilities | trend of advances/deferred revenue | sustained decline while revenue grows: possible pull-forward |
| Non-recurring gap | net income vs net income excl. non-recurring items (扣非) | recurring large gaps, or negative 扣非 with positive net income |
| Government subsidy reliance | subsidies / net income | >30%: sustainability question |

### Distress and manipulation screens

- Altman Z (manufacturing calibration, Altman 1968):
  `Z = 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MVE/TL + 1.0·Revenue/TA`.
  Advisory bands: >2.99 safe, 1.81–2.99 grey, <1.81 distress. State which
  inputs were unavailable rather than improvising proxies.
- Piotroski F-score (2000): nine binary signals (positive ROA and operating
  cash flow, improving ROA, OCF exceeding net income, falling long-term
  leverage ratio, improving current ratio, no share dilution, improving gross
  margin, improving asset turnover). Report the count and which signals were
  computable.
- Beneish M (1999) needs granular notes data; treat as unavailable unless the
  statement bundle actually carries the required line items.

### Price-vs-volume decomposition (cyclical / commodity exposure)

For companies whose revenue tracks a commodity or commodity-like price,
decompose revenue growth into price and volume contributions before calling
the growth high-quality. If volume data is unavailable from the statements,
report the split as indeterminate rather than inferring volume from revenue
alone. All thresholds below are advisory heuristics:

| Screen | Formula | Advisory signal |
|---|---|---|
| Price-driven share | revenue growth split into volume (units/shipments/production) vs realized price | growth mostly price-driven with volume flat or down: late-cycle marker, not durable quality |
| Gross-margin percentile | current gross margin vs its own 5-year distribution | ≥90th percentile: extreme-profit zone; low PE(TTM) at this point reflects the market pricing mean reversion, not cheapness |
| Sequential margin inflection | first quarter-over-quarter gross-margin decline after an extreme run | the first sequential decline is itself a downgrade signal even when the absolute margin is at a record high |
| Inventory-to-revenue | inventory / trailing-twelve-month revenue | >0.5 with inventory roughly doubling year over year: hoarding risk (a price decline hits impairment and demand at the same time), even when headline revenue growth appears to justify the inventory |

### A-share red-flag checklist

Financial: revenue growth with persistently negative operating cash flow;
inventory growth far outpacing cost of sales; construction in progress
(在建工程) not transferring to fixed assets over long periods; abnormally
large other receivables (possible related-party fund occupation); high
commercial-acceptance-bill share in receivables; goodwill above 40% of net
assets (20–40%: monitor; also flag profit-commitment (对赌) periods about to
expire); sudden large impairments after a clean streak (potential big-bath);
recurring same-direction accounting-estimate changes; excessive R&D
capitalization ratio.

Governance: auditor change or qualified opinion; frequent CFO turnover;
financial restatements; exchange inquiry letters (问询函); high controlling
shareholder pledge ratios; buybacks running in parallel with insider selling;
independent directors dissenting; CSRC investigation; opaque related-party
transaction pricing.

Also screen off-balance-sheet exposure when disclosures allow: major
long-term lease commitments signed but not yet commenced, SPV or
industrial-fund capital commitments carrying make-up / bottom-line (兜底)
obligations, external guarantees, controlling-shareholder pledges, pending
litigation, and wealth-management or asset-management product investments.
Liability forms evolve: risk does not disappear, it migrates from the
visible balance sheet into the notes. When the combined notional of lease
commitments, SPV make-up obligations, and external guarantees exceeds 50%
of net assets, escalate to a manual cash-flow sustainability review
(advisory threshold; compute only from disclosed figures, otherwise mark
unavailable).

Sources: DuPont decomposition; Altman (1968); Piotroski (2000); Beneish (1999);
A-share conventions adapted from the finskills China-market methodology
reference (Apache-2.0). These are reasoning aids, not verified facts.
