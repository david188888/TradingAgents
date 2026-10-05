# Low-cost evidence investigation — 600803

Status: Historical

Do not use this document as evidence of current implementation behavior.
See [the documentation index](../README.md) for current-state references.
The user approved the recommended scope on 2026-10-05; implementation and
acceptance are still pending. The [design](../superpowers/specs/2026-10-05-low-cost-evidence-design.md)
records the proposed implementation boundaries.

Investigated on 2026-10-05 against `4f4a0eb775f6c121862da498df453609f0966dd9`.
The prior frozen run `run_20261004T151705246468Z_32576e4c` and its evidence were
read without alteration. This investigation used public HTTP requests and local
PDF/text inspection, with no model SDK requests or paid data calls. Downloads
and probe results are isolated in `/private/tmp/ta-evidence-investigation/`;
they are investigation artifacts, not admitted production evidence.

## Findings

1. `dataflows/disclosure_documents.py:report_period()` accepts an unprefixed
   annual/interim title. CNINFO's actual title is `新奥股份2026年半年度报告`, so
   it is not selected as a formal report. The summary and main operating-data
   notice also fail the current document-selection rules. Replaying those three
   actual catalogue rows through `select_documents()` selected zero documents.
2. The current report parser mainly recognizes revenue-composition and
   profitability layouts. Running its operating-table parser against the full
   223-page report yielded zero admitted rows and
   `operating_table_layout_not_admitted`. The dedicated operating notice is a
   different layout, combining Q2 and H1 columns, mixed physical units, and
   wrapped labels. It must not be treated as the existing revenue table.
3. Directly parsing the actual summary failed `document_security_unqualified`:
   its header uses `公司代码`, which the security-label matcher does not accept.
   Identity/publication/report-period checks still need to remain strict.
4. The relevant financial-note pages are outside the current bounded excerpt
   selection. Current frozen financial operands also retain only revenue,
   consolidated/parent net income, total assets/liabilities and operating cash
   flow. Obtaining the full supplier response alone does not expose working
   capital or cash-flow adjustments to the research graph.
5. Existing `china_specialty_em.py` adapters already fetch research-report EPS
   fields and THS forecasts. `native_sources.py` does not route those capabilities
   into the maintained native Web research flow. Adding more global vendor
   settings does not resolve that missing integration.
6. `ChallengeAssessmentV1.outcome` permits only `unresolved`;
   `graph/native_research.py` also explicitly instructs synthesis to retain that
   outcome, and any challenge forces `LOW_CONFIDENCE`. This is the current
   conservative contract. More data alone cannot make an existing challenge
   acquire a resolved outcome. A useful distinction between an answered evidence
   question and a continuing economic uncertainty requires an approved contract
   change, rather than a prompt-only workaround.

## Public-source probes

| Source | Actual result | Admission limit |
| --- | --- | --- |
| CNINFO full H1 report | HTTP 200, 2,181,238 bytes, 223 pages | Selected excerpts, issuer/time/period checks; H1 unaudited |
| CNINFO H1 summary | HTTP 200, 155,596 bytes, 4 pages | Same disclosure lineage as the full report; not independent confirmation |
| CNINFO operating notice | HTTP 200, 109,365 bytes, 1 page | Internal unaudited statistics; Q2 and H1 are different columns |
| EastMoney reportapi | HTTP 200; one report since 2026-07-01, dated 2026-09-04; response `currentYear=2026` | Analyst forecasts, not reported earnings or an independent seven-source sample |
| THS worth page | HTTP 200; EPS/net-profit summary and dated institution rows; seven institutions for 2026/2027 | Snapshot capture and report dates must both be retained; deduplicate institutions |
| EastMoney industry comparison | HTTP 200; target, five named candidates and two aggregate rows | Eight returned rows versus stated industry population 31; aggregate/sample coverage differs; `REPORT_DATE` is not proof of quote time |
| Tencent quotes | Target plus three candidate peers all returned 2026-09-30 timestamps | Same latest quoted session, current capture; not a historical archived vintage |
| Yahoo chart | HTTP 403 in this environment | Current-network failure, not proof that Yahoo is unavailable everywhere |

