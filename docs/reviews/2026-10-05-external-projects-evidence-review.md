# External project evidence review — 600803

Status: Historical

Do not use this document as evidence of current implementation behavior.
See [the documentation index](../README.md) for current-state references.

Reviewed on 2026-10-05 by three read-only subagents and consolidated against the
local [investigation](2026-10-05-low-cost-evidence-investigation.md) and
[proposed design](../superpowers/specs/2026-10-05-low-cost-evidence-design.md).
No external project was installed or executed. Tests were read, not run. One
free public Sina request for 600803 checked response shape; Phoenix pages were
read over ordinary HTTP. No model requests, production changes, saved-record
changes or Git publication were made.

## Decision from the research objective

The useful output is a traceable answer to a bounded company-research question,
not the largest number of endpoints or agents. A candidate helps this initiative
if it supplies a missing qualified operand, improves its interpretation without
inventing facts, or reduces fetch/model work while preserving reproducibility.
Provider identity, publication/quote/capture time, units and coverage still apply.
Different wrappers around one provider are not independent confirmation.

None of these projects supplies a ready-made fix for all three 600803 challenges.
Vibe-Research offers the strongest calculation/audit examples; vibe-astock offers
a useful closed-check pattern. TradingAgents-astock has practical missing-data
explanations and familiar endpoint helpers. Phoenix is a project discovery portal.
The current minimal-evidence design remains appropriate; no wholesale migration
or new model runtime is recommended.

## Pinned inspection and licenses

