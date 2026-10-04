import type { ResearchRecordResponseDTO } from "../../api/contracts";
import { ROLE_LABELS_ZH } from "../../domain/roles";
import { NATIVE_ROLE_REGISTRY, type ReducerState, type RoleStatus } from "../../state/model";
import { ResearchRecordSection } from "./ResearchRecordSection";

const STATUS_LABELS: Record<RoleStatus, string> = {
  pending: "等待", running: "执行中", completed: "已完成", failed: "失败",
  cancelled: "已取消", interrupted: "已中断", skipped: "已跳过", not_reached: "未到达",
};

/** The saved native record is the sole research source for an evidence_v1 run. */
export function NativeResearchPage({ runId, ticker, status, state, response, loading, error,
  onOpenAudit, onCancel, onRetry, onResume, onNewResearch }: {
  runId: string; ticker: string; status: string; state: ReducerState | null;
  response: ResearchRecordResponseDTO | null; loading: boolean; error: boolean;
  onOpenAudit(): void; onCancel(): void; onRetry(): void; onResume(): void; onNewResearch(): void;
}): JSX.Element {
  const completed = status === "completed";
  const failed = status === "failed";
  const stopped = status === "cancelled" || status === "interrupted";
  const currentState = state?.meta.run_id === runId ? state : null;
  const incompatibleRecord = response?.state === "ready" &&
    (response.record.construction !== "native" || !response.record.assessment);
  return <section className="native-research-page" aria-label="证据研究" data-run={runId}>
    <header className="reader-surface-head">
      <div><span className="eyebrow">证据研究</span><h2>{ticker}</h2></div>
      <button type="button" onClick={onOpenAudit}>打开审计中心</button>
    </header>
    {completed ? <section data-main-summary="native_research">
      {incompatibleRecord ? <p role="status">保存记录未包含原生研究判断，无法展示本次研究简报。</p> :
        <ResearchRecordSection runId={runId} response={response} loading={loading} error={error} />}
      {!loading && !error && response === null ? <p role="status">尚未读取到本次运行的证据记录。</p> : null}
    </section> : <>
      <h3>{failed ? "本次研究未完成" : stopped ? (status === "interrupted" ? "研究已中断" : "研究已取消") : "正在整理研究证据"}</h3>
      <p className="record-meta">{failed || stopped ? "未发布研究判断；可在审计中心检查已保存的过程。" : "完成核查和综合后发布研究判断；角色执行状态不代表证据完整。"}</p>
      <ul aria-label="研究阶段状态">
        {NATIVE_ROLE_REGISTRY.map((role) => <li key={role.actor_id}>
          {ROLE_LABELS_ZH[role.actor_id]} · {currentState?.roles[role.actor_id]
            ? STATUS_LABELS[currentState.roles[role.actor_id].status] : "未记录"}
        </li>)}
      </ul>
      {failed ? <button type="button" onClick={onRetry}>重试研究</button> : null}
      {status === "interrupted" ? <button type="button" onClick={onResume}>恢复研究</button> : null}
      {!failed && !stopped ? <button type="button" onClick={onCancel} disabled={status === "cancel_requested"}>{status === "cancel_requested" ? "正在取消" : "取消研究"}</button> : null}
    </>}
    {completed || failed || stopped ? <button type="button" onClick={onNewResearch}>新建研究</button> : null}
  </section>;
}
