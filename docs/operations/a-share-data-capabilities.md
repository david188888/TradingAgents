# A-share data capabilities

Status: Current

This reference distinguishes the maintained native evidence chain from retained classic tools.
Providers supply material; code determines identity, dates, units, scope, coverage and usability.
A source failure never proves no event occurred. Source routes are not investment conclusions.

## Native sources

[native_sources.py](../../tradingagents/dataflows/native_sources.py),
[native_valuation.py](../../tradingagents/dataflows/native_valuation.py),
[minimum_sources.py](../../tradingagents/dataflows/minimum_sources.py) and the V8
[search extension](../../tradingagents/dataflows/search_sources.py) own collection and admission.

| Capability | Dedicated default candidates and boundary |
| --- | --- |
| Security identity | EastMoney exact profile → labelled Sina profile → Tushare `stock_basic`; exact security/exchange and listing-date qualification. |
| Company introduction | Identity-verified, explicitly labelled profile fields; an admitted official main-business excerpt can supply fallback. Business scope is not automatically main business. |
| Financial tables | Sina direct income/balance/cashflow → Tushare independently per failed table; consolidated CNY fields with actual disclosure dates. |
| Calendar | Official SZSE month grid → Tencent index-derived dates → Tushare last fallback; crosschecks described below. |
| Adjusted prices | Tencent raw bars with dated Sina divisors → Tushare bars/factors; settled window, anchor, vintage and OHLC qualification. |
| Disclosures | CNINFO official listing/query and bounded qualified documents; titles, selected bodies and numerical rows have distinct coverage. |
| Valuation | Dated Tencent snapshot and optional Tushare `daily_basic` history; source capture does not prove archived PIT availability. |
| Forecast/industry context | Dated THS institution EPS, EastMoney fallback; EastMoney industry candidates plus same-session Tencent quotes. Limited samples are not full consensus or assured business comparables. |

DeepSeek/Tavily search discovers dated news, industry, policy and competition, and attempts only
missing dedicated fields. Snippets are discovery aids. Search qualification, field recovery,
immutable revisions and shared budgets follow the [research contract](../contracts/research-record.md).
Unsupported layouts or incomplete price/valuation inputs stay unavailable, even when a page was found.

Programmatic `effective_config.evidence_source_vendors` orders native candidate subsets by capability;
empty disables that capability. `evidence_source_exclusions` removes vendors afterward. These keys
freeze into checkpoint identity. Legacy `data_vendors`/`tool_vendors` do not configure the native chain.
The browser has no arbitrary source-policy editor. Provider attempts/selection retain safe provenance;
a Tushare rate-limit rejection suppresses further Tushare attempts within that run.

## Native calendar and price qualification

A missing K-line does not prove a holiday. The complete official SZSE month calendar is authoritative
for Shanghai, Shenzhen and Beijing securities. Tencent SSE-composite bar dates witness settled days;
index price values do not become company evidence. Unavailable witnesses retain the official calendar
with degradation rather than silently switching its meaning.

When the witness disagrees, TDX daily-package existence can adjudicate disputed dates. Two independent
witnesses contradicting the official calendar reject it, not invite Tushare voting. When SZSE is
unavailable, Tencent-derived settled weekday gaps need TDX closed-day confirmation. An old package's
404 counts only when a known earlier trading-day package remains retrievable. Unknown gaps stay
unavailable; an unexplained missing stock session cannot be filled or labelled suspension.

Public adjustment applies dated Sina divisors to OHLC and reanchors to the last settled price session.
Generic Tencent qfq and a historical cutoff alone do not prove factor vintage. A current-day
unsettled valuation snapshot retains its timezone-aware quote/capture timestamps; peer quotes must
match the target's actual session. Valuation history, forecasts and price statistics keep their own
qualified windows; none manufactures a fair-value anchor or forecasts future risk.

## Statements, documents and coverage

