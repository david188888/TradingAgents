# Web evidence-driven research

Status: Current

`evidence_v1` is the default and only new Web research workflow. The form
supports A-share company, catalyst and holding research; batch uses the same
company workflow. `NativeRunner` owns execution. CLI analysis is outside
continued maintenance; `tradingagents web` remains the supported launcher.

## Start Web research

Keep model/data credentials in ignored local configuration and start:

```bash
tradingagents web --port 8765 --open
```

`GET /api/config` reports native support and the native Web default. Creation
is enabled unless explicitly disabled by `TRADINGAGENTS_EVIDENCE_ENABLED=false`
or `evidence_profile_enabled=false`. This blocks single/batch creation and
fresh retries with `403 evidence_profile_unavailable`; saved reading and
compatible interrupted-run resume remain available. Old `classic` and
`catalyst_v1` creation/retry return `410 research_profile_retired` even if the
old catalyst flag is enabled. Legacy history is neither deleted nor rewritten.
The neutral `AnalysisRequest` and retained CLI defaults remain compatibility
contracts and must not be mistaken for the Web default.

Submit one run through `POST /api/runs`. This example contains no credentials;
replace the cutoff and model IDs with the values for the intended research and
the configured provider. A historical cutoff can leave price evidence
unavailable when its archive vintage cannot be established.

```bash
curl --fail-with-body http://127.0.0.1:8765/api/runs \
  -H 'Content-Type: application/json' \
  --data-binary @- <<'JSON'
{
  "ticker": "600803.SS",
  "analysis_date": "2026-10-02",
  "research_profile": "evidence_v1",
  "mode": "company_research",
  "research_question": "哪些经营事实支持持续改善，哪些问题仍需核查？",
  "llm_provider": "deepseek",
  "quick_think_llm": "deepseek-v4-flash",
  "deep_think_llm": "deepseek-v4-flash",
  "output_language": "Chinese"
}
JSON
```

The optional question is trimmed and limited to 400 Unicode code points. It
is saved in run identity; omission uses the mode's code-owned question.
Native roles and the single challenge stage are code-owned. Omit classic
scheduling fields, or retain their compatibility defaults: all four analyst
keys, depth/rounds of one, and `horizon=medium`. Non-default selections are
rejected rather than ignored. The `evidence_policy` may be omitted; if supplied,
it must match `NativeEvidencePolicyV1`, not the catalyst policy.

| Mode | Research scope | Additional input |
| --- | --- | --- |
| `company_research` | Operating quality, valuation evidence and market context. | No holding context. |
| `catalyst_research` | Operating evidence, catalyst delivery and market context over the next 84 calendar days. | No holding context. This mode requires `evidence_v1`; the older `catalyst_v1` entry still uses `company_research`. |
| `holding_review` | Recheck the user's original thesis against operating, valuation and market evidence. | A `holding` object with ticker, positive quantity and average cost; other account facts and the original thesis remain optional. |

For holding review, change the mode and add user-provided facts. The following
is illustrative input, not an actual account or a suggested position:

```json
{
  "mode": "holding_review",
  "holding": {
    "ticker": "600803.SS",
    "quantity": 100,
    "average_cost": 10,
    "facts_as_of": "2026-10-02",
    "original_thesis": "原假设：收入改善能够延续；下一期收入回落则重新核查。"
  }
}
```

The full body retains the other fields from the company example. Holdings are
declarations, not independently verified evidence. Missing original thesis
limits the holding-thesis dimension; the system does not invent it or infer
missing account values. Company and holding modes do not acquire an 84-day
outlook from the collector's compatibility adapter.

## Evidence and workflow

The code-owned source policy fixes 7/30/90-day event windows, 250 trading days
of price history and eight financial-reporting quarters. Source windows are
separate from research outlook. New native runs use the v4 `dataflows/native_valuation.py` collector, extending
the bounded public sources and official disclosure collector in all three modes:

| Capability | Native default candidates, in order |
| --- | --- |
| Security identity | EastMoney exact profile, Sina labelled company profile, Tushare stock_basic |
| Financial tables | Sina direct income/balance/cashflow, then Tushare separately per failed table |
| Official disclosures | Existing CNINFO official query, including its bounded official fallback |
| Calendar | Complete SZSE monthly natural-day grid for Shenzhen securities, then Tushare |
| Adjusted prices | Tencent raw daily bars plus dated Sina qfq divisors, then Tushare daily/factors |
| Valuation | Tencent exact dated current snapshot; Tushare daily_basic PE-TTM/PB history |

Sina financial admission requires consolidated scope, CNY yuan fields and real
publication dates; an update timestamp after cutoff is excluded. Provider
metadata is saved with the normalized source response. Qualified tables survive
other table failures. Providers remain separate source families, and C1 numeric
comparisons still require the same exact family. Tencent raw requests include
the mandatory empty adjustment field. Public adjustment applies Sina's divisor
to all OHLC and re-anchors to the last settled session, checking the complete
calendar, current-cutoff capture and input hash. Generic Tencent qfq remains
unqualified; older cutoffs still need an archived factor vintage. SZSE calendar
is not borrowed for Shanghai/Beijing securities; those currently use the backup.

