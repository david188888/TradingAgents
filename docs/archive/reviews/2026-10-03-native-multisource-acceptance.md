# Native multi-source routing acceptance — 2026-10-03

Status: Historical

Do not use this document as evidence of current implementation behavior.

归档日期：2026-10-04。正文保留编写时的设计、结果和未完成事项；归档不表示全部目标已验收。当前行为与仍待推进的计划见[文档索引](../../README.md)。

## Delivered scope

New `evidence_v1` company/catalyst/holding runs share `NativeSources` with public
identity, financial, calendar and price candidates before Tushare backup.
Classic remains default; old catalyst sourcing remains unchanged. Native
overrides/exclusions are separate from legacy vendor keys. Tables fall back
individually, preserving separate source families and same-family C1 checks.
Source attempts and safe typed failures are durable. Budget, cancellation and
checkpoint faults cannot become provider fallback. Workflow v1 recovery keeps
the original collector or saved V0; v2 uses the new topology.

The Tencent raw request needed its empty sixth adjustment field: without the
trailing comma its successful HTTP response contained no raw day series.
Sina financial admission uses original CNY yuan values, actual publication
dates, consolidated scope and update timestamps. This new path does not reuse
the legacy text adapter's monetary scaling. Tencent raw/Sina dated divisors
are normalized at the settled cutoff with complete SZSE session coverage.
Unarchived retrospective factors and a missing benchmark remain unavailable.

## Live 002130 trial

Local branch: `codex/research-data-integration-20261002`. Run store is isolated
under `/tmp/tradingagents-002130-live-20261003/runs`; probes and browser evidence
are under `/tmp/tradingagents-002130-multisource-20261003`. These are test data,
not committed reports, and do not replace the user's regular run store.

First run `run_20261003T084124163705Z_09b1f4a2` admitted 94 facts with all four
source capabilities qualified, then failed the specialist reference guard.
The event specialist fabricated two fact IDs. Three paid model dispatches were
saved; this failed run and its checkpoint were retained. No invalid inference
was promoted to a report. The adapter now checks specialist fact membership
before caching and can use the existing one structural repair allowance;
kernel reference guards and budgets were not relaxed.

Second run `run_20261003T084646362285Z_0c3b12bc` completed with:

- Sina labelled identity after EastMoney transport failure; CNINFO official
  disclosure coverage; eight periods in each Sina financial table; Tencent raw
  daily OHLC and dated Sina divisors qualified against SZSE's calendar.
- 335 bars from 2025-05-21 to the last settled session, 2026-09-30. The research
  cutoff is 2026-10-03; the calendar explicitly covers the intervening closure.
- 94 facts, seven hypotheses, three unresolved economic challenges and one
  numeric predicate check. Five MAIN model dispatches, zero model repairs or
  Tushare requests; 28 observed data HTTP attempts and 11 data capability calls
  including the condition verification.
- Annualized volatility 48.55%, historical daily 5% quantile -4.72%, ES -6.55%,
  maximum observed drawdown -55.00%, ATR(14) about 0.5263 CNY/share. Beta remains
  unavailable because no qualified benchmark was supplied. These are script
  results, not an intrinsic value interval or a future-loss bound.
- Final assessment `partial / LOW_CONFIDENCE`. Qualified numeric fields do not
  replace announcement bodies, operating detail, valuation inputs or resolved
  economic challenges. This establishes a working integration, not predictive
  accuracy or research adequacy.

Reader API bytes were identical on repeated reads and the checkpoint remained
unchanged. Saved Markdown contains the same judgement. Browser-harness opened
the exact second run in normal desktop Chrome, expanded financial source
fields, and confirmed the quantitative overview. At 390×844 its root scroll
width remained 390. Jev independently opened the same run in two actions
(1,751 ms), then DOM verification confirmed the exact run ID, judgement and
48.55% statistic. Jev used a 1120×1900 viewport so history was visible; this
does not prove nested-scroll support. Its owned tab was closed on exit.

## Checks and remaining limitations

Focused source/native/model/verification/price/report/public-wiring checks:
295 passed, including public families in all three research modes, same-run
rate cooling, independent financial fallback, old topology recovery and typed
failure replay without repeated transport. Final runner control handling also
received a focused public-wiring rerun. Ruff, agent-doc checks and diff checks
passed. Frontend source did not change, so no generated assets were rewritten.

Full offline suite before the final two regression additions: 2,974 passed,
12 failed, five deselected and 73 subtests passed. The failure categories match
the [existing integration baseline](2026-10-02-research-data-integration-acceptance.md):
three classic graph prefetch expectations, one historical-date text fixture,
three runtime v2 descriptor/identity expectations, two methodology field
fixtures and three Web CLI log-permission failures. Full pytest is not green.

Remaining reader/analysis work: specialist unknowns describe their isolated
views, and can sound like global data absence; label their scope before using
them as a global coverage summary. Some available-dimension limitations also
repeat generic missing-input codes. Retain these observed limitations rather
than treating the report as fully polished. Next useful data work is official
body/operating-detail admission and qualified benchmark/valuation inputs.

No push, PR, merge or default-profile migration was performed.
