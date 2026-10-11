import { ModelFailureNotice } from "./ModelFailureNotice";
import { useEffect, useId, useRef, useState } from "react";
import { useReaderAgent, useReaderProcess } from "../../hooks/useReaderProcess";
import type { RunStreamStatus } from "../../hooks/useRunStream";
import { NativeReader } from "./NativeReader";
import { ReaderAgentOutput } from "./ReaderAgentOutput";
import { AGENT_LABELS, AGENT_PURPOSE, AGENT_PRODUCTS, outputLabel } from "../../domain/readerExplanation";
import type { AgentKey, ResearchRecordResponseDTO } from "../../api/contracts";
import { rolesForProfile, type ReducerState, type RoleStatus } from "../../state/model";

const STATUS_LABELS: Record<RoleStatus, string> = {
  pending: "等待", running: "执行中", completed: "已完成", failed: "失败",
  cancelled: "已取消", interrupted: "已中断", skipped: "已跳过", not_reached: "未到达",
};

/** The saved native record is the sole research source for an evidence_v1 run. */
export function NativeResearchPage({ runId, ticker, status, state, response, mode = "company_research", loading, error,
  onOpenAudit, onCancel, onRetry, onResume, onNewResearch, streamStatus = "error" }: {
  streamStatus?: RunStreamStatus;
  runId: string; ticker: string; status: string; state: ReducerState | null; mode?: string | null;
  response: ResearchRecordResponseDTO | null; loading: boolean; error: boolean;
  onOpenAudit(): void; onCancel(): void; onRetry(): void; onResume(): void; onNewResearch(): void;
}): JSX.Element {
  const [role, setRole] = useState<AgentKey | null>(null);
  const reviewId = useId();
  const review = useRef<HTMLElement>(null);
  const returnTrigger = useRef<HTMLButtonElement | null>(null);
  const revealReview = () => {
    review.current?.scrollIntoView({ block: "start", behavior: "instant" });
    review.current?.focus({ preventScroll: true });
  };
  useEffect(() => {
    if (role) revealReview();
  }, [role]);
  const openRole = (key: AgentKey, trigger: HTMLButtonElement) => {
    returnTrigger.current = trigger;
    if (role === key) revealReview();
    else setRole(key);
  };
  const closeRole = () => {
    setRole(null);
    returnTrigger.current?.focus();
  };
  const process = useReaderProcess(runId, state?.meta.run_id === runId ? state.meta.latest_sequence : 0, status, streamStatus, Object.values(state?.roles ?? {}).map(r=>r.status).join(","));
  const agent = useReaderAgent(runId, role, process.response);
  const completed = status === "completed";
  const failed = status === "failed";
  const stopped = status === "cancelled" || status === "interrupted";
  const currentState = state?.meta.run_id === runId ? state : null;
  const unified = (process.response?.workflow_version ?? currentState?.meta.native_workflow_version) === "evidence-production-v7";
  const published = response?.state === "ready" && response.run_id === runId && response.record.construction === "native" && !!response.record.assessment;
  const incompatibleRecord = response?.state === "ready" &&
    (response.record.construction !== "native" || !response.record.assessment);
  return <section className="native-research-page" aria-label="证据研究" data-run={runId}>
    <header className="reader-surface-head">
      <div><span className="eyebrow">证据研究</span><h2>{ticker}</h2></div>
      {completed || failed || stopped ? <button type="button" onClick={onOpenAudit}>技术诊断与执行记录</button> : null}
    </header>
    <ModelFailureNotice failures={process.response?.model_failures ?? []} />
    {completed || published ? <section data-main-summary="native_research">
      {incompatibleRecord ? <p role="status">保存记录未包含原生研究判断，无法展示本次研究简报。</p> :
        response?.state === "ready" && response.run_id === runId && response.record.run_id === runId ? <NativeReader key={runId} runId={runId} record={response.record} process={process.response} processError={process.error} retryProcess={process.retry}/> : <p role="status">{loading ? "正在读取保存的研究记录…" : error ? "研究记录暂时无法读取。" : "本次没有合格的已发布研究记录。"}</p>}
      {!loading && !error && response === null ? <p role="status">尚未读取到本次运行的证据记录。</p> : null}
    </section> : <section className="native-progress">
      <header><span className="qr-eyebrow">研究进行中</span><h3>{failed ? "本次研究未完成" : stopped ? (status === "interrupted" ? "研究已中断" : "研究已取消") : "正在把证据整理成可核查的回答"}</h3>
      <p>冻结证据 → 三个专项提出假设 → 独立挑战 → 代码核查 → {unified ? "被质疑专项回应 → 投资吸引力判断。" : "综合回答。"}</p><p className="qr-meta">角色执行完成不代表证据充分。研究正文通过发布校验后才展示。</p></header>
      {process.error ? <p role="status">过程读取暂时失败。<button onClick={process.retry}>重试读取</button></p> : null}
      {rolesForProfile("evidence_v1", process.response?.workflow_version ?? currentState?.meta.native_workflow_version).map((r,i) => { const key=r.node_id as AgentKey, meta=process.response?.roles.find(x=>x.role_key===key); return <article className="qr-process-step" key={r.actor_id}><span className="qr-step-index">{String(i+1).padStart(2,"0")}</span><div><h3>{AGENT_LABELS[key]} · {currentState?.roles[r.actor_id] ? STATUS_LABELS[currentState.roles[r.actor_id].status] : "未记录"}</h3><p>{meta?.purpose ?? AGENT_PURPOSE[key]}</p><p className="qr-meta">本步产物：{AGENT_PRODUCTS[key]}</p><p className="qr-meta">{meta ? outputLabel(meta.output_availability,meta.reason_code) : "正在读取保存状态"}</p><button type="button" aria-expanded={role === key} aria-controls={role ? reviewId : undefined} onClick={event=>openRole(key,event.currentTarget)}>查看本环节与保存产物 →</button></div></article>; })}
      {role ? <section className="native-role-review" id={reviewId} ref={review} tabIndex={-1} aria-label="所选环节详情"><button type="button" onClick={closeRole}>收起角色回顾</button><ReaderAgentOutput role={role} process={process.response} output={agent.response} error={agent.error || process.error} record={null} entity={null} onRole={setRole} onInspect={()=>{}} onLocate={()=>{}} onRetry={()=>{agent.retry();if(process.error)process.retry();}}/></section> : null}
      {failed && mode === "company_research" ? <button type="button" onClick={onRetry}>重试研究</button> : null}
      {status === "interrupted" ? <button type="button" onClick={onResume}>恢复研究</button> : null}
      {!failed && !stopped ? <button type="button" onClick={onCancel} disabled={status === "cancel_requested"}>{status === "cancel_requested" ? "正在取消" : "取消研究"}</button> : null}
    </section>}
    {completed || failed || stopped ? <button type="button" onClick={onNewResearch}>{mode && mode !== "company_research" ? "新建公司研究" : "新建研究"}</button> : null}
  </section>;
}
