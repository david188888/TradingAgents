# Capability supplement live acceptance — 2026-11-05

Status: Dated acceptance record. Not current-state architecture or operating guidance.

Task 6 of [the capability-catalog plan](../plans/2026-11-05-capability-catalog-controlled-supplement-plan.md):
one authorized live V9 study to measure model usage, capability audit and supplement counts after
the catalog/gateway work (PR #44, #45). No default budget or configuration was changed.

## Run

| Item | Value |
| --- | --- |
| Run | `run_20261105T110427426212Z_595dffce` (workspace-local store, user run stores untouched) |
| Ticker / date | `002130.SZ` / 2026-11-05 |
| Model | DeepSeek `deepseek-flash` for both tiers, thinking enabled, effort high |
| Limits | Default policy: 900 s active deadline, `SUPPLEMENT_CAPABILITIES` 3 per run, capability calls 2 per specialty |
| Result | `completed` in 762 s; Insight report readable; synthesis stance 不利 over 7 accepted Insights (33 total items: 7 accepted, 10 pending, 16 superseded) |
| Review round | Challenge stage reported `failed`: 3 challenged, 4 unreviewed; response stages `failed`; synthesis still completed |

## Capability audit

Requests the model actually made (saved in the journal, not paraphrased):

| Role / round | Requests | Outcome |
| --- | --- | --- |
| event main | 2× `disclosure_search` (board resolution + capital increase, progress announcement), 1× `news_search` | 2 dispatched, both `capability_empty:disclosure_search`; the `news_search` request was cut by the per-specialty cap and `capability_role_limit:event_context` was recorded |
| event supplement_1 | 5 requests (3× `disclosure_search`, 2× `news_search`) | all blocked by the same per-specialty cap (`capability_role_limit:event_context`); web `search_requests` were empty this round |
| event supplement_2 | 3× `disclosure_search` | blocked by the per-specialty cap |
| market main | 1× `disclosure_search` ("股价异常波动公告") | dispatched, `capability_empty:disclosure_search` |
| market supplement_2 | `shareholder_count` + `disclosure_search` + `news_search` | first accepted, then `capability_budget_exhausted` before dispatch; `capability_role_limit:market_context` for the rest |

Ledger: exactly 3 `supplement_capabilities` attempts, all `disclosure_search` (2 event, 1 market), all
settled `ok`, none admitted. Report gaps include `capability_empty:disclosure_search`,
`capability_no_qualified_delta`, `capability_role_limit:event_context`,
`capability_role_limit:market_context`, `capability_budget_exhausted`,
`event_context_supplement_unresolved`, `market_context_supplement_unresolved`.
**No `capability.*` source reached the review catalog or any Insight.**

## Model usage

| Stage | Input tokens | Output tokens |
| --- | --- | --- |
| operating_quality main + repair | 82,005 + 82,016 | 14,196 + 7,587 |
| event_context main + supplement_1 + supplement_2 | 22,607 + 57,534 + 67,516 | 8,177 + 10,254 + 8,308 |
| market_context main + repair + supplement_2 | 2,683 + 2,734 + 25,651 | 3,363 + 1,224 + 7,366 |
| challenge | 160,774 | 12,343 |
| response ×3 | 166,858 + 166,859 + 166,861 | 2,397 + 1,570 + 2,625 |
| synthesis | 42,383 | 2,880 |
| **Total** | **1,046,481** | **82,290** |

Ledger buckets: `main_analysis` 8, `structured_repair` 2, `search_review` 3, `deepseek_search` 14,
`tavily_search` 14, `search_page` 8, `search_rounds` 2, `supplement_capabilities` 3,
`data_capability_calls` 20, `data_http_attempts` 44.

Comparison basis is weak by construction: there is **no completed pre-change V9 run**. The closest
pre-change record is `run_20261104T142743857851Z_143ff49a` (same defaults, 2026-11-04): it finished the
three specialists plus one supplement and two repairs (301,049 tokens total) and then hit the 900 s
deadline inside challenge. Its specialist main calls (operating 88,821/9,053; event 21,030/3,959;
market 2,197/2,774 input/output) are within the same order as this run, so the compact capability cards
added roughly 1–2 k input tokens per specialist, not an order-of-magnitude increase. The totals above
are not comparable because this run reached challenge, responses and synthesis while the baseline did not.

## Finding: `disclosure_search` returns nothing for real model queries

Every dispatched `disclosure_search` produced zero rows even though the matching CNINFO announcements
exist. The gateway filters the CNINFO listing client side with
`query.casefold() in title.casefold()` — the **whole query string must appear verbatim in one title**.
Real model queries are natural-language sentences, so the match rate is structurally close to zero.
Verified against the live CNINFO listing for the same window (60 titles fetched):

| Model query (first dispatch round) | Whole-string match | Notes |
| --- | --- | --- |
| `第八届董事会第十二次会议决议公告 控股子公司增资扩股暨关联交易 2026-09-18` | 0 | Titles contain `第八届董事会第十二次会议决议公告` and `关于控股子公司增资扩股暨关联交易的公告` |
| `关于控股子公司增资扩股暨关联交易的进展公告 2026-10-09 全文` | 0 | Exact title exists: `关于控股子公司增资扩股暨关联交易的进展公告` |
| `股价异常波动公告` | 0 | Title family uses `股票交易异常波动` wording |
| `乐庭智联 增资协议 工商变更 完成 公告` | 0 | `关于完成工商变更登记的公告` exists |

The same live listing shows the CNINFO endpoint already accepts a `searchkey` field
(`get_a_share_cninfo_announcements` currently always sends `searchkey: ""`), so server-side keyword
search is the natural fix; a client-side token match would only patch part of the wording gap. The
capability card also still describes `query` as "公告主题关键词" while the model is free to write a
sentence — the card text and the matcher must agree.

Consequences observed in this run: the three-call capability budget was spent on three empty results,
later, more specific requests were cut by the per-specialty cap, and the specialists fell back to the
existing dual-search path (`search_requests`) for the same gaps instead of gaining structured evidence.

## Verdict

Accepted (no regression):
- Requests are parsed and audited; per-specialty caps, the run-wide capability budget and typed gaps
  (`capability_empty` / `capability_budget_exhausted` / `capability_role_limit`) behave as designed.
- Capability work is independent of the web-search switch; `news_search` is not executed by the gateway.
- The run respected the default deadline, published a readable Insight report, and did not reintroduce
  Bull/Bear debate or tool access for challenge/synthesis.

Not accepted yet:
- Zero evidence yield for `disclosure_search` in the only live run, for a fixable matching reason.
  The capability-supplement value claim stays unproven until the query→CNINFO matching is corrected and
  a follow-up live run admits at least one capability fact.

Open, outside this change: the challenge/reply stages failed again (review completeness, response
validation). This matches the pre-change failure surface and is not caused by capability cards, but it
means live runs still cannot produce a fully reviewed report.

## Proposed next step (not executed here)

1. Give `get_a_share_cninfo_announcements` an optional `searchkey` pass-through and have the gateway
   send the model query to CNINFO's own search, keeping the same person/date qualification and bounded rows.
2. Rewrite the `disclosure_search` card `inputs` so the model is asked for short keywords; keep `not_for`.
3. Re-check with the recorded real queries above (public data only, no model) and add offline tests for
   the new matching contract.
4. Optional second live run, only with explicit authorization, to confirm admitted capability evidence
   and re-measure token usage.

## Resolution after this run

The disclosure matching defect was fixed on 2026-11-05 (design §13.3): CNINFO server-side title
keyword search with date/filler normalization, a longest-term fallback when the multi-term AND finds
nothing, and highlight tags disabled. The card now asks for 1–3 space-separated title keywords.
Replaying the recorded queries against live public CNINFO admits titles for the board-resolution,
progress-announcement, next-day-disclosure, shareholder-meeting and 乐庭智联 queries; the
`股价异常波动公告` query stays correctly empty because no title in the window carries those words.
Offline tests cover normalization, the fallback, empty results and card/budget behavior. A second
live model run is pending explicit authorization; the acceptance verdict above remains the record of
this run itself.
