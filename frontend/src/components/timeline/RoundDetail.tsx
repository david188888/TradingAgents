/**
 * L3 full-text round detail.
 *
 * Mounted lazily inside a RoundCard when the user expands it. Each lane loads
 * its own turn output artifact (the same business_delta the summary LLM read)
 * via useArtifact and runs it through the same extractResponse() the live
 * timeline uses, so the full text is byte-identical to what the agent emitted.
 * Research debates render two columns (bull/bear); risk debates three columns
 * (aggressive/neutral/conservative). Narrow viewports collapse to a single
 * stacked column via CSS.
 */
import { useArtifact } from "../../hooks/useArtifact";
import { extractResponse } from "../../domain/responseExtractor";
import { SafeMarkdown } from "../shared/SafeMarkdown";

export interface LaneSpec {
  actor_id: string;
  lane: string;
  label: string;
  tone: "bull" | "bear" | "neutral" | "risk";
  artifact_id: string;
}

export interface RoundDetailProps {
  runId: string;
  lanes: LaneSpec[];
}

function LaneBody({ runId, lane }: { runId: string; lane: LaneSpec }): JSX.Element {
  const { content, loading, error } = useArtifact(runId, lane.artifact_id);

  let text: string | null = null;
  if (content) {
    try {
      const delta = JSON.parse(content) as Record<string, unknown>;
      text = extractResponse(lane.actor_id, delta).text;
    } catch {
      text = null;
    }
  }

  return (
    <div className={`round-detail-lane round-detail-${lane.tone}`}>
      <div className="round-detail-lane-head">
        <span className="round-detail-lane-label">{lane.label}</span>
      </div>
      <div className="round-detail-lane-body">
        {loading ? (
          <p className="placeholder">读取发言中…</p>
        ) : error ? (
          <p className="placeholder">无法读取发言：{error}</p>
        ) : text ? (
          <SafeMarkdown content={text} mode="prose" />
        ) : (
          <p className="placeholder">该发言没有可显示的文本。</p>
        )}
      </div>
    </div>
  );
}

export function RoundDetail({ runId, lanes }: RoundDetailProps): JSX.Element {
  const laneCountClass =
    lanes.length >= 3 ? " round-detail-three" : " round-detail-two";
  return (
    <div className={`round-detail${laneCountClass}`}>
      {lanes.map((lane) => (
        <LaneBody key={lane.lane} runId={runId} lane={lane} />
      ))}
    </div>
  );
}