Programmatic `effective_config.evidence_source_vendors` can replace any of
`identity`, `financial`, `calendar`, `price`, `events`, `valuation` with an ordered subset of
its candidates (empty disables it). `evidence_source_exclusions` removes named
vendors afterwards. These native-only keys are bound to checkpoint identity;
legacy `data_vendors`/`tool_vendors` keep their classic/catalyst meaning.
Classic defaults are unchanged. Failed attempts and selected table providers
are persisted in `native_source_admission`. A Tushare rate-limit rejection
suppresses further Tushare attempts in that run; public sources remain eligible.
All attempts share the existing capability/HTTP ceilings and active deadline.
Cancellation, budget exhaustion and checkpoint conflicts stop execution.

The current `evidence-production-v4` also binds valuation inputs and dimension-reference
validation; v3 binds documents and scoped coverage. Original v1, v2 and v3 checkpoints
recover with their original collectors and kernel/prompt inputs when V0 is
missing, or replay saved V0/output without new source calls. A new topology
is never inserted into an old interrupted run.
Having credentials does not establish entitlement, complete coverage or
point-in-time provenance. Opaque SDK sources and unqualified historical factors
remain unavailable; a source gap never proves an event did not occur.

```text
qualified saved source fields -> facts-only V0
  -> operating quality / event context / market context specialists
  -> one independent challenge stage (zero to three challenges)
  -> bounded condition verification (up to three checks)
  -> one dimension-gated synthesis -> authorized native record and Markdown
```

Facts and source identity are extracted by code. Specialists see isolated fact
views, with fixed reservation and merge order and at most two concurrent
workers. Context isolation is not statistical independence. Hypotheses cite
facts and retain invalidation conditions and alternative explanations. The
challenge stage sees anonymous hypotheses; it need not manufacture opposing
positions when evidence is clear.

The model adapter checks specialist fact IDs before saving a proposal. A
schema-valid fabricated reference can use the existing single structured
repair allowance; it cannot enter the kernel or cause unbounded retries.
Kernel reference guards remain authoritative, including old cached proposals.

Verification is a closed local operation on saved financial fields or metrics.
It is not an unrestricted model tool loop or additional data search. Checks
bind a hypothesis, challenge, immutable condition and input snapshot. Actual
checks create V1 lineage while preserving V0; zero execution creates no V1.
A successful predicate check does not prove the whole hypothesis or close an
economic challenge. Derived arithmetic retains its source family.

Specialist unknowns in v3 carry their code-owned role; they describe isolated
inputs, not global source absence. Synthesis also receives collector coverage.
Reader/Markdown separate `global_coverage`, `global_gap` and specialist unknown
labels; old unscoped unknowns explicitly retain unknown scope. A conditional
dimension with usable inputs is not labelled as missing those same inputs.

The synthesis follows code-owned dimensions and evidence ceilings. Unavailable
valuation inputs constrain valuation; missing qualified prices constrain market
context. Announcement titles do not establish delivery. The current source
adapters do not supply qualified valuation inputs to this native workflow, so
company and holding research retain an unresolved valuation dimension and a
partial assessment. Risk/ATR statistics do not fill that gap.

Model proposals must include each mode dimension exactly once. Their array
order is normalized to the code-owned output order: JSON prompt serialization
may reorder mapping keys. Unknown claim references still fail validation. For
a dimension with an unavailable evidence ceiling, code removes proposed claim
references and replaces the judgement with the missing-data explanation;
discarded references are labeled `unqualified_dimension_claims_discarded`.
The raw proposal remains in the checkpoint for audit. Qualified dimensions
retain their source-partition checks.

## Budget, cancellation and recovery

The native flow reuses the existing durable ledger and its hard limits: five
main model calls, two structured repairs across the run with at most one per
stage, and twelve model attempts in total. Data calls retain the existing
twenty-four capability and sixty-four HTTP-attempt ceilings. One bounded
verification round covers at most three supplementary capabilities. This
profile does not increase the ceilings to compensate for missing sources.
SDK retries are disabled; each actual model request acquires one process-wide
model slot. Specialists/challenge use quick, synthesis uses deep.

Native checkpoints persist independently of the classic checkpoint toggle.
Active execution defaults to 300 seconds, excluding queue time. Interrupted
runs can use `POST /api/runs/{id}/resume` after identity and integrity checks.
Profile, mode, source policy, question, cutoff, holding context, configuration
and workflow version must match. The exact saved V0 and validated stage results
are reused. A validated SDK response saved before the kernel's MAIN result can
also be recovered without a new request. Unknown dispatched calls remain spent
and are not automatically redispatched; missing token usage stays unknown.

Cancellation and publication authorization share the manager's lifecycle
lock. Cancellation first prevents publication; authorization first preserves
the candidate's right to publish and rejects late cancellation. Native record
publication is mandatory: a publication failure cannot produce `run.completed`
or a fallback classic/catalyst case. Recovery verifies the saved candidate,
authorization barrier and public bytes. Reports are derived from that same
record, without a second summary model.

## Read a result