Qualified statement tables preserve source families and survive unrelated table failures. Six core
financial fields and separate eleven-field detail records have distinct roles; adding detail must
not silently change frozen comparisons or valuation inputs. Same-period checks cannot mix cells from
different suppliers, consolidated/parent-attributable income or incompatible reporting frequencies.

Official PDFs have bounded downloads, parsing and excerpts. Scanned, encrypted, wrong-issuer,
future, ambiguous-column or unsupported layouts remain unavailable; no OCR/model numbers are guessed.
Selected excerpts are partial body coverage. A passed structured profit/CFO comparison is distinct
from a complete reported cash bridge. Empty disclosed cells stay missing rather than zero.

[coverage.py](../../tradingagents/dataflows/coverage.py) owns source coverage semantics.
Screening-capable adapters can report a complete zero-result search only with proven pagination and
scope; unavailable/partial/unknown cannot become “nothing happened”. Classic screening tools use
`CoveredText`/`ScreeningCoverageV1`; other capability types retain their own constraints.

## Installation and TDX boundary

```bash
conda activate tradingagents
python -m pip install -e ".[china,web]" --index-url https://pypi.org/simple
python -m pip check
```

The default china extra includes PDF/spreadsheet parsers, AKShare, baostock and Tushare, but excludes
mootdx. mootdx 0.11.x's httpx/tenacity constraints conflict with the maintained Web/model stack;
do not force it in with `--no-deps`. If `pip check` identifies that conflict in an old installation,
remove the conflicting mootdx SDK and reinstall the supported combination. Keep user data intact.
Adapter/legacy routing remains; SDK absence/import failure yields typed unavailability, not no data.
TDX package HEAD witnesses in the native calendar do not require the mootdx SDK.

For clean resolution diagnostics use `pip install --dry-run --ignore-installed -e ".[china,web]"`.
That checks dependency resolution rather than only metadata; it does not install the project.

## Supplemental tools and known limits

Classic supplemental capabilities are registered in [registry.py](../../tradingagents/dataflows/registry.py)
and exposed through [data_meta_tools.py](../../tradingagents/agents/utils/data_meta_tools.py).
Adding an adapter does not automatically admit it into native research.

- EastMoney datacenter screening validates response code, stable pagination/counts and returned filters.
  push2/push2ex tools are separate: several still have single-page/response-shape gaps; an empty table
  from them cannot prove complete absence. See source-specific adapters before using negative findings.
- baostock valuation/listing/chip tools reject unsupported Beijing segments. Chip distribution is a
  local advisory heuristic, not observed holdings. The shared session bounds socket waits.
- Interactive Q&A and exchange announcement tools have exchange-specific scope; do not substitute
  investor questions for institution-survey records, or nonofficial fallback for official coverage.
- Latest-only supplemental tools do not gain historical validity from an `as_of` label. Preserved
  disclosure dates and immutable capture/vintage qualifications remain separate requirements.
- Tencent volume keeps the provider's raw value and explicit security-dependent unit: STAR-market
  688/689 stocks use shares; other stock paths use lots. Multiplication cannot recover source rounding.
- Tavily pools share per-key cooldown/health; 401/403 is explicit access failure, not permission to
  bypass it by rotating keys. Logs use fingerprints rather than raw keys.

A-stock-data is a reference used for selected hand-written ports, not a runtime import dependency.
Historical upstream reviews remain in the [archive](../archive/README.md). Wind is a retained classic
integration, excluded from native collection; see [compatibility](catalyst-research.md#wind).

<!-- Compatibility anchors for existing section links. -->
<a id="a-股补充数据能力"></a>
<a id="baostock-调用约束"></a>
<a id="eastmoney-datacenter-严格性"></a>
<a id="native-证据链的交易日历"></a>
<a id="上游基准与同步状态"></a>
<a id="安装与通达信边界"></a>
<a id="完整查过且确实没有与取数失败"></a>
<a id="官方披露与覆盖语义"></a>
<a id="新闻降级与凭据健康"></a>
<a id="研究日期与最新数据"></a>
