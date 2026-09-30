# Explicit catalyst research trials

Status: Current

The local Web workbench supports `catalyst_v1` for A-share ordinary stocks in
`company_research` mode. Classic is the default for omitted profiles and for
the CLI. The classic graph facade explicitly rejects catalyst requests.

## Start a trial

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
| Price history | No qualified adapter for the default chain. Bounded Tencent qfq requires explicit vendor selection and verified PIT adjustment provenance; existing unverified provenance is rejected. Raw prices or current factors cannot qualify it. |

Unavailable/partial required capabilities cap priority at
`insufficient_information`. Source errors and truncated windows cannot prove
no events. This trial currently cannot establish a complete live research case
through the default price chain.

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
[wiring acceptance record](../superpowers/plans/2026-09-30-catalyst-wiring-acceptance.md).
