import type {
  AnchorOutputDTO,
  PercentilePointDTO,
  RangeSynthesisDTO,
  ValuationAssessmentDTO,
} from "../../api/contracts";

/**
 * Deterministic valuation-position card for the learning research reader.
 *
 * Every number shown here was computed by the code-owned decision chain
 * (tradingagents.research.valuation); this component only renders it. The
 * card must degrade gracefully: sparse evidence shows the reason instead of
 * leaving blank space, and the framing stays "research reference range",
 * never a trade recommendation.
 */

const BUCKET_ZH: Record<PercentilePointDTO["bucket"], string> = {
  undervalued_band: "低位带",
  lower_mid_band: "中低带",
  upper_mid_band: "中高带",
  elevated_band: "高位带",
  not_assessable: "无法评估",
};

const ANCHOR_STATUS_ZH: Record<AnchorOutputDTO["status"], string> = {
  available: "可用",
  partial: "部分可用",
  unavailable: "不可用",
};

const REASON_ZH: Record<string, string> = {
  negative_or_zero_net_income: "最新年报净利润为负或为零，市盈率口径不适用",
  negative_or_zero_equity: "最新年报净资产为负，市净率口径不适用",
  annual_base_missing: "缺少可验证的年报盈利基数",
  insufficient_multiple_history: "自身估值历史样本不足（需至少约 60 个交易日）",
  verified_peer_valuations_unavailable: "暂无可验证的同行估值观测",
  insufficient_comparable_peers: "可比同行估值观测少于 3 家",
};

const WINDOW_LABEL_ZH: Record<string, string> = {
  pe_3y: "PE 近3年分位",
  pe_1y: "PE 近1年分位",
  pb_3y: "PB 近3年分位",
  pb_1y: "PB 近1年分位",
  "52w_price": "现价 52周位置",
};

function windowLabelZh(label: string): string {
  return WINDOW_LABEL_ZH[label] ?? label;
}

const INPUT_REASON_ZH: Record<string, string> = {
  market_snapshot_unavailable: "实时估值快照不可用",
  annual_net_income_unavailable: "可验证的年报净利润不可用",
};

const RANGE_POSITION_ZH: Record<ValuationAssessmentDTO["verdict"]["range_position"], string> = {
  below_range: "低于参考区间",
  within_range: "处于参考区间内",
  above_range: "高于参考区间",
  unavailable: "无法判断",
};

function bandClass(bucket: PercentilePointDTO["bucket"]): string {
  if (bucket === "undervalued_band") return "reader-valuation__band--low";
  if (bucket === "elevated_band") return "reader-valuation__band--high";
  return "reader-valuation__band--mid";
}

function positionBadgeClass(position: string): string {
  if (position === "below_range") return "reader-badge reader-badge--green";
  if (position === "above_range") return "reader-badge reader-badge--red";
  if (position === "unavailable") return "reader-badge reader-badge--muted";
  return "reader-badge reader-badge--amber";
}

