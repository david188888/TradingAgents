/**
 * L2 stage detail container.
 *
 * Mounted below the DebateTimeline when a stage is selected. Research/risk
 * stages render per-round RoundCards driven by the committed debate summary
 * artifact; expanding a card lazy-mounts L3 (RoundDetail) which loads the
 * exact turn output artifacts for each lane and renders them through the same
 * extractResponse() path as the live timeline. The verdict/other stages point
 * at the audit reader. When the summary is still generating or generation
 * failed, the panel says so plainly — full text remains available via the
 * audit reader.
 */
import type {
  JourneyStageId,
  ResearchRoundSummaryDTO,
  RiskRoundSummaryDTO,
  RunViewEnvelopeDTO,
} from "../../api/contracts";
import type { ReducerState, Turn } from "../../state/model";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { useArtifact } from "../../hooks/useArtifact";
import { extractResponse } from "../../domain/responseExtractor";
import { ROLE_LABELS_ZH } from "../../domain/roles";
import { SafeMarkdown } from "../shared/SafeMarkdown";
import { RoundCard, researchLanes, riskLanes } from "./RoundCard";
import { RoundDetail, type LaneSpec } from "./RoundDetail";

export interface StageDetailProps {
  stageId: JourneyStageId;
  envelope: RunViewEnvelopeDTO;
  runId: string;
  onOpenAudit(): void;
  onRoleSelected?: (actorId: string) => void;
}

const STAGE_TITLES: Record<JourneyStageId, string> = {
  analysts: "分析师团队",
  evidence: "证据门",
  research: "研究辩论",
  trading: "交易计划",
  risk: "风险辩论",
  portfolio: "组合裁决",
};

const STAGE_ACTORS: Record<JourneyStageId, string[]> = {
  analysts: ["analyst.market", "analyst.sentiment", "analyst.news", "analyst.fundamentals"],
  evidence: ["evidence.steward"],
  research: ["researcher.bull", "researcher.bear", "manager.research"],
  trading: ["trader"],
  risk: ["risk.aggressive", "risk.neutral", "risk.conservative"],
  portfolio: ["manager.portfolio"],
};

function latestTurnForActor(state: ReducerState, actorId: string): Turn | null {
  const roleTurnId = state.roles[actorId]?.latest_turn_id;
  if (roleTurnId && state.turns[roleTurnId]) return state.turns[roleTurnId];
  return Object.values(state.turns)
    .filter((turn) => turn.actor_id === actorId)
    .sort((left, right) => right.turn_index - left.turn_index || right.turn_id.localeCompare(left.turn_id))[0] ?? null;
}

function StageTurnOutput({
  runId,
  turn,
  onSelect,
}: {
  runId: string;
  turn: Turn;
  onSelect(): void;
}): JSX.Element {
  const { content, loading, error } = useArtifact(runId, turn.artifact_id ?? null);
  let text: string | null = null;
  let badge: string | null = null;
  if (content) {
    try {
      const parsed = JSON.parse(content) as Record<string, unknown>;
      ({ text, badge } = extractResponse(turn.actor_id, parsed));
    } catch {
      text = null;
    }
  }

  return (
    <article className="stage-turn-output">
      <button type="button" className="stage-turn-select" onClick={onSelect}>
        <span className="stage-turn-role">{ROLE_LABELS_ZH[turn.actor_id] ?? turn.actor_id}</span>
        <span className="stage-turn-open">查看审计</span>
      </button>
      {badge ? <span className="stage-turn-badge">{badge}</span> : null}
      {loading ? <p className="placeholder">正在读取角色输出…</p> : null}
      {error ? <p className="placeholder">无法读取角色输出：{error}</p> : null}
      {!loading && !error && text ? <SafeMarkdown content={text} mode="prose" /> : null}
      {!loading && !error && !text ? <p className="placeholder">该角色没有可显示的结构化输出。</p> : null}
    </article>
  );
}

function StageTurnOutputs({
  stageId,
  state,
  runId,
  onRoleSelected,
}: {
  stageId: JourneyStageId;
  state: ReducerState | null;
  runId: string;
  onRoleSelected?: (actorId: string) => void;
}): JSX.Element {
  const turns = state
    ? STAGE_ACTORS[stageId]
        .map((actorId) => latestTurnForActor(state, actorId))
        .filter((turn): turn is Turn => turn !== null)
    : [];
  if (turns.length === 0) {
    return <p className="placeholder stage-detail-pending">尚未回放到该阶段的发言事实。</p>;
  }
  return (
    <div className="stage-turn-outputs">
      {turns.map((turn) => (
        <StageTurnOutput
          key={turn.turn_id}
          runId={runId}
          turn={turn}
          onSelect={() => onRoleSelected?.(turn.actor_id)}
        />
      ))}
    </div>
  );
}