PDF SHA256:

- Full report: `f36c421ac8d7d564f4df40d18a5a57b8c4a04dc4f53f09c2a5d2d56e6e4ddafe`.
- Summary: `f4a291838cf525881095613b46576d5bb296fed3dd77c13703b27fcce144d495`.
- Operating notice: `9098ed79d2f5d5269c45e9c8c94e36a56006a674d48e3aabb108f3b43f62f3d1`.

The report's pages 179–180 were inspected as rendered pages, including their
shared units and current/prior columns. All disclosed cash-flow reconciliation
components sum exactly to 447,797 and 557,339 respectively, in CNY ten-thousands.
The three working-capital adjustments contribute -28,346 of the -109,542
year-on-year cash-flow change. Investment and fair-value adjustments also
matter; those accounting adjustments alone do not establish economic causation
or prove structural deterioration. The first original challenge is a coverage
gap; the second contains a genuine attribution question and an unavailable
future observation. They should not share an all-or-nothing resolution rule.

## Proposed minimum sufficient evidence

| Question | Minimum useful evidence | Remaining limit |
| --- | --- | --- |
| Is an operating-quality judgement based on substantive disclosures? | Qualified H1 key financial pages plus relevant business/operating pages or the operating notice, with dates, units, page locators and supplier cross-checks | Coverage remains selected; management assertions are not independent delivery evidence |
| What changed in cash conversion this H1? | Current/prior H1 cash flow and net income, the reconciled cash-flow bridge and working-capital components | A statement about structural persistence remains conditional; future annual data is a follow-up, not a prerequisite for describing current evidence |
| What explains valuation positioning? | Same-date historical PE/PB positioning and qualified peer context and/or clearly dated analyst EPS forecasts | Peer comparability, nonrecurring earnings and forecast uncertainty remain explicit; absence of forecasts does not invalidate an otherwise supported historical comparison |

Recommended implementation scope: repair document selection/admission; add
bounded relevant-page/table extraction; route qualified forecasts and peer
context into the native frozen record; add code-owned evidence checks and
distinguish answered data gaps, supported risks, unresolved questions and future
observations. Preserve all original records and checkpoint behavior. Use the
existing research budget and explicit source failure states. No OCR, paid
provider subscription, unbounded crawl, CLI work or automatic grade promotion.

An alternative first increment repairs only document coverage and leaves the
current all-unresolved challenge contract intact. It is smaller, but does not
fully address the user's complaint about useful challenge resolution.

Verification should use 600803, downloaded public artifacts and deterministic
fixtures first. A later real model acceptance requires a separately bounded
request allowance; the prior six-request frozen acceptance is already spent.

## Source references

- [a-stock-data v3.10.0 reference](https://github.com/simonlin1212/a-stock-data/tree/f814dcfe209dd7958f4858f9d878d591ee85fb56): endpoint reference, not an importable runtime dependency.
- [AKShare peer adapter](https://github.com/akfamily/akshare/blob/fac1e50ebf9b907960d6aab4c3df658559689f39/akshare/stock/stock_zh_comparison_em.py): supplementary endpoint reference; not an independent underlying data provider.
- [AKShare THS adapter](https://github.com/akfamily/akshare/blob/fac1e50ebf9b907960d6aab4c3df658559689f39/akshare/stock_fundamental/stock_profit_forecast_ths.py).
- [600803 H1 full report](https://static.cninfo.com.cn/finalpage/2026-08-29/1225526373.PDF).
- [600803 H1 summary](https://static.cninfo.com.cn/finalpage/2026-08-29/1225526315.PDF).
- [600803 H1 operating notice](https://static.cninfo.com.cn/finalpage/2026-08-29/1225525549.PDF).
- [THS forecast page](https://basic.10jqka.com.cn/new/600803/worth.html).
