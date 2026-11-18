import { useEffect, useId, useRef, type ReactNode } from "react";
import type { AgentKey, ReaderProcessDTO, ReaderRoleDTO } from "../../api/contracts";
import { rolesForRun, type ReducerState } from "../../state/model";
import { AGENT_LABELS, isTerminalRun, STATUS_LABELS } from "../../domain/readerExplanation";

type FlowRole = { key: AgentKey; status: string; meta?: ReaderRoleDTO };
type Stage = { id: string; label: string; keys: AgentKey[] };
type StageStatus = "pending" | "running" | "partial" | "completed" | "failed";

const STAGE_STATUS: Record<StageStatus, string> = {
  pending: "等待", running: "执行中", partial: "部分完成", completed: "已完成", failed: "需关注",
};

function stageStatus(roles: FlowRole[]): StageStatus {
  if (roles.every(role => role.key === "code_checks")) {
    if (roles.some(role => role.status === "failed")) return "failed";
    return roles.every(role => role.status === "completed" || role.meta?.output_availability === "available") ? "completed" : "pending";
  }
  if (roles.some(role => role.status === "running")) return "running";
  if (roles.some(role => role.status === "failed" || role.status === "interrupted")) return "failed";
  if (roles.every(role => ["completed", "skipped", "not_applicable"].includes(role.status))) return "completed";
  if (roles.some(role => ["completed", "failed", "skipped"].includes(role.status))) return "partial";
  return "pending";
}

