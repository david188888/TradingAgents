import { SearchResearch } from "./SearchResearch";
import { useEffect, useId, useRef, type ReactNode } from "react";
import type { AgentKey, ReaderProcessDTO, ReaderRoleDTO, ResearchRecordDTO } from "../../api/contracts";
import { rolesForProfile, type ReducerState } from "../../state/model";
import { AGENT_LABELS, AGENT_PURPOSE, isTerminalRun, outputLabel, STATUS_LABELS } from "../../domain/readerExplanation";

type FlowRole = { key: AgentKey; status: string; meta?: ReaderRoleDTO };
type Group = { id: string; label: string; keys: AgentKey[] };

/** Dependency map only: data, dispatch and public output qualification stay in existing hooks. */
export function ResearchFlow({ process, workflowVersion, state, runStatus, record, selectedRole,
  onSelect, onClose, children }: {
  process: ReaderProcessDTO | null; workflowVersion?: string; state?: ReducerState | null;
  runStatus: string; record?: ResearchRecordDTO | null; selectedRole: AgentKey | null;
  onSelect(role: AgentKey): void; onClose(): void; children?: ReactNode;
}) {
  const version = process?.workflow_version ?? workflowVersion;
  const known = /^evidence-production-v[1-8]$/.test(version ?? "");
  const unified = version === "evidence-production-v7" || version === "evidence-production-v8";
  const terminal = isTerminalRun(runStatus);
  const activeRun = !terminal && runStatus !== "cancel_requested";
  const roles: FlowRole[] = process ? process.roles.map(r => ({ key: r.role_key,
    status: state?.roles[r.actor_id]?.status ?? r.status, meta: r })) :
    rolesForProfile("evidence_v1", version, state?.meta.focus_requested).map(r => ({ key: r.node_id as AgentKey,
      status: state?.roles[r.actor_id]?.status ?? "not_recorded" }));
  if (known && !roles.some(r => r.key === "code_checks")) roles.push({ key: "code_checks", status: "not_recorded" });
  const byKey = new Map(roles.map(r => [r.key, r]));
  const groups: Group[] = known ? [
    { id: "evidence", label: "共同输入", keys: ["evidence"] },
    { id: "specialists", label: "独立专项分工", keys: ["operating_quality", "event_context", "market_context"] },
    { id: "challenge", label: "汇合提议，提出质疑", keys: ["challenge"] },
    { id: "checks", label: "核查可执行条件", keys: ["code_checks"] },
    ...(unified ? [{ id: "responses", label: "被质疑专项回应", keys: ["response_operating_quality", "response_event_context", "response_market_context"] as AgentKey[] }] : []),
    { id: "synthesis", label: "综合研究判断", keys: ["synthesis"] },
    { id: "publication", label: "校验并发布基础研究", keys: ["code_checks"] },
    ...(byKey.has("focus_response") ? [{ id: "focus", label: "基础研究保存后的补充", keys: ["focus_response"] as AgentKey[] }] : []),
  ] : [{ id: "compatibility", label: "已记录环节", keys: roles.map(r => r.key) }];
  const visibleGroups = groups.filter(g => g.keys.some(k => byKey.has(k)));
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

  return <section className="research-flow" aria-label="研究流程与环节详情">
    {record ? <SearchResearch record={record}/> : null}
    <div className="rf-workspace" data-detail={selectedRole ? "open" : "closed"}>
      <section className="rf-map" aria-label="研究依赖流程">
        <header className="rf-panel-head"><h2>研究如何推进</h2><span>执行状态与产物状态分别记录</span></header>
        {!known ? <p className="rf-compatibility" role="status">{version ? "此版本暂不绘制依赖图，以下保留已记录环节。" : "正在读取流程版本，以下显示已知环节。"}</p> : null}
        <div className="rf-canvas">
          {visibleGroups.map((group, index) => <div className="rf-group-wrap" key={group.id}>
            {index ? <div className="rf-connector" data-active={activeRun && group.keys.some(k => byKey.get(k)?.status === "running")}>
              <span>{group.label}</span><span className="rf-arrow" aria-hidden="true">↓</span>
            </div> : <p className="rf-group-label">{group.label}</p>}
            <div className="rf-group" data-group={group.id} role="group" aria-label={group.label}>
              {group.keys.map((key, position) => {
                const role = byKey.get(key);
                if (!role) return null;
                const { meta, status } = role;
                const code = key === "code_checks";
                const label = code ? group.id === "publication" ? "基础研究发布" : "代码条件核查" : AGENT_LABELS[key];
                const savedStatus = meta ? outputLabel(meta.output_availability, meta.reason_code, runStatus) : "正在读取保存状态";
                const outputStatus = group.id === "publication" && meta?.output_availability === "stage_available" ? terminal ? "本次未发布最终研究" : "最终研究尚未发布"
                  : status === "not_reached" ? "后续未执行" : status === "pending" && terminal ? "本环节未执行" : savedStatus;
                return <article className="rf-node" key={`${group.id}.${key}`} data-role={key}
                  data-status={status} data-active={activeRun && status === "running"} data-selected={selectedRole === key}>
                  <div className="rf-node-meta"><span className="rf-index">{String(index + 1).padStart(2,"0")}{group.keys.length > 1 && known ? String.fromCharCode(65 + position) : ""}</span>
                    <span className="rf-status">{code ? "代码职责" : STATUS_LABELS[status] ?? "未记录"}</span></div>
                  <h3>{label}</h3><p className="rf-purpose">{code ? group.id === "publication" ? "验证并保存可公开阅读的基础研究。" : "核查给定条件，保留经济解释与未知项。" : meta?.purpose ?? AGENT_PURPOSE[key]}</p>
                  {key === "evidence" && record ? <p className="rf-count">{record.evidence.length} 项来源 · {record.claims.filter(c => c.kind === "fact").length} 条事实</p> : null}
                  <p className="rf-output">{outputStatus}{meta?.output_count != null && group.id !== "publication" && !(key === "evidence" && record) ? ` · ${meta.output_count} ${key === "evidence" ? "条事实" : "项"}` : ""}</p>
                  <button type="button" aria-label={`查看${label}环节与保存产物`} aria-expanded={selectedRole === key}
                    aria-controls={selectedRole ? detailId : undefined} onClick={e => select(key,e.currentTarget)}>查看本环节与保存产物 <span aria-hidden="true">↗</span></button>
                </article>;
              })}
            </div>
          </div>)}
          <p className="rf-boundary">连接线表示资料与提议的依赖；各专项独立研究。执行结束不代表研究充分或产物已发布。</p>
        </div>
      </section>
      {selectedRole ? <section className="rf-detail native-role-review" id={detailId} ref={detail} tabIndex={-1} aria-label="所选环节详情">
        <header className="rf-panel-head"><h2>环节详情</h2><button type="button" onClick={close}>收起角色回顾</button></header>{children}
      </section> : null}
    </div>
  </section>;
}
