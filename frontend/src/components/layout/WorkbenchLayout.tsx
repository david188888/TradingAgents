import { useState } from "react";
import { Controls } from "../controls/Controls";
import { RunHistory } from "../history/RunHistory";
import { NativeResearchPage } from "../reader/NativeResearchPage";
import { AuditCenter } from "../reader/AuditCenter";
import { useWorkbenchStore } from "../../state/WorkbenchStore";
import { useRunHistory } from "../../hooks/useRunHistory";
import { useResearchRecord } from "../../hooks/useResearchRecord";
import { cancelRun, retryRun, resumeRun } from "../../api/client";

/** One workbench for current Insight research, including saved stage evidence. */
export function WorkbenchLayout(): JSX.Element {
  const { run_id, stream, selectRun, reconnectRun } = useWorkbenchStore();
  const history = useRunHistory();
  const [auditOpen, setAuditOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);
  const state = stream.state?.meta.run_id === run_id ? stream.state : null;
  const status = state?.meta.status ?? "created";
  const terminal = ["completed", "failed", "cancelled", "interrupted"].includes(status);
  const record = useResearchRecord(terminal ? run_id : null);
  const act = async (kind: "cancel" | "retry" | "resume") => {
    if (!run_id) return;
    setActionError(null);
    try {
      if (kind === "cancel") await cancelRun(run_id);
      else if (kind === "retry") selectRun((await retryRun(run_id)).run_id);
      else { await resumeRun(run_id); reconnectRun(run_id); }
      await history.refresh();
    } catch (error) { setActionError(error instanceof Error ? error.message : String(error)); }
  };
  return <div className="app">
    <header className="topbar"><div className="brand"><span className="brand-mark">TA</span>TradingAgents <span className="brand-sub">Research Console</span></div><div className="top-meta"><button className="audit-toggle" aria-expanded={!sidebarCollapsed} onClick={() => setSidebarCollapsed(value => !value)}>{sidebarCollapsed ? "展开研究配置" : "收起研究配置"}</button><span className="local-pill">● localhost</span><span>公司证据研究 · V9</span></div></header>
    <div className={`layout${sidebarCollapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar" hidden={sidebarCollapsed}><Controls refreshHistory={history.refresh}/>
        <RunHistory {...history} onLoadMore={() => void history.loadMore()} clearing={clearing}
          onDeleteRun={id => { void history.removeRun(id).then(removed => { if (removed && id === run_id) selectRun(null); }); }}
          onClearHistory={() => { setClearing(true); void history.clearAll().then(result => { if (result?.removed) selectRun(null); }).finally(() => setClearing(false)); }}/>
      </aside>
      <main className="main">
        {actionError ? <p role="alert">{actionError}</p> : null}
        {run_id && state ? <NativeResearchPage key={run_id} runId={run_id} ticker={state.meta.ticker} status={status}
          state={state} {...record} streamStatus={stream.status} onOpenAudit={() => setAuditOpen(true)}
          onCancel={() => void act("cancel")} onRetry={() => void act("retry")} onResume={() => void act("resume")}
          onNewResearch={() => selectRun(null)}/> : <section className="reader-empty"><h2>{run_id ? "正在读取研究记录…" : "选择一次研究，或输入股票代码开始"}</h2>{stream.error ? <p role="alert">{stream.error.message}</p> : null}</section>}
      </main>
    </div>
    {run_id ? <AuditCenter key={run_id} runId={run_id} open={auditOpen} context={null} returnFocus={null} onClose={() => setAuditOpen(false)}/> : null}
  </div>;
}
