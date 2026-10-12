import { useEffect, useState } from "react";
import { ModelFailureNotice } from "./ModelFailureNotice";
import { useReaderAgent, useReaderProcess } from "../../hooks/useReaderProcess";
import type { RunStreamStatus } from "../../hooks/useRunStream";
import { NativeReader } from "./NativeReader";
import { ReaderAgentOutput } from "./ReaderAgentOutput";
import { ResearchFlow } from "./ResearchFlow";
import type { AgentKey, ResearchRecordResponseDTO } from "../../api/contracts";
import type { ReducerState } from "../../state/model";
import "../../styles/nativeReader.css";

/** The saved native record is the sole research source for an evidence_v1 run. */
export function NativeResearchPage({ runId, ticker, status, state, response, mode = "company_research", loading, error, retry,
  onOpenAudit, onCancel, onRetry, onResume, onNewResearch, streamStatus = "error" }: {
  streamStatus?: RunStreamStatus;
  runId: string; ticker: string; status: string; state: ReducerState | null; mode?: string | null;
  response: ResearchRecordResponseDTO | null; loading: boolean; error: boolean; retry?(): void;
  onOpenAudit(): void; onCancel(): void; onRetry(): void; onResume(): void; onNewResearch(): void;
}): JSX.Element {
  const [role, setRole] = useState<AgentKey | null>(null);
  useEffect(() => { setRole(null); }, [runId]);
  const currentState = state?.meta.run_id === runId ? state : null;
  const process = useReaderProcess(runId, currentState?.meta.latest_sequence ?? 0, status, streamStatus,
    Object.values(currentState?.roles ?? {}).map(r=>r.status).join(","));
  const agent = useReaderAgent(runId, role, process.response);
  const completed = status === "completed";
  const failed = status === "failed";
  const stopped = status === "cancelled" || status === "interrupted";
  const record = response?.state === "ready" && response.run_id === runId && response.record.run_id === runId
    && response.record.construction === "native" && response.record.assessment ? response.record : null;
  const incompatibleRecord = response?.state === "ready" && !record;
  const unpublished = response?.state === "unavailable" && response.run_id === runId && response.reason_code === "not_published";
  const title = failed ? "本次研究未完成" : stopped ? status === "interrupted" ? "研究已中断" : "研究已取消"
    : status === "cancel_requested" ? "正在取消研究" : "正在形成可核查的研究判断";
  const statusLabel = failed ? "研究已停止" : stopped ? title : status === "cancel_requested" ? "取消中" : "研究执行中";
  return <section className="native-research-page" aria-label="证据研究" data-run={runId}>
    <header className="reader-surface-head">
      <div><span className="eyebrow">公司证据研究</span><h2>{ticker}</h2></div>
      {completed || failed || stopped ? <button type="button" onClick={onOpenAudit}>研究检查与审计 ↗</button> : null}
    </header>
    <ModelFailureNotice failures={process.response?.model_failures ?? []} />
    {completed || record ? <section data-main-summary="native_research">
      {record ? <NativeReader key={runId} runId={runId} record={record} process={process.response} processError={process.error} retryProcess={process.retry}/> :
        <p role="status">{incompatibleRecord ? "保存记录未包含原生研究判断，无法展示本次研究简报。" : loading ? "正在读取保存的研究记录…" : error ? "研究记录暂时无法读取。" : unpublished ? "本次未生成可读最终报告。" : "本次没有合格的已发布研究记录。"}
          {error && retry ? <button onClick={retry}>重试读取记录</button> : null}</p>}
    </section> : <section className="native-progress">
      <header className="native-run-overview" data-stopped={failed || stopped}>
        <div><span className="qr-eyebrow">本次运行</span><h3>{title}</h3></div><span className="native-run-badge">{statusLabel}</span>
        <p>{failed ? "已保存的专项提议可以保留，但只有通过完整校验的研究正文才能发布。请在执行记录中查看停止原因。" : stopped ? "本次执行已停止。以下保留真实执行状态与产物保存状态。" : "先冻结证据，各专项独立形成假设，再经质疑、核查与综合判断。"}</p>
        {(failed || stopped) ? <p className="native-publication-state" role="status">{loading ? "正在核对保存记录…" : error ? "保存记录暂时无法读取，尚不能确认报告是否已发布。" : unpublished ? "本次未生成可读最终报告。" : "尚未确认本次是否存在合格的已发布研究记录。"}
          {error && retry ? <button onClick={retry}>重试读取记录</button> : null}</p> : <p className="qr-meta">执行状态与公开产物状态分别记录；研究正文通过发布校验后展示。</p>}
      </header>
      {process.error ? <p className="qr-fault" role="status">过程读取暂时失败。<button onClick={process.retry}>重试读取</button></p> : null}
      <ResearchFlow key={runId} process={process.response} workflowVersion={currentState?.meta.native_workflow_version}
        state={currentState} runStatus={status} selectedRole={role} onSelect={setRole} onClose={()=>setRole(null)}>
        {role ? <ReaderAgentOutput role={role} process={process.response} output={agent.response} error={agent.error || process.error}
          record={null} runStatus={status} entity={null} onRole={setRole} onInspect={()=>{}} onLocate={()=>{}}
          onRetry={()=>{agent.retry();if(process.error)process.retry();}}/> : null}
      </ResearchFlow>
      <footer className="native-run-actions"><span>已保存记录保留 · 阅读不重新调用模型</span><div>
        {failed && mode === "company_research" ? <button type="button" onClick={onRetry}>重试研究</button> : null}
        {status === "interrupted" ? <button type="button" onClick={onResume}>恢复研究</button> : null}
        {!failed && !stopped ? <button type="button" onClick={onCancel} disabled={status === "cancel_requested"}>{status === "cancel_requested" ? "正在取消" : "取消研究"}</button> : null}
      </div></footer>
    </section>}
    {completed || failed || stopped ? <button className="native-new-research" type="button" onClick={onNewResearch}>{mode && mode !== "company_research" ? "新建公司研究" : "新建研究"}</button> : null}
  </section>;
}
