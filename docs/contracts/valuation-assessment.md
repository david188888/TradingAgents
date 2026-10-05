# Valuation Assessment Contract (valuation-assessment-v1)

## What it is

`valuation-assessment-v1` is a derived public artifact computed after the
learning research case is committed. It answers two questions with
deterministic, replayable arithmetic over already committed bundles:

1. Where does the current price/multiple sit relative to the ticker's own
   history and to peers (低位还是高位)?
2. What reference per-share / market-cap interval follows from the latest
   disclosed annual earnings under multiple-band anchors (合理预期参考区间)?

The chain is code-owned (`tradingagents/research/valuation.py`). No LLM turn
creates or mutates any number; the model may only narrate a rendered,
read-only brief (see `_render_valuation_context` in the research manager).

## Inputs (committed bundles only)

| Input | State key | Provider |
| --- | --- | --- |
| Realtime valuation snapshot (price, PE-TTM, PB, market cap) | `valuation_bundle.results[capability=valuation_snapshot]` | tencent `get_a_share_valuation` |
| ~3y daily multiple history (peTTM / pbMRQ) | `valuation_bundle.results[capability=valuation_history]` | baostock `get_a_share_valuation_history` |
| Verified market quote + adjusted closes (52w position) | `adjusted_price_bundle` quote/adjusted data | existing price prefetch |
| Latest annual net income / equity base (亿元, filing-date guarded) | `fundamentals_prefetch_bundle` observations | existing fundamentals adapter |

The bundle is prefetched by the deterministic graph task
`Valuation Evidence Prefetch` (`tradingagents/agents/utils/valuation_data_tools.py`)
for retained classic graph runs; non-A-share tickers produce an explicit `not_applicable`
bundle. Parser: `tradingagents/research/valuation_inputs.py`.

## Decision chain rules

- **Positioning**: current PE/PB percentile inside own 365/1095 calendar-day windows
  (midpoint rank), peer premium/discount vs median (±10% threshold), price
  percentile inside trailing 52-week closes.
- **Anchors** (each fails closed with a reason code):
  - `history_pe_band`: latest disclosed annual net income × own 3y PE p25-p75;
    falls back to `history_pb_band` (equity × PB band) when income is
    non-positive.
  - `peer_pe_band`: only when ≥3 verified current peer PE-TTM observations
    exist; otherwise explicitly unavailable.
- **Synthesis**: overlapping anchor intervals intersect; disjoint intervals
  fall back to the union span plus a mandatory disagreement note; a single
  usable anchor is published alone with a "single-anchor" method note; zero
  anchors ⇒ `unavailable`.
- **Verdict**: last verified price vs the synthesized per-share interval →
  `below_range` / `within_range` / `above_range` plus deviation percent.

Pydantic validators enforce the arithmetic (implied value = base × multiple,
band monotonicity, per-share monotonicity) so a malformed artifact cannot be
published.

## Consumers

- Reader projection: `LearningReaderV2.valuation` → frontend
  `ValuationPositionCard` (range band + percentile bars + anchor details).
- Prompt narrative: the research manager receives the rendered brief as
  read-only factual context for synthesis.

## Guarantees and limits

- Sparse evidence degrades with explicit reason codes; numbers are never
  guessed ("宁缺毋假").
- The output is a research reference range anchored to disclosed figures —
  it carries no growth forecast and must not be read as a trade target or
  recommendation. Multiple choice assumes historical pricing habits persist
  and is labelled advisory heuristics.
- All figures share the same currency/cutoff discipline as the rest of the
  research layer (annual monetary values normalized to CNY 亿元).

## Native Web valuation chain

New Web studies reuse this same pure chain inside the optional `research-record-v1.valuation`.
Their input assembler is `research/native_valuation.py`, with dated Tencent
snapshot, direct Tushare `daily_basic` PE/PB history and the latest qualified
consolidated annual net income attributable to parent shareholders. Native
annual equity, peer valuation anchors and 52-week price positioning are not
assembled into this chain; their outputs remain unavailable. Source refs, complete saved inputs,
input SHA256 and recomputation protect the native record boundary.
History is current-capture retrospective data, admitted only at today's requested
cutoff; it does not prove archived historical PIT availability. Market cap / price
implies shares and inherits rounding. A single available historical PE anchor
remains assumption-dependent; its interval does not establish intrinsic value.
The native Reader and saved Markdown render this committed assessment without
provider/model work during reading. V1–V3 records and old workflow recovery
retain their prior semantics.

V5 supplements this retained V4 chain with same-session industry-candidate
quotes and dated institution EPS in `research-record-v1.evidence_checks`.
`research/minimum_evidence.py` checks their finite evidence scope and saves
sample medians or institution scenarios. These inputs do not populate the
chain's peer anchor or create new fair-value ranges. Industry candidates are
not assured business comparables; fewer than three institutions remain
individual scenarios rather than a consensus mean. See
[V5 source and check rules](../operations/evidence-research.md#v5-minimum-sufficient-evidence).