const RESEARCH_LANE_META: Record<string, { actor_id: string; label: string; tone: LaneSpec["tone"] }> = {
  bull: { actor_id: "researcher.bull", label: "多方分析师", tone: "bull" },
  bear: { actor_id: "researcher.bear", label: "空方分析师", tone: "bear" },
};

const RISK_LANE_META: Record<string, { actor_id: string; label: string; tone: LaneSpec["tone"] }> = {
  aggressive: { actor_id: "risk.aggressive", label: "激进方", tone: "bull" },
  neutral: { actor_id: "risk.neutral", label: "中性方", tone: "neutral" },
  conservative: { actor_id: "risk.conservative", label: "保守方", tone: "bear" },
};

function lanesFromSources(
  sources: Record<string, string | undefined> | undefined,
  meta: Record<string, { actor_id: string; label: string; tone: LaneSpec["tone"] }>,
): LaneSpec[] {
  if (!sources) return [];
  return Object.entries(sources)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string")
    .map(([lane, artifact_id]) => ({
      lane,
      artifact_id,
      ...meta[lane],
    }))
    .filter((lane) => lane.actor_id !== undefined);
}

function SummaryState({
  availability,
  hasValue,
}: {
  availability: "ready" | "pending" | "unavailable";
  hasValue: boolean;
}): JSX.Element | null {
  if (availability === "pending") {
    return <p className="placeholder stage-detail-pending">摘要生成中，可在审计阅读器中查看完整发言。</p>;
  }
  if (availability === "unavailable" || !hasValue) {
    return <p className="placeholder stage-detail-pending">暂无辩论摘要，可在审计阅读器中查看完整发言。</p>;
  }
  return null;
}

function ResearchRounds({
  rounds,
  runId,
}: {
  rounds: ResearchRoundSummaryDTO[];
  runId: string;
}): JSX.Element {
  return (
    <div className="stage-rounds">
      {rounds.map((round) => {
        const lanes = lanesFromSources(round.sources, RESEARCH_LANE_META);
        return (
          <RoundCard
            key={round.round_index}
            roundIndex={round.round_index}
            topic={round.topic}
            summary={round.summary}
            keywords={round.keywords}
            lanes={researchLanes(round)}
            detail={lanes.length > 0 ? <RoundDetail runId={runId} lanes={lanes} /> : undefined}
          />
        );
      })}
    </div>
  );
}

function RiskRounds({
  rounds,
  runId,
}: {
  rounds: RiskRoundSummaryDTO[];
  runId: string;
}): JSX.Element {
  return (
    <div className="stage-rounds">
      {rounds.map((round) => {
        const lanes = lanesFromSources(round.sources, RISK_LANE_META);
        return (
          <RoundCard
            key={round.round_index}
            roundIndex={round.round_index}
            topic={round.topic}
            summary={round.summary}
            keywords={round.keywords}
            lanes={riskLanes(round, null)}
            detail={lanes.length > 0 ? <RoundDetail runId={runId} lanes={lanes} /> : undefined}
          />
        );
      })}
    </div>
  );
}

export function StageDetail({
  stageId,
  envelope,
  runId,
  onOpenAudit,
  onRoleSelected,
}: StageDetailProps): JSX.Element {
  const { stream } = useWorkbenchStore();
  const summary = envelope.view.debate_summary;
  const value = summary.value;

  let body: JSX.Element;
  if (stageId === "research") {
    const hasRounds = !!value && value.research_debate.length > 0;
    body = (
      <>
        {value?.global_summary ? (
          <p className="stage-detail-global">{value.global_summary}</p>
        ) : null}
        {!hasRounds ? (
          <>
            <SummaryState availability={summary.availability} hasValue={!!value} />
            <StageTurnOutputs stageId={stageId} state={stream.state} runId={runId} onRoleSelected={onRoleSelected} />
          </>
        ) : (
          <ResearchRounds rounds={value!.research_debate} runId={runId} />
        )}
      </>
    );
  } else if (stageId === "risk") {
    const hasRounds = !!value && value.risk_debate.length > 0;
    body = (
      <>
        {!hasRounds ? (
          <>
            <SummaryState availability={summary.availability} hasValue={!!value} />
            <StageTurnOutputs stageId={stageId} state={stream.state} runId={runId} onRoleSelected={onRoleSelected} />
          </>
        ) : (
          <RiskRounds rounds={value!.risk_debate} runId={runId} />
        )}
      </>
    );
  } else {
    body = <StageTurnOutputs stageId={stageId} state={stream.state} runId={runId} onRoleSelected={onRoleSelected} />;
  }

  return (
    <section className="stage-detail" aria-label={`${STAGE_TITLES[stageId]}详情`}>
      <header className="stage-detail-head">
        <h3>{STAGE_TITLES[stageId]}</h3>
        <button type="button" className="stage-detail-audit" onClick={onOpenAudit}>
          查看完整审计记录 →
        </button>
      </header>
      {body}
    </section>
  );
}