/** Dependency and output status share one compact rail; artifacts live in their own sections. */
export function ResearchFlow({ process, workflowVersion, state, runStatus, selectedRole,
  onSelect, onClose, children, artifacts, variant = "running" }: {
  process: ReaderProcessDTO | null; workflowVersion?: string; state?: ReducerState | null;
  runStatus: string; selectedRole: AgentKey | null;
  onSelect(role: AgentKey): void; onClose(): void; children?: ReactNode; artifacts?: ReactNode;
  variant?: "running" | "summary";
}) {
  const version = process?.workflow_version ?? workflowVersion ?? "evidence-production-v9";
  const known = version === "evidence-production-v9";
  const terminal = isTerminalRun(runStatus);
  const activeRun = !terminal && runStatus !== "cancel_requested";
  const roles: FlowRole[] = process ? process.roles.map(role => ({ key: role.role_key,
    status: state?.roles[role.actor_id]?.status ?? role.status, meta: role })) :
    rolesForRun(state?.meta.focus_requested).map(role => ({ key: role.node_id as AgentKey,
      status: state?.roles[role.actor_id]?.status ?? "not_recorded" }));
  if (known && !roles.some(role => role.key === "code_checks")) roles.push({ key: "code_checks", status: "not_recorded" });
  const byKey = new Map(roles.map(role => [role.key, role]));
  const stages: Stage[] = known ? [
    { id: "evidence", label: "证据冻结", keys: ["evidence"] },
    { id: "specialists", label: "专项研究", keys: ["operating_quality", "event_context", "market_context"] },
    { id: "decision", label: "决策核验", keys: ["jev_verify"] },
    { id: "challenge", label: "质疑", keys: ["challenge"] },
    { id: "responses", label: "回应", keys: ["response_operating_quality", "response_event_context", "response_market_context"] },
    { id: "synthesis", label: "综合判断", keys: ["synthesis"] },
    { id: "publication", label: "发布", keys: ["code_checks"] },
    ...(byKey.has("focus_response") ? [{ id: "focus", label: "关注点回应", keys: ["focus_response"] as AgentKey[] }] : []),
  ] : [{ id: "compatibility", label: "已记录环节", keys: roles.map(role => role.key) }];
  const visibleStages = stages.filter(stage => stage.keys.some(key => byKey.has(key)));
  const detailId = useId();
  const detail = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const reveal = () => {
    detail.current?.scrollIntoView({ block: "nearest", behavior: "instant" });
    detail.current?.focus({ preventScroll: true });
  };
  useEffect(() => { if (selectedRole) reveal(); }, [selectedRole]);
  const select = (key: AgentKey, button: HTMLButtonElement) => {
    trigger.current = button;
    if (key === selectedRole) reveal();
    else onSelect(key);
  };
  const close = () => { onClose(); trigger.current?.focus(); };
  const selectStage = (stage: Stage, button: HTMLButtonElement) => {
    const key = stage.keys.find(item => byKey.get(item)?.status === "running") ?? stage.keys[0];
    select(key, button);
  };
  const completedCount = visibleStages.filter(stage => stageStatus(stage.keys.map(key => byKey.get(key)!)) === "completed").length;
  const currentIndex = visibleStages.findIndex(stage => ["running", "partial", "failed", "pending"].includes(stageStatus(stage.keys.map(key => byKey.get(key)!))));

  const rail = <div className="rf-rail" aria-label="研究依赖流程">
    {visibleStages.map((stage, index) => {
      const stageRoles = stage.keys.map(key => byKey.get(key)!);
      const status = stageStatus(stageRoles);
      const code = stage.id === "publication";
      const selected = stage.keys.includes(selectedRole as AgentKey);
      const count = stage.keys.length === 1 ? byKey.get(stage.keys[0])?.meta?.output_count : null;
      return <div className="rf-rail-stage" data-stage={stage.id} data-status={status} key={stage.id}
        role="group" aria-label={stage.id === "focus" ? "基础研究保存后的补充" : stage.label}>
        <button type="button" className="rf-stage-button" data-active={activeRun && status === "running"}
          aria-label={`查看${stage.label}环节与保存产物`} aria-expanded={selected} aria-controls={selected ? detailId : undefined}
          onClick={event => selectStage(stage, event.currentTarget)}>
          <span className="rf-stage-dot" aria-hidden="true">{status === "completed" ? "✓" : index + 1}</span>
          <span className="rf-stage-name">{stage.label}</span>
          <span className="rf-stage-status">{code && status === "pending" ? "等待发布" : STAGE_STATUS[status]}{count != null ? ` · ${count} 项` : ""}</span>
        </button>
      </div>;
    })}
  </div>;
  const subroles = (stageId: string) => {
    const stage = visibleStages.find(item => item.id === stageId);
    if (!stage || stage.keys.length < 2) return null;
    return <div className={`rf-subroles rf-subroles-${stageId}`} role="group" aria-label={stage.id === "specialists" ? "独立专项分工" : stage.label}>
      {stage.keys.map(key => {
        const role = byKey.get(key)!;
        return <button type="button" key={key} data-role={key} data-status={role.status}
          data-active={activeRun && role.status === "running"} data-selected={selectedRole === key}
          aria-label={`查看${AGENT_LABELS[key]}环节与保存产物`} aria-expanded={selectedRole === key}
          aria-controls={selectedRole === key ? detailId : undefined}
          onClick={event => select(key, event.currentTarget)}>
          <strong>{AGENT_LABELS[key]}</strong>
          <span>{STATUS_LABELS[role.status] ?? "未记录"}{role.meta?.output_count != null ? ` · ${role.meta.output_count} 项` : ""}</span>
        </button>;
      })}
    </div>;
  };
  const processBody = <>
    {!known ? <p className="rf-compatibility" role="status">此版本暂不绘制依赖图，以下保留已记录环节。</p> : null}
    {rail}
    {known ? subroles("specialists") : null}
  </>;

  return <section className={`research-flow rf-${variant}`} aria-label="研究流程与环节详情">
    {variant === "summary" ? <details className="rf-process-summary">
      <summary><strong>研究过程 {completedCount} / {visibleStages.length} 个阶段已完成</strong><span>查看阶段与保存产物</span></summary>
      {processBody}
    </details> : <section className="rf-progress" aria-label="研究进度">
      <header className="rf-progress-head"><h2>研究进度</h2><span>{currentIndex >= 0 ? `第 ${currentIndex + 1} / ${visibleStages.length} 步` : `${visibleStages.length} 个阶段`} · 执行与保存状态分别记录</span></header>
      {processBody}
    </section>}
    {artifacts}
    {selectedRole ? <section className="rf-detail native-role-review" id={detailId} ref={detail} tabIndex={-1} aria-label="所选环节详情">
      <header className="rf-detail-head"><h2>环节详情</h2><button type="button" onClick={close}>收起环节详情</button></header>{children}
    </section> : null}
  </section>;
}