`GET /api/runs/{id}/reader/record` reads the committed `research-record-v1`.
Native records require their assessment and no paired legacy case. The
workbench routes an explicitly native run to this record as its single main
Reader. It shows the judgement, up to three key claims, primary risk and next
check first; historical quantitative context remains on the main surface.
Supporting facts and saved original content are available on demand. Missing
publication stays unavailable rather than showing a legacy summary.

`ready` means readable, and `completed` means the execution/publication path
finished. Neither establishes complete research or predictive accuracy. Inspect
the assessment's completeness, quality, per-dimension limitations and unresolved
challenges separately. `partial / LOW_CONFIDENCE` remains visibly limited
research. Source/model failures and budget refusal do not become verified facts.

Reader, audit, SSE replay/reconnect and report reads make no model or provider
calls. Markdown is stored in the run's `reports/complete_report.md` in the local
durable store. The Web default migration is implemented. This engineering
integration has no paid quality comparison or real-world predictive-accuracy
acceptance. The [600803 Web acceptance](../reviews/2026-10-04-web-final-acceptance.md)
records two fresh-source trials and one explicitly approved frozen-evidence
validation, with their separate execution and research-quality outcomes.
The [002130 live smoke record](../archive/reviews/2026-10-03-002130-live-smoke.md)
documents a real source/model trial, a cached replay and a provider-limited
second run; it does not establish complete research or predictive accuracy.
See [the shared record contract](../contracts/research-record.md) and
[architecture](../../ARCHITECTURE.md) for canonical ownership.

## Official document admission

New v3 runs share `DisclosureSources` in all three modes. The existing CNINFO
90-day announcement list remains distinct from document coverage. When no
formal annual/interim report occurs in that list, a separate bounded 550-day
catalogue query supplies candidates. Selection is deterministic by publication
and identifier: at most one formal report and three recent operating/project/
governance event disclosures. Summaries, unsupported revisions and duplicate
attachments cannot stand in for the report. Native CNINFO disable/exclusion
also disables its document extension.

Downloads use the existing BudgetedSession and durable fetch keys, without
redirects, credentials or hidden retries. Only validated static.cninfo.com.cn
attachment paths matching the official announcement ID are accepted. Documents
have a 20 MiB / 500-page ceiling; the optional china installation includes
pypdf. Encrypted, corrupt, scanned/empty, wrong-security, wrong-issuer or
future-report documents remain unavailable. Cancellation/deadline/checkpoint
errors stop execution; exhausting supplementary document budget stops that
supplement and retains prior qualified evidence. Historical cutoffs currently
have no archived PDF vintage and explicitly skip new body admission.

Saved excerpts include document ID/hash, publication, parser version and PDF
page. Only selected pages and bounded text are saved: this is partial body
coverage even when the catalogue is complete. Company plans and management
statements remain company disclosures, not independently verified delivery.
Operating extraction supports explicit five-column revenue composition and
six-column revenue/cost/margin layouts, including inherited page headers and
wrapped labels. Only yuan/ten-thousand-yuan CNY units are admitted; report
periods and classification groups stay distinct. Decimal arithmetic checks
reported margin precision; malformed columns invalidate that table while
retaining other qualified tables and excerpts. Incomplete classification totals
are labelled; no residual rows, missing values or estimates are manufactured.
These families are excluded from C1's financial-statement operand registry.

The saved record represents source status independently for financials,
announcement lists, selected bodies, operating rows and prices. Source
availability never establishes that all economic questions are answered.

## Native valuation qualification

V4 adds optional capability `valuation`. A Tencent snapshot requires exact code,
positive finite price/market cap, at least one positive multiple and a timestamp
on the last settled exchange session. Shanghai/Beijing still require their own
qualified calendar via Tushare; the SZSE calendar is not borrowed. Current quote
and history are admitted only when captured on the requested Shanghai cutoff
calendar date. Historical cutoff requests keep valuation unavailable without an
archived vintage.

Tushare `daily_basic` history requests at most 1095 calendar days and 1000 rows,
checks code, dates, duplicates and the last settled session, and shares the
existing HTTP/capability/deadline ledger. A failed optional history call retains
a qualified snapshot as partial coverage. History is current-capture
retrospective data, not proof of archived PIT availability.

`research/native_valuation.py` reuses `research/valuation.py` to calculate
historical positioning and a PE p25–p75 reference anchor from the latest
qualified consolidated annual net income attributable to parent shareholders
(`n_income_attr_p`). Monetary inputs are normalized to CNY 亿元. Share count is
implied from current market cap/price and inherits quote rounding. No native
peer anchor, intrinsic value or standalone annual equity input is invented.
Missing history/profit keeps reference anchors unavailable. The record saves
inputs, evidence IDs, input SHA256 and the deterministic assessment; the model
only receives read-only results. Valuation dimension claims may cite only the
valuation fact family; operating judgements still require financial facts.

The Reader and Markdown use the same committed record. Citation drawers display
saved content before locator metadata, with timestamps and hashes; Escape, Tab
trapping, inert background and returned focus are part of the interaction.
Single-symbol smoke validates wiring and readability; wider same-evidence quality,
cost and accuracy comparisons remain separate work.
