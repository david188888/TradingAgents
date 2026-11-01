import { InsightReader } from "./InsightReader";
import type { AgentKey, ReaderAgentDTO, ReaderProcessDTO } from "../../api/contracts";
import { AGENT_LABELS, outputLabel, STATUS_LABELS } from "../../domain/readerExplanation";

/** Show only the saved current Insight stage; reading never dispatches models. */
export function ReaderAgentOutput({ role, process, output, error, onRetry }: {
  role: AgentKey; process: ReaderProcessDTO | null; output: ReaderAgentDTO | null; error: boolean;
  runStatus?: string; onRole(role: AgentKey): void; onRetry(): void;
}) {
  const meta = process?.roles.find(item => item.role_key === role);
  return <section className="qr-agent-review" aria-label="Agent 产物回顾">
    <h2>{AGENT_LABELS[role]}</h2><p>{meta?.purpose}</p><p>{STATUS_LABELS[meta?.status ?? ""] ?? "状态未记录"}</p>{output ? <p>{outputLabel(output.availability)}</p> : null}
    {error ? <p role="status">产物暂时无法读取。<button onClick={onRetry}>重试读取</button></p> : output?.insight_record ?
      <InsightReader record={output.insight_record} role={role}/> : <p role="status">本环节尚无合格的已保存研究产物。</p>}
    {output?.input_description ? <details><summary>输入范围说明</summary><p>{output.input_description}</p></details> : null}
  </section>;
}
