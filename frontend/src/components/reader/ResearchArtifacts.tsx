import type { AgentKey, ReaderProcessDTO, ReaderRoleDTO } from "../../api/contracts";
import { AGENT_LABELS, outputLabel, STATUS_LABELS } from "../../domain/readerExplanation";
import { useReaderAgent } from "../../hooks/useReaderProcess";
import { InsightReader } from "./InsightReader";

const SPECIALISTS = ["operating_quality", "event_context", "market_context"] as const;
const REVIEW_ROLES: AgentKey[] = ["jev_verify", "challenge", "response_operating_quality", "response_event_context", "response_market_context"];

function roleMeta(process: ReaderProcessDTO | null, role: AgentKey): ReaderRoleDTO | undefined {
  return process?.roles.find(item => item.role_key === role);
}

function StageHeader({ index, title, description, status }: { index: string; title: string; description: string; status: string }) {
  return <header className="ra-stage-head"><span className="ra-stage-index">{index}</span><div><h3>{title}</h3><p>{description}</p></div><span className="ra-stage-status">{status}</span></header>;
}

function SpecialistArtifact({ runId, role, process, runStatus, onSelect }: {
  runId: string; role: AgentKey; process: ReaderProcessDTO | null; runStatus: string; onSelect(role: AgentKey): void;
}) {
  const output = useReaderAgent(runId, role, process);
  const meta = roleMeta(process, role);
  const record = output.response?.insight_record;
  if (record) return <div className="ra-specialty-output"><InsightReader record={record} role={role} presentation="artifacts"/>
    <button type="button" className="ra-detail-link" onClick={() => onSelect(role)}>查看本环节与输入说明 ↗</button></div>;
  const status = meta?.status ?? "not_recorded";
  return <section className="ra-specialty ra-specialty-waiting" aria-label={`${AGENT_LABELS[role]}阶段产物`}>
    <header><div><span className="ra-role-mark">{AGENT_LABELS[role].slice(0, 1)}</span><h4>{AGENT_LABELS[role]}</h4></div><span>{STATUS_LABELS[status] ?? "未记录"}</span></header>
    <div className="ra-waiting-body">{output.error ? <p role="status">产物暂时无法读取。<button type="button" onClick={output.retry}>重试读取</button></p> :
      status === "running" ? "正在形成观点，已保存的关键 Insight 会显示在这里。" :
      status === "completed" || status === "failed" ? outputLabel(meta?.output_availability ?? "not_recorded") :
      runStatus === "failed" || runStatus === "cancelled" || runStatus === "interrupted" ? "本环节未形成可读产物。" : "等待本专项开始。"}
    <button type="button" className="ra-detail-link" onClick={() => onSelect(role)}>查看环节详情 ↗</button></div>
  </section>;
}

/** Important stage outputs are readable in place; full execution detail remains one click away. */
export function ResearchArtifacts({ runId, process, runStatus, onSelect }: {
  runId: string; process: ReaderProcessDTO | null; runStatus: string; onSelect(role: AgentKey): void;
}) {
  const evidence = roleMeta(process, "evidence");
  const specialists = SPECIALISTS.map(role => roleMeta(process, role));
  const completedSpecialists = specialists.filter(role => role?.status === "completed").length;
  const reviewRoles = REVIEW_ROLES.filter(role => roleMeta(process, role));
  const synthesis = roleMeta(process, "synthesis");
  const reviewStatuses = reviewRoles.map(role => roleMeta(process, role)!.status);
  const reviewStatus = reviewStatuses.includes("running") ? "执行中" : reviewStatuses.length > 0 && reviewStatuses.every(status => ["completed", "skipped", "not_applicable"].includes(status)) ? "已完成" : reviewStatuses.some(status => ["completed", "failed", "skipped"].includes(status)) ? "部分完成" : "等待专项完成";
  return <div className="research-artifacts">
    <section className="ra-stage" aria-label="证据冻结阶段">
      <StageHeader index="01" title="证据冻结" description="本次研究共同使用的合格事实与来源" status={STATUS_LABELS[evidence?.status ?? ""] ?? "正在读取状态"}/>
      <div className="ra-evidence"><strong>共同输入</strong>
        <span>{evidence?.output_count != null ? `${evidence.output_count} 项已记录产物` : outputLabel(evidence?.output_availability ?? "not_recorded")}</span>
        <button type="button" onClick={() => onSelect("evidence")}>查看资料范围与保存产物 ↗</button>
      </div>
    </section>
    <section className="ra-stage" aria-label="专项 Insight 阶段">
      <StageHeader index="02" title="专项 Insight" description="各专项独立保存，核心观点与局限直接可读" status={`${completedSpecialists} / ${SPECIALISTS.length} 个专项已完成`}/>
      <div className="ra-specialty-list">{SPECIALISTS.map(role => <SpecialistArtifact key={role} runId={runId} role={role} process={process} runStatus={runStatus} onSelect={onSelect}/>)}</div>
    </section>
    <section className="ra-stage" aria-label="核验与质疑阶段">
      <StageHeader index="03" title="核验与质疑" description="这里只汇总审阅进度；完整执行记录保留在审计" status={reviewStatus}/>
      <div className="ra-review-grid">{reviewRoles.map(role => {
        const meta = roleMeta(process, role)!;
        const label = role.startsWith("response_") ? `${AGENT_LABELS[role]}` : AGENT_LABELS[role];
        return <button type="button" key={role} onClick={() => onSelect(role)} data-status={meta.status}><strong>{label}</strong><span>{STATUS_LABELS[meta.status] ?? "未记录"}</span></button>;
      })}</div>
    </section>
    <section className="ra-stage" aria-label="综合报告阶段">
      <StageHeader index="04" title="综合报告" description="仅使用已保存且可追溯的 Insight" status={STATUS_LABELS[synthesis?.status ?? "not_reached"] ?? "等待"}/>
      <div className="ra-report-pending">{synthesis?.status === "running" ? "正在权衡专项观点、质疑与回应，形成综合判断。" : "专项研究、质疑与回应完成后，在这里形成综合判断。"}
        <button type="button" onClick={() => onSelect("synthesis")}>查看综合环节 ↗</button></div>
    </section>
  </div>;
}
