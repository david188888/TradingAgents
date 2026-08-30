---
name: sentiment-reality-gap
description: Compare market narratives with sourced operating facts and make divergence a conditional risk signal.
roles:
  - sentiment_analyst
triggers:
  - retail or news sentiment differs from reported fundamentals
  - social data quality requires confidence calibration
output_schema:
  - narrative
  - reality_check
  - divergence
  - confidence
---

Summarize the observed narrative by source, sample size, and time window. Compare
it with verified operating and financial facts only when those facts are present.
Classify divergence as temporary, structural, or indeterminate, and name the
future observation that would resolve it.

Sentiment is neither a vote nor a price target. Thin, unavailable, or
single-platform data lowers confidence. Never invent community activity or
substitute an unsourced claim for a missing A-share sentiment measure.

Two additional reality checks, both evidence-disciplined:

- Silence as a signal: when a company omits or dodges key operating
  disclosures (capacity utilization, order visibility, inventory mix, major
  customer changes), treat the absence as a negative prior and keep
  confidence low until an independent source corroborates. Name what is
  missing instead of filling the gap with assumptions.
- Claims versus verifiable delivery: compare announced capacity, order
  books, or capacity/megawatt targets with completed, dated, independently
  verifiable project evidence. Announced figures never substitute for
  delivered ones; flag the gap explicitly when they diverge.