function formatYi(value: number): string {
  const abs = Math.abs(value);
  const digits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

/** Horizontal reference-range band with a live price cursor (pure SVG). */
function RangeBand({ assessment }: { assessment: ValuationAssessmentDTO }): JSX.Element | null {
  const low = assessment.synthesis.per_share_low;
  const high = assessment.synthesis.per_share_high;
  const price = assessment.current_price;
  if (low === null || high === null || price === null || !(high > low)) {
    return null;
  }
  const pad = Math.max((high - low) * 0.18, price * 0.02, high * 0.01);
  const scaleMin = Math.min(low, price) - pad;
  const scaleMax = Math.max(high, price) + pad;
  const width = 100;
  const toX = (value: number): number =>
    ((value - scaleMin) / (scaleMax - scaleMin)) * width;
  const bandLeft = toX(low);
  const bandRight = toX(high);
  const cursor = toX(price);
  const cursorLabel = `${price.toLocaleString("zh-CN")} 元`;
  return (
    <div className="reader-valuation__range">
      <svg
        className="reader-valuation__range-svg"
        viewBox={`0 0 ${width + 16} 46`}
        role="img"
        aria-label={`参考区间每股 ${low} 至 ${high} 元，现价 ${price} 元`}
      >
        <line x1="8" y1="24" x2={width + 8} y2="24" className="reader-valuation__axis" />
        <rect
          x={8 + bandLeft}
          y="12"
          width={Math.max(bandRight - bandLeft, 1)}
          height="24"
          rx="4"
          className="reader-valuation__interval"
        />
        <line x1={8 + cursor} y1="4" x2={8 + cursor} y2="36" className="reader-valuation__cursor" />
        <text x={8 + cursor} y="45" textAnchor="middle" className="reader-valuation__cursor-label">
          现价 {cursorLabel}
        </text>
      </svg>
      <div className="reader-valuation__range-ends">
        <span>{low.toLocaleString("zh-CN")} 元</span>
        <span>{high.toLocaleString("zh-CN")} 元</span>
      </div>
    </div>
  );
}

function PercentileBar({ point }: { point: PercentilePointDTO }): JSX.Element {
  return (
    <li className="reader-valuation__percentile">
      <div className="reader-valuation__percentile-head">
        <span className="reader-valuation__percentile-label">{windowLabelZh(point.window_label)}</span>
        <span className="reader-valuation__percentile-value">
          第 {point.percentile.toFixed(0)} 百分位 · {BUCKET_ZH[point.bucket]}
        </span>
      </div>
      <div className="reader-valuation__bar">
        <div
          className={`reader-valuation__bar-fill ${bandClass(point.bucket)}`}
          style={{ width: `${Math.max(Math.min(point.percentile, 100), 0)}%` }}
        />
      </div>
    </li>
  );
}

function AnchorDetail({ anchor }: { anchor: AnchorOutputDTO }): JSX.Element {
  return (
    <li className="reader-valuation__anchor">
      <div className="reader-valuation__anchor-head">
        <strong>{anchor.method_label_zh}</strong>
        <span className={`reader-badge ${anchor.status === "unavailable" ? "reader-badge--muted" : "reader-badge--green"}`}>
          {ANCHOR_STATUS_ZH[anchor.status]}
        </span>
      </div>
      {anchor.status === "unavailable" ? (
        <p className="placeholder">
          不可用原因：{REASON_ZH[anchor.reason_code ?? ""] ?? anchor.reason_code ?? "未知"}
        </p>
      ) : (
        <>
          <p>
            倍数带 {anchor.multiple_low}–{anchor.multiple_high}
            ，基数{" "}
            {anchor.earnings_base
              ? `${formatYi(anchor.earnings_base.value_yi)} 亿元（${anchor.earnings_base.period}${anchor.earnings_base.metric_id === "net_income" ? "，最新年报净利" : ""}）`
              : "未知"}
            ；隐含市值 {formatYi(anchor.implied_value_low_yi ?? 0)}–{formatYi(anchor.implied_value_high_yi ?? 0)} 亿元
            {anchor.per_share_low !== null && anchor.per_share_high !== null
              ? `（约 ${anchor.per_share_low}–${anchor.per_share_high} 元/股）`
              : ""}
            。
          </p>
          {anchor.invalidation ? <p className="placeholder">失效条件：{anchor.invalidation}</p> : null}
        </>
      )}
    </li>
  );
}

function SynthesisText({ synthesis }: { synthesis: RangeSynthesisDTO }): JSX.Element {
  if (synthesis.status === "unavailable") {
    return (
      <p className="placeholder">
        参考区间不可用。{synthesis.disagreement_note_zh ?? ""}
      </p>
    );
  }
  const capRange = `隐含市值 ${formatYi(synthesis.reference_low_yi ?? 0)}–${formatYi(synthesis.reference_high_yi ?? 0)} 亿元`;
  const perShare =
    synthesis.per_share_low !== null && synthesis.per_share_high !== null
      ? `每股约 ${synthesis.per_share_low}–${synthesis.per_share_high} 元`
      : null;
  return (
    <p className="reader-valuation__synthesis">
      {perShare ?? capRange}
      {perShare ? `；${capRange}` : ""}。
    </p>
  );
}

export function valuationCardNote(
  assessment: Pick<ValuationAssessmentDTO, "verdict" | "input_reasons">,
): string {
  const notes = assessment.verdict.fact_notes_zh.join(" ");
  const inputNotes = assessment.input_reasons
    .map((reason) => INPUT_REASON_ZH[reason] ?? reason)
    .join("；");
  return [notes, inputNotes].filter(Boolean).join(" ");
}

export function ValuationPositionCard({ assessment }: { assessment: ValuationAssessmentDTO }): JSX.Element {
  const degraded = assessment.synthesis.status === "unavailable";
  return (
    <section className="reader-section reader-section--valuation" aria-label="估值定位">
      <div className="reader-valuation__head">
        <h3>估值定位</h3>
        <span className={positionBadgeClass(assessment.verdict.range_position)}>
          {RANGE_POSITION_ZH[assessment.verdict.range_position]}
          {assessment.verdict.deviation_pct !== null
            ? ` · ${assessment.verdict.deviation_pct > 0 ? "+" : ""}${assessment.verdict.deviation_pct.toFixed(1)}%`
            : ""}
        </span>
      </div>
      <p className="reader-valuation__headline">{assessment.verdict.overall_label_zh}</p>

      {!degraded ? <RangeBand assessment={assessment} /> : null}
      <SynthesisText synthesis={assessment.synthesis} />

      {assessment.positions.length || assessment.week52_position ? (
        <ul className="reader-valuation__percentiles">
          {[...assessment.positions, ...(assessment.week52_position ? [assessment.week52_position] : [])].map(
            (point) => <PercentileBar key={point.window_label} point={point} />,
          )}
        </ul>
      ) : null}

      <details className="reader-valuation__anchors">
        <summary>锚点与方法明细（{assessment.anchor_outputs.length}）</summary>
        <ul>
          {assessment.anchor_outputs.map((anchor) => (
            <AnchorDetail key={anchor.anchor_id} anchor={anchor} />
          ))}
        </ul>
        <p className="placeholder">{assessment.synthesis.method_note_zh}</p>
      </details>

      <p className="reader-valuation__disclaimer">
        以上区间由已验证数据经确定性规则推导，为研究参考而非操作建议；不构成买入、卖出或任何执行指令。
      </p>
    </section>
  );
}
