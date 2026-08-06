/**
 * L1 debate journey timeline.
 *
 * Compact, static reading skeleton shown below the DecisionBrief once a run
 * is terminal. Six stages map 1:1 to the workflow projection; research/risk
 * carry measured round counts from turn.completed events. The insight strip
 * only surfaces committed typed outputs — conviction estimates belong to the
 * L2 summary cards, never here. Clicking a stage selects it for the L2 detail
 * panel (mounted by the parent).
 */
import type { DebateJourneyDTO, JourneyStageId, JourneyStageStatus } from "../../api/contracts";

export interface DebateTimelineProps {
  journey: DebateJourneyDTO;
  selectedStage: JourneyStageId | null;
  onStageToggle(stage: JourneyStageId): void;
}

interface StageView {
  id: JourneyStageId;
  label: string;
  shortLabel: string;
  rounds: number | null;
  status: JourneyStageStatus;
}

const STAGE_LABELS: Record<JourneyStageId, { label: string; short: string }> = {
  analysts: { label: "分析师", short: "分析师" },
  evidence: { label: "证据门", short: "证据门" },
  research: { label: "研究辩论", short: "研究辩论" },
  trading: { label: "交易", short: "交易" },
  risk: { label: "风险辩论", short: "风险辩论" },
  portfolio: { label: "裁决", short: "裁决" },
};

const STATUS_GLYPH: Record<JourneyStageStatus, string> = {
  completed: "✓",
  running: "•",
  failed: "✕",
  cancelled: "⊘",
  interrupted: "⊘",
  skipped: "–",
  waiting: "",
};

const RISK_DISAGREEMENT_LABELS: Record<string, string> = {
  none: "高度一致",
  tight: "轻微分歧",
  wide: "明显分歧",
  mixed: "多空混杂",
  unavailable: "暂无风险共识数据",
};

function riskConsensusLabel(conviction: number | null, disagreement: string): string {
  if (conviction == null) return RISK_DISAGREEMENT_LABELS[disagreement] ?? "风险共识不可用";
  if (conviction >= 0.4) return "共识偏激进";
  if (conviction <= -0.4) return "共识偏保守";
  return "中性偏谨慎";
}

export function DebateTimeline({
  journey,
  selectedStage,
  onStageToggle,
}: DebateTimelineProps): JSX.Element {
  const stages: StageView[] = journey.stages.map((stage) => ({
    id: stage.stage_id,
    label: STAGE_LABELS[stage.stage_id]?.label ?? stage.stage_id,
    shortLabel: STAGE_LABELS[stage.stage_id]?.short ?? stage.stage_id,
    rounds: stage.rounds,
    status: stage.status,
  }));

  return (
    <section className="journey" aria-label="辩论历程">
      <h2 className="journey-title">辩论历程</h2>
      <ol className="journey-track">
        {stages.map((stage, index) => {
          const isSelected = selectedStage === stage.id;
          const clickable = stage.status !== "waiting";

          return (
            <li key={stage.id} className="journey-cell">
              {index > 0 ? <span className="journey-arrow" aria-hidden="true">→</span> : null}
              <button
                type="button"
                className={`journey-node journey-node-${stage.status}${
                  isSelected ? " is-selected" : ""
                }`}
                disabled={!clickable}
                aria-pressed={isSelected}
                aria-label={`${stage.label}：${stage.status}`}
                onClick={() => onStageToggle(stage.id)}
              >
                <span className="journey-glyph">{STATUS_GLYPH[stage.status]}</span>
                <span className="journey-label">{stage.shortLabel}</span>
                {stage.rounds ? (
                  <span className="journey-rounds">{stage.rounds} 轮</span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ol>

      <div className="journey-insights">
        <div className="journey-insight">
          <span className="journey-insight-label">研究评级</span>
          <strong>{journey.research_rating ?? "—"}</strong>
          {journey.disagreement_count > 0 ? (
            <span className="journey-insight-note">
              {journey.disagreement_count} 项关键分歧
            </span>
          ) : null}
        </div>
        <div className="journey-insight">
          <span className="journey-insight-label">风险共识</span>
          <strong>
            {riskConsensusLabel(
              journey.risk_consensus.conviction,
              journey.risk_consensus.disagreement,
            )}
          </strong>
          {journey.risk_consensus.abstained_roles.length > 0 ? (
            <span className="journey-insight-note">
              {journey.risk_consensus.abstained_roles.length} 方弃权
            </span>
          ) : null}
        </div>
      </div>
      <p className="journey-hint">点击任意阶段查看该阶段的详细过程</p>
    </section>
  );
}