| Project | Inspected revision | License and scope |
| --- | --- | --- |
| [TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock/tree/b0594a4f2b8ff7c32807ebc9ec269007fffe895c) | `b0594a4f2b8ff7c32807ebc9ec269007fffe895c`, version 0.5.20 | [Apache-2.0](https://github.com/simonlin1212/TradingAgents-astock/blob/b0594a4f2b8ff7c32807ebc9ec269007fffe895c/LICENSE), upstream [NOTICE](https://github.com/simonlin1212/TradingAgents-astock/blob/b0594a4f2b8ff7c32807ebc9ec269007fffe895c/NOTICE) |
| [Vibe-Research](https://github.com/simonlin1212/Vibe-Research/tree/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3) | `85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3`, main on 2026-09-25 | [MIT](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/LICENSE); main differs from v1.2.0, so release test claims were not applied to main |
| [vibe-astock](https://github.com/simonlin1212/vibe-astock/tree/bd96df4045e7a4a68478862d18358139599fcf34) | `bd96df4045e7a4a68478862d18358139599fcf34`, version 1.1.3 | [Apache-2.0](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/LICENSE); some transplanted modules retain MIT and their own [NOTICE](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/backtest/NOTICE.md) |
| [Phoenix Tree AI](https://phoenixtree.ai/) | Public pages captured 2026-10-05 | No separate website source/license or independent data API found in the pages read; linked repositories have their own licenses |

## Fit to the three evidence questions

### Official report and operating disclosure

- TradingAgents-astock's inspected data layer has no qualified CNINFO PDF-body
  pipeline. Its [news helper](https://github.com/simonlin1212/TradingAgents-astock/blob/b0594a4f2b8ff7c32807ebc9ec269007fffe895c/tradingagents/dataflows/a_stock.py#L1396-L1459)
  is news search with bounded snippets.
- Vibe-Research's [announcement fetch](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/.agents/skills/data-access/scripts/fetch_announcements.py#L1-L8)
  intentionally returns titles and links. Its [PDF library](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/orchestrator/src/report_library.ts#L141-L186)
  really does parse uploaded text PDFs with page references, but does not qualify
  official issuer/security/report period or extract the required operating table.
- vibe-astock's [disclosure/announcement functions](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/vr/astock.py#L221-L250)
  are catalogue functions.

Therefore the local company-prefixed title, `公司代码` header and mixed H1/Q2
operating-table repairs remain necessary. PDF retrieval could support a future
upload library, but does not replace official document admission.

### Cash conversion and reported reconciliation

- TradingAgents-astock's [Sina helper](https://github.com/simonlin1212/TradingAgents-astock/blob/b0594a4f2b8ff7c32807ebc9ec269007fffe895c/tradingagents/dataflows/a_stock.py#L1166-L1211)
  expects `result.data[source_type]`. A request for 600803 cash flow returned
  HTTP 200 and success with `report_list`, `report_date`, `report_count`, but no
  `llb`. The real response plus source imply this helper would return an empty
  table; the external function itself was not executed. The local qualified
  Sina parser already handles `report_list`.
- Vibe-Research's [financial mapper](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/.agents/skills/data-access/scripts/sources/mappers_cn.py#L96-L129)
  supplies general financial-statement fields, not the complete note reconciling
  net income to CFO.
- vibe-astock's [financials](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/vr/astock.py#L299-L321)
  exposes a summary including per-share operating cash flow, not the bridge.

No inspected implementation deterministically extracts and reconciles the
current/prior H1 bridge and required working-capital adjustments. The official
note remains the source for that question. Explaining reported adjustments does
not prove their economic cause or future persistence.

### Peer valuation and dated institutional forecasts

The inspected industry-comparison helpers in all three repositories return
industry-board price rankings, not individual peers' PE/PB:
[TradingAgents-astock](https://github.com/simonlin1212/TradingAgents-astock/blob/b0594a4f2b8ff7c32807ebc9ec269007fffe895c/tradingagents/dataflows/a_stock.py#L2410-L2474),
[Vibe-Research](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/.agents/skills/data-access/scripts/sources/eastmoney.py#L195-L202),
[vibe-astock](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/vr/astock.py#L863-L882).

Vibe-Research's [EastMoney EPS path](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/.agents/skills/data-access/scripts/fetch_estimates.py#L30-L138)
retains institution/report date, which is useful, but derives forecast year from
publication year rather than explicit `currentYear`. Its THS aggregate does not
retain individual report dates or cross-provider institution deduplication.
vibe-astock's [forward valuation](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/vr/astock.py#L372-L424)
hardcodes 2026/2027 and accepts undated annual averages. TradingAgents-astock also
uses aggregate/positional EPS extraction. None is safe to copy unchanged.

Continue the proposed dated-institution rows and explicit years, 180-day cutoff,
cross-provider deduplication and same-session Tencent peer qualification. The
existing local THS/reportapi adapters and inspected a-stock-data/AKShare endpoint
references already cover the underlying suppliers; no new independent A-share
source family was established by this review.

## Adopt, adapt, defer

| Decision | Useful implementation | Local application and boundary |
| --- | --- | --- |
| Adapt | Vibe-Research [required/optional stage validation](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/orchestrator/src/validator.ts#L220-L274) | Define minimum operands per question; optional missing data remains a limitation. Stage success is not economic-risk resolution. |
| Adapt | Vibe-Research [calculation IDs](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/calc/cli.py#L258-L280) and [recomputation](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/orchestrator/src/validator.ts#L609-L638) | Use frozen evidence IDs, input hashes and calculation versions; test altered inputs/results/display/outcomes. Retain local Decimal/disclosed precision and qualification gates. |
| Adapt | vibe-astock [closed verification menu](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/duanxian/verification.py#L41-L146) and [frozen numeric catalogue](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/review_agent/grounding.py#L65-L132) | Model chooses a declared question; code fixes operands, labels and outcomes. Do not import short-term market thresholds into company fundamentals. |
| Adapt | Vibe-Research [fetch ledger integrity](https://github.com/simonlin1212/Vibe-Research/blob/85ba57191ba28cb9b4eeb4f7c1ed006d58d999c3/orchestrator/src/validator.ts#L131-L197), vibe-astock [revision cache](https://github.com/simonlin1212/vibe-astock/blob/bd96df4045e7a4a68478862d18358139599fcf34/duanxian/cache_policy.py#L10-L35) | Borrow audit cases and retained observations. Keep native durable capability ownership, source/parser-version keys and immutable prior runs; do not update reports at read time. |
| Adapt | TradingAgents-astock [missing-data explanation](https://github.com/simonlin1212/TradingAgents-astock/blob/b0594a4f2b8ff7c32807ebc9ec269007fffe895c/web/components/report_viewer.py#L98-L147) | Explain that new data requires a new analysis. Do not copy its mutation of a saved missing-data snapshot. |
| Defer | Vibe-Research uploaded-PDF search, SEC/RSS/industry signals, local subscription agents | Valuable for separately scoped capabilities; unnecessary for these three company questions. Subscription quotas/time remain costs, and no runtime migration was authorized. |
| Reject for this scope | Entire agent graphs, prose-length quality gates, undated forecasts, missing-to-zero coercion and read-time historical re-evaluation | They do not satisfy the local budget, point-in-time, bounded-check or old-record contracts. |

## Phoenix and verification limits

Phoenix's [privacy page](https://phoenixtree.ai/privacy/) identifies it as a static
company/product site, not a hosted research service. Its [open-source page](https://phoenixtree.ai/open-source/)
links product/data repositories. The [research-system page](https://phoenixtree.ai/research-system/)
describes the two products as separately running today; automatic research-loop
integration is a future direction. The AStock product page points to an older
development revision, so current ability was checked against pinned source.
Browser-search open errors did not establish site unavailability: ordinary HTTP
successfully returned the pages.

The review established actual code paths, not production readiness or successful
600803 runs in those projects. Author-reported test counts, endpoint counts and
release notes are not independent acceptance. Vibe-Research's broader catalogue
has 117 enabled endpoints over 30 layers, but endpoint count is not provider
count or coverage of this company. Public-interface access does not by itself
grant redistribution rights; any later substantive code copying must retain
the applicable license/attribution.

Detailed temporary source copies are under `/private/tmp/ta-external-review/`.
The single Sina response is under
`tradingagents-astock-probes/sina-600803-cashflow.json` in that directory.
This review adds design references only; low-cost v5 implementation and its
600803 Web/HTML acceptance remain pending.
