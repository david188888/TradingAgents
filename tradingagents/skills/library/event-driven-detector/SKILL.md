---
name: event-driven-detector
description: Classify A-share corporate events, distinguish confirmed facts from rumors, and give each event an explicit status, economic channel, and next verification point.
roles:
  - news_analyst
triggers:
  - corporate action, regulatory filing, or capital-markets event appears
  - event timing may affect the investment case
output_schema:
  - event_type
  - status
  - materiality
  - next_verification
---

Classify events such as earnings, buybacks, shareholder changes, asset injections,
lock-up expiries, index changes, restructurings, regulatory actions, and major
contracts. Record source, date, status (confirmed, scheduled, reported, or
rumor), expected timing, and the specific economic channel.

Do not assume completion from an announcement. Highlight approval conditions,
counterparty risk, dilution, lock-up supply, and regulatory dependencies. If an
event cannot be sourced, describe it as unverified and do not use it as a core
thesis premise.

## A-share event taxonomy (advisory reference)

Use these categories to normalize what you observe; the taxonomy is a
classification aid, not evidence about any company.

| Event type | What to verify | Typical failure modes |
|---|---|---|
| Major asset restructuring (重大资产重组) | Board plan, shareholder vote, CSRC registration/approval; consideration mix (cash vs shares); profit commitments (业绩承诺) | Vote failure, approval rejection, aggressive commitments, dilution from share consideration and matching fundraising |
| Asset injection / SOE reform (资产注入/国企改革) | Group commitment timeline, whether pledged assets are profitable, securitization headroom | Commitments repeatedly deferred; injected asset quality unverified |
| Buybacks (回购) | Stated purpose: cancellation (share-count reduction) vs employee-incentive repo; funding source; execution progress vs announced size; window-period compliance | Announced but slowly executed; incentive-linked repos dilute; borrowed-money buybacks |
| Controlling-shareholder / management purchases (增持) | Who buys (controller vs financial holder), amount, method (auction vs block trade), repetition, any offsetting sales | Block trades with hedging arrangements; token amounts; pledge-maintenance buying |
| Spin-off listing (分拆上市) | Parent listing age and profitability history, subsidiary profit share, independence, board approval stage | Conditions unmet; timeline slip; subsidiary valuation assumption |
| Index adjustment (指数调整) | Announcement date vs effective date, passive-tracking scale, whether inclusion or deletion | Front-running flows before effective date; one-off mechanical demand |
| Lock-up expiry (解禁) | Unlock size vs total shares, holder type (financial investor vs controlling shareholder), cost basis vs current price, any announced reduction plan (减持计划) | Financial investors exiting; weak-market amplification; rule-based selling windows |
| Regulatory actions (监管/问询) | Inquiry letters, investigations, penalties: exact scope and current stage | Escalation from inquiry to formal investigation |

For every classified event, state: status (confirmed / scheduled / reported /
rumor), the dated source, the economic transmission channel to revenue, cost,
capital, or share count, and the next concrete verification point (a filing, a
vote, an effective date, or a disclosure that would confirm or break the event).

Reduction-rule context (advisory): controlling shareholders selling via
centralized bidding are capped around 1% of shares per 3 months and block
trades around 2% with a 6-month lock for the buyer; selling is restricted
below issuance price or book value and for dividend non-compliers. Use these
as context for feasibility, never as a substitute for the actual announcement.

Do not convert any event into an expected return, position size, or trade.
Sources: A-share disclosure conventions; finskills China-market event
framework reference (Apache-2.0).
