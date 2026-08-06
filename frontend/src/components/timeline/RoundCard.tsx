/**
 * L2 per-round summary card for the research/risk debates.
 *
 * Shows the LLM-generated index (topic, one-line summary, keywords, and for
 * the research debate estimated conviction bars) without the full text.
 * Expansion into L3 (full per-lane markdown) is wired by the parent and
 * lazy-mounted so collapsed cards never parse debate prose.
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import type { ResearchRoundSummaryDTO, RiskRoundSummaryDTO } from "../../api/contracts";

export interface RoundCardProps {
  /** 1-based round number. */
  roundIndex: number;
  topic: string;
  summary: string;
  keywords: string[];
  /** Lanes rendered as conviction rows. */
  lanes?: ReadonlyArray<{
    key: string;
    label: string;
    /** 0-1 when estimated/measured; null renders a neutral dash. */
    value: number | null;
    tone: "bull" | "bear" | "risk" | "neutral";
    estimated?: boolean;
  }>;
  /** Lazy L3 detail node; mounted only while expanded. */
  detail?: ReactNode;
  defaultExpanded?: boolean;
}

function pct(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export function RoundCard({
  roundIndex,
  topic,
  summary,
  keywords,
  lanes,
  detail,
  defaultExpanded = false,
}: RoundCardProps): JSX.Element {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <article className={`round-card${expanded ? " is-open" : ""}`}>
      <div className="round-card-head">
        <div className="round-card-titles">
          <span className="round-card-index">第 {roundIndex} 轮</span>
          <h4>{topic || "未命名主题"}</h4>
        </div>
        {detail ? (
          <button
            type="button"
            className="round-card-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "收起详情 ▴" : "展开详情 ▾"}
          </button>
        ) : null}
      </div>
      <p className="round-card-summary">{summary}</p>
      {lanes && lanes.length > 0 ? (
        <ul className="round-card-lanes">
          {lanes.map((lane) => (
            <li key={lane.key} className={`round-lane round-lane-${lane.tone}`}>
              <span className="round-lane-label">{lane.label}</span>
              <span
                className="round-lane-bar"
                style={{ "--lane-fill": lane.value == null ? 0 : `${Math.round(lane.value * 100)}%` } as CSSProperties}
              >
                <span className="round-lane-fill" />
              </span>
              <span className="round-lane-value">
                {pct(lane.value)}
                {lane.estimated && lane.value != null ? (
                  <small> 摘要估计</small>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {keywords.length > 0 ? (
        <div className="round-card-keywords">
          {keywords.map((keyword) => (
            <span key={keyword} className="keyword-tag">{keyword}</span>
          ))}
        </div>
      ) : null}
      {expanded && detail ? <div className="round-card-body">{detail}</div> : null}
    </article>
  );
}

export function researchLanes(round: ResearchRoundSummaryDTO): RoundCardProps["lanes"] {
  return [
    {
      key: "bull",
      label: "多方",
      value: round.bull_estimated_conviction,
      tone: "bull",
      estimated: true,
    },
    {
      key: "bear",
      label: "空方",
      value: round.bear_estimated_conviction,
      tone: "bear",
      estimated: true,
    },
  ];
}

export function riskLanes(
  _round: RiskRoundSummaryDTO,
  convictions: { aggressive: number | null; neutral: number | null; conservative: number | null } | null,
): RoundCardProps["lanes"] {
  const rows: NonNullable<RoundCardProps["lanes"]> = [
    { key: "aggressive", label: "激进", value: convictions?.aggressive ?? null, tone: "bull" },
    { key: "neutral", label: "中性", value: convictions?.neutral ?? null, tone: "neutral" },
    { key: "conservative", label: "保守", value: convictions?.conservative ?? null, tone: "bear" },
  ];
  return rows;
}
