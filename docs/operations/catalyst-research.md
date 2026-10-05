# Explicit catalyst research trials

Status: Legacy recovery reference

New Web research uses `evidence_v1`; see [Web research](evidence-research.md).
`catalyst_v1` records remain readable and interrupted runs recover using their
saved identities and budgets. Creation and fresh retry return
`410 research_profile_retired`, regardless of the old enable flag. The sections
below describe the retained workflow for recovery, rather than a current creation
entry point. CLI analysis is outside continued maintenance.

## Historical trial setup

Keep existing LLM/data credentials in ignored local configuration. Enable the
server process, then select the catalyst workflow:

```bash
TRADINGAGENTS_CATALYST_PROFILE_ENABLED=1 tradingagents web --port 8765 --open
```

Enter company code, research cutoff and optional question. The outlook is the
next 84 calendar days, separate from historical lookback. Evidence must have
been knowable at the cutoff. The question is trimmed, limited to 400 Unicode
code points, persisted in run identity and included in model prompts and the
case. Classic rejects a nonempty catalyst question.

Catalyst does not submit classic role, debate-depth, holding-review or horizon
selections. Required legacy wire fields use canonical compatibility defaults.
Output language and model selections remain effective: the three specialists
and refutation use quick, synthesis uses deep.

## Sources and qualification

Only adapters whose actual network dispatch can be charged enter this profile.
Configured category/tool selection is respected; unselected sources are never
substituted. Opaque SDK fallbacks are unavailable here.

| Capability | Bounded adapter and admission rule |
| --- | --- |
| Security identity | Tushare REST `stock_basic`; exact code, unique identity and listing date at/before cutoff. Current company name is not historical identity evidence. |
| Event coverage | CNINFO direct transport, 90-day publication lookback with bounded pagination; only proven complete coverage qualifies. Each filing cites its own source record. Publication date is not inferred to be occurrence date. |
| Fundamentals | Tushare REST income, balance sheet and cash flow; consolidated statements, publication/final-publication and reporting dates at/before cutoff, eight distinct periods per statement. Fewer periods are partial. Credentials do not prove API entitlement. |
| Price history | Direct Tushare REST `trade_cal`, `daily` and `adj_factor` is admitted when explicitly present in the configured chain. All calendar dates, settled sessions, security codes, OHLC and dated factors are checked. OHLC is scaled to the last price session's factor. Only capture on the research-cutoff date can qualify without an archive vintage; retrospective factors remain unverified. Tencent qfq still needs explicit selection and verified PIT provenance; existing unverified provenance is rejected. |

Unavailable/partial required capabilities cap priority at
`insufficient_information`. Source errors and truncated windows cannot prove
no events. A cutoff anchor alone cannot qualify historical factor vintage.
Missing price sessions, including possible suspensions, are recorded without
filling prices or asserting their cause. The first explicitly selected bounded
price adapter is used; opaque Wind CLI/SDK paths are recorded as unsupported
for this profile, even though classic can use Wind. An explicit Wind-only
selection cannot silently call Tushare prices.

Qualifying Tushare price evidence includes code-computed volatility, signed
daily historical VaR/ES, observed maximum drawdown and Wilder ATR when their
own inputs/sample limits permit. Missing a qualified benchmark leaves beta
unavailable without suppressing single-security statistics. The input hash,
calculation versions, adjustment anchor and limitations are frozen with the
source payload and checkpointed before specialist dispatch. The market
specialist reads this saved payload; a dedicated homepage metrics projection
is not yet part of the published case. See [local price statistics](../contracts/local-price-statistics.md).

## Budget, cancellation and recovery

Permissions are persisted before dispatch. SDK retries and redirects are
disabled. The stricter ledger/policy limits apply: five main calls, two semantic
preprocessing calls, two structured repairs (one per stage), three network
retries, twelve model attempts total, twenty-four capability calls and sixty-four
HTTP attempts. At most one supplement round covers three capabilities.
Pagination consumes HTTP attempts. Model/data concurrency is two each across
runs. Active execution defaults to 300 seconds, excluding queue time; timeout
prohibits late publication.

Stage/attempt checkpoints are always persisted in the run store, even when the
classic checkpoint toggle is disabled. Interruption can resume the same run
after validating profile, policy, question, ticker, cutoff, workflow/config
identity and artifact integrity. Saved results are reused; uncertain dispatched
calls remain spent, and a repeated main task requires network-retry allowance.
Resume cannot promise remote billing exactly once. Absent usage stays unknown.

Accepted cancellation is terminal; start a new run or retry. Interrupted runs
can resume. Cancellation and publication authorization share a lifecycle lock:
cancellation first prevents the artifact; authorization first durably records
the candidate's right to publish and a late cancel receives conflict. Recovery
after that barrier only finishes publication/reporting.

## Read a result

The four stage statuses derive from committed durable records. Failures and
source gaps remain visible. A terminal run without a committed case has no
research conclusion. `GET /api/runs/{id}/catalyst` returns `ready`, `unavailable`
or `unsupported`; `ready` only means readable. Inspect completeness, quality,
priority and limitations independently.

First screen, details, evidence drawer and Markdown report read the same case.
Refresh, SSE replay/reconnect and artifact/projection reads perform no model or
data calls. After a page reload, select the saved run from history. Reports
remain in the run's `reports/` directory in the local durable store.

See [architecture](../../ARCHITECTURE.md) for ownership and default paths.
Verification history and research-quality decisions belong in the
[wiring acceptance record](../archive/reviews/2026-09-30-catalyst-wiring-acceptance.md).

New case publication also emits an additive
[shared research record](../contracts/research-record.md). The Reader presents
up to four saved price-statistic cards below the brief, with ES/Beta and method
details expandable. Citation drawers resolve saved claims/challenges to all
their directly cited sources and show admitted source content before metadata.
Missing original bodies remain missing; model dispositions never become
executed verification. This integration does not change the existing catalyst
workflow, default profile or data-qualification rules.
