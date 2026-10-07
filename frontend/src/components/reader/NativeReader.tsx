import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { AgentKey, ReaderProcessDTO, ResearchRecordV1DTO } from "../../api/contracts";
import { useReaderAgent, useReaderFocus } from "../../hooks/useReaderProcess";
import { AGENT_LABELS, countLabel, DIMENSION_LABELS, outputLabel, STATUS_LABELS, TERMS } from "../../domain/readerExplanation";
import { limitationLabel } from "../../domain/researchCoverage";
import { useDrawerFocus, useReturnFocus } from "../shared/drawerFocus";
import { claimText, LocalChallengeResult, LocalEvidenceChecks, MetricCard } from "./ResearchRecordSection";
import { ReaderEvidence, SavedSource, type EvidenceSelection } from "./ReaderEvidence";
import { ReaderAgentOutput } from "./ReaderAgentOutput";
import { ValuationPositionCard } from "./ValuationPositionCard";
import { FocusResponse } from "./FocusResponse";
import "../../styles/nativeReader.css";

type View = "report" | "evidence" | "process" | "agents" | "full";

export function NativeReader({ runId, record, process, processError, retryProcess }: {
  runId: string; record: ResearchRecordV1DTO; process: ReaderProcessDTO | null; processError: boolean; retryProcess(): void;
}) {
  const assessment = record.assessment!;
  const [view, setView] = useState<View>("report");
  const [role, setRole] = useState<AgentKey>("operating_quality");
  const [entity, setEntity] = useState<string | null>(null);
  const [selected, setSelected] = useState<EvidenceSelection | null>(() => assessment.key_claim_ids[0] ? {kind:"claim",id:assessment.key_claim_ids[0]} : null);
  const [term, setTerm] = useState<string | null>(null);
  const [pinned, setPinned] = useState(false);
  const [modal, setModal] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [hasReturn, setHasReturn] = useState(false);
  const root = useRef<HTMLElement>(null), rail = useRef<HTMLElement>(null);
  const returnContext = useRef<{ view: View; y: number; mainY: number; trigger: HTMLElement; triggerText: string; triggerIndex: number } | null>(null);
  const focus = useReturnFocus();
  const agent = useReaderAgent(runId, view === "agents" ? role : null, process);
  const supplemental = useReaderFocus(runId, process);
  const independent = process?.workflow_version === "evidence-production-v6";
  const hasFocus = process?.roles.some(r=>r.role_key === "focus_response");
  const preferred = record.metrics.filter(m => /\.(annualized_volatility|historical_var_95|max_drawdown|atr_14)$/.test(m.metric_id));
  const primaryMetrics = (preferred.length ? preferred : record.metrics).slice(0,4);
  const primary = record.challenges.find(c => c.challenge_id === assessment.primary_challenge_id);
  const origin = (id: string) => process?.claim_origins.find(c => c.claim_id === id)?.role_key;
  const closeModal = () => { setModal(false); focus.release(); };
  const showModal = (trigger: HTMLElement) => { focus.remember(trigger); setModal(true); };
  const select = (value: EvidenceSelection, trigger?: HTMLElement, manual = true) => {
    setSelected(value); setTerm(null); setPinned(manual);
    if (manual && narrow) {
      const active = document.activeElement;
      const returnTarget = trigger ?? (active instanceof HTMLElement ? active : root.current);
      if (returnTarget) showModal(returnTarget);
    }
  };
  const changeView = (next: View) => { setView(next); setEntity(null); window.scrollTo({top:0,behavior:"instant"}); document.querySelector("main")?.scrollTo({top:0,behavior:"instant"}); };
  const openAgent = (key: AgentKey, id: string | null, trigger: HTMLElement) => {
    const matching = Array.from(root.current?.querySelectorAll<HTMLButtonElement>("button") ?? []).filter(b=>b.textContent === trigger.textContent);
    returnContext.current = {view, y:window.scrollY, mainY:document.querySelector("main")?.scrollTop ?? 0, trigger, triggerText:trigger.textContent ?? "", triggerIndex:matching.indexOf(trigger as HTMLButtonElement)}; setHasReturn(true);
    setRole(key); setEntity(id); setView("agents"); window.scrollTo({top:0,behavior:"instant"});
  };
  const returnToReading = () => {
    const context = returnContext.current;
    if (!context) return;
    setView(context.view); setHasReturn(false);
    window.setTimeout(() => { window.scrollTo({top:context.y,behavior:"instant"}); document.querySelector("main")?.scrollTo({top:context.mainY,behavior:"instant"}); const restored = context.trigger.isConnected ? context.trigger : Array.from(root.current?.querySelectorAll<HTMLButtonElement>("button") ?? []).filter(b=>b.textContent === context.triggerText)[context.triggerIndex];
      (restored ?? root.current?.querySelector<HTMLButtonElement>(".qr-evidence-entry"))?.focus({preventScroll:true}); },0);
  };
  const locate = (value: EvidenceSelection) => { setSelected(value); setTerm(null); setPinned(true); setEntity(value.id); setView("full"); };
  useEffect(() => {
    const node = root.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(entries => setNarrow(entries[0].contentRect.width < 960));
    observer.observe(node); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!entity) return;
    const timer = window.setTimeout(() => {
      const node = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-entity]") ?? []).find(el => el.dataset.entity === entity);
      if (node) { node.scrollIntoView({block:"center",behavior:"instant"}); node.tabIndex = -1; node.focus({preventScroll:true}); }
    },0);
    return () => window.clearTimeout(timer);
  }, [entity, view, agent.response]);
  useEffect(() => {
    if (view !== "report" || pinned || narrow) return;
    let scheduled = false;
    const update = () => {
      scheduled = false;
      if (!rail.current || rail.current.matches(":hover") || rail.current.contains(document.activeElement) || rail.current.querySelector("details[open]")) return;
      const sections = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-follow-kind]") ?? []);
      const line = 170;
      const current = sections.find(el => { const r=el.getBoundingClientRect();return r.top <= line && r.bottom > line; }) ?? sections.find(el => el.getBoundingClientRect().top > line);
      if (current?.dataset.followId) { setSelected({kind:current.dataset.followKind as EvidenceSelection["kind"],id:current.dataset.followId!}); setTerm(null); }
    };
    const scroll = () => { if(!scheduled) {scheduled=true;requestAnimationFrame(update);} };
    document.addEventListener("scroll",scroll,true); update();
    return () => document.removeEventListener("scroll",scroll,true);
  }, [view,pinned,narrow]);
  const contribution = (key: AgentKey, id?: string) => process?.roles.find(r => r.role_key === key)?.output_availability === "available"
    ? <button className="qr-text-button" onClick={e => openAgent(key,id ?? null,e.currentTarget)}>来自{AGENT_LABELS[key]} · 回顾产物 →</button>
    : <span className="qr-meta">相关产物归属尚未核验；可在 Agent 产物页查看读取状态。</span>;
  const inspectButton = (value: EvidenceSelection, label="核对依据 →") => <button className="qr-text-button" onClick={e => select(value,e.currentTarget)}>{label}</button>;
  const sectionHead = (number: string, title: string, description: string) => <header className="qr-section-head"><span>{number}</span><div><h2>{title}</h2><p className="qr-meta">{description}</p></div></header>;
  const evidence = <ReaderEvidence record={record} selected={selected} term={term} onTerm={t => {setTerm(t);setPinned(true);}}/>;
  return <section className="question-reader" ref={root} aria-label={independent ? "独立研究报告" : "问题优先研究报告"}>
    <nav className="qr-nav" aria-label="报告导航">{([["report","研究报告"],["evidence","证据目录"],["process","研究过程"],["agents","Agent 产物"],["full","完整记录"]] as [View,string][]).map(([key,label]) => <button key={key} aria-current={view === key ? "page" : undefined} onClick={() => changeView(key)}>{label}</button>)}</nav>
    {hasReturn && view !== "report" ? <button className="qr-return" onClick={returnToReading}>← 返回刚才的阅读位置</button> : null}
    <div className={`qr-reading-grid${narrow ? " qr-narrow" : ""}`}>
      <div className="qr-reading-main">
        {view === "report" ? <>
          <header className="qr-question"><span className="qr-eyebrow">{independent ? "本次研究范围" : process?.question_origin === "user" ? "你的研究问题" : "本次研究问题"}</span><h2>{assessment.research_question}</h2><p className="qr-meta">{!independent && process?.workflow_version ? "历史运行：研究问题参与了当时的基础分析。 " : ""}证据截至 {record.analysis_date}{assessment.forward_window_calendar_days ? ` · 展望 ${assessment.forward_window_calendar_days} 个日历日` : ""}</p></header>
          <article className="qr-answer"><span className={`qr-tag${assessment.quality === "LOW_CONFIDENCE" ? " warn" : ""}`}>{assessment.quality === "LOW_CONFIDENCE" ? "结论仍需核查" : "通过当前质量门槛"}</span><h3>{independent ? "综合判断" : "当前回答"}</h3><p className="qr-judgement">{assessment.judgement}</p><p className="qr-boundary">研究流程已完成 · 记录{assessment.completeness === "complete" ? "完整" : "部分"} · {assessment.quality === "LOW_CONFIDENCE" ? "证据或挑战仍有保留；不确定不等于否定。" : "仍需在已保存依据与适用范围内理解。"}</p>{contribution("synthesis")}</article>
          <nav className="qr-jump-nav" aria-label="报告章节">{[["qr-findings","关键依据"],["qr-doubt","疑点与下一步"],["qr-checks","已经核对什么"],["qr-valuation","估值定位"],["qr-quant","量化背景"]].map(([id,label]) => <button key={id} onClick={() => document.getElementById(id)?.scrollIntoView({block:"start",behavior:"instant"})}>{label}</button>)}</nav>
          <section className="qr-report-section" id="qr-findings">{sectionHead("01",independent ? "关键研究依据" : "哪些依据支持回答","先看重点推断，再沿右侧找到绑定事实和保存来源。")}
            {assessment.key_claim_ids.map((id,i) => { const c=record.claims.find(c=>c.claim_id===id);if(!c)return null; const key=origin(id);return <article className="qr-finding" data-entity={id} data-follow-kind="claim" data-follow-id={id} key={id} data-selected={selected?.id===id ? "true":undefined}><span className="qr-tag">{c.kind === "fact" ? "保存事实" : "待验证推断"} {i+1}</span><p>{claimText(c.statement)}</p><footer className="qr-actions">{inspectButton({kind:"claim",id})}{key ? contribution(key,id) : <span className="qr-meta">逐条作者归属未记录</span>}</footer></article>;})}
            {!assessment.key_claim_ids.length ? <p>综合环节未选出重点依据；可在完整记录中检查已有事实。</p> : null}
          </section>
          <section className="qr-report-section" id="qr-doubt" data-follow-kind="challenge" data-follow-id={primary?.challenge_id ?? ""}>{sectionHead("02","最大的疑点，下一步怎么查","区分待验证的经济问题、模型建议和已经执行的检查。")}
            <article className="qr-next-box"><span className="qr-tag warn">主要疑点</span><h3>{primary?.statement ?? "本次未选出主要挑战；不代表不存在风险。"}</h3>{primary ? <><h4>挑战提出的核查办法 · 尚非执行结果</h4><p>{primary.proposed_test}</p><footer className="qr-actions">{inspectButton({kind:"challenge",id:primary.challenge_id})}{contribution("challenge",primary.challenge_id)}</footer></> : null}
              <h4>综合给出的完整下一步</h4><p>{assessment.next_check}</p>{contribution("synthesis")}
              <p className="qr-boundary">{process?.primary_selection === "code" ? "主要疑点由挑战环节提出，代码关键级别规则置顶。" : process?.primary_selection === "synthesis" ? "主要疑点由挑战环节提出，综合环节选择。" : "主要疑点的选择归属尚未核验。"} 下一步是建议，是否已执行需查看下方记录。</p>
            </article>
            {record.challenges.length > 1 ? <button className="qr-text-button" onClick={() => changeView("full")}>查看全部 {record.challenges.length} 条挑战 →</button> : null}
          </section>
          <section className="qr-report-section" id="qr-checks">{sectionHead("03","已经核对了什么","这些检查核对指定资料和数字；通过检查仍不能证明业务联系、增长能否持续或价格是否合理。")}
            {process?.source_failures.includes("document_parser_not_installed") ? <div className="qr-fault"><h3>本次部分公告正文未能解析</h3><p>运行时缺少 PDF 解析依赖，影响正文核对。这是程序读取问题，不表示公司没有披露。</p></div> : null}
            {record.evidence_checks?.checks.map(c => <article className="qr-check" key={c.check_id} data-follow-kind="check" data-follow-id={c.check_id}><span className={`qr-tag${c.status === "passed" ? "" : " warn"}`}>{c.status === "passed" ? "证据子问题已核对" : c.status === "conflict" ? "存在数据冲突" : "所需证据不足"}</span><h3>{c.question}</h3>{c.observations.map((o,i) => <p key={i}>{o.label}：{o.value} {o.unit}</p>)}{c.missing.map((m,i) => <p className="qr-meta" key={i}>{limitationLabel(m)}</p>)}{inspectButton({kind:"check",id:c.check_id})}</article>)}
            <p className="qr-meta">额外条件验证：{record.verifications.length} 次。{!record.verifications.length ? "本次未执行新增来源的独立验证。" : "执行范围和结果见完整记录。"}</p>{contribution("code_checks")}
          </section>
          <section className="qr-report-section" id="qr-valuation" data-follow-kind="valuation" data-follow-id="valuation">{sectionHead("04","估值定位与参考区间","理解当前价格所处位置；区间依赖已保存盈利与倍数假设。")}
            {record.valuation ? <><ValuationPositionCard assessment={record.valuation.assessment}/><p className="qr-meta">报价截至 {record.valuation.inputs.snapshot?.as_of ?? record.analysis_date}。{record.valuation.assessment.synthesis.contributing_anchor_ids.length === 1 ? "只有一个有效锚点，未做交叉验证。" : ""}</p>{inspectButton({kind:"valuation",id:"valuation"},"核对估值输入与来源 →")}<details><summary>计算输入与校验</summary><pre>{JSON.stringify(record.valuation.inputs,null,2)}</pre><p className="qr-meta">输入 SHA256：{record.valuation.input_sha256}</p></details></> : <p>本次没有合格估值输入，无法形成参考区间。</p>}
          </section>
          <section className="qr-report-section" id="qr-quant">{sectionHead("05","量化背景","代码计算的历史描述；不代表价值区间或未来损失上限。")}
            <div className="qr-quant-grid">{primaryMetrics.map(m => <div key={m.metric_id} data-follow-kind="metric" data-follow-id={m.metric_id}><MetricCard metric={m}/>{inspectButton({kind:"metric",id:m.metric_id})}</div>)}</div>
            <details><summary>更多量化指标（{record.metrics.length-primaryMetrics.length}）</summary>{record.metrics.filter(m=>!primaryMetrics.includes(m)).map(m=><div key={m.metric_id}><MetricCard metric={m}/>{inspectButton({kind:"metric",id:m.metric_id})}</div>)}</details>
          </section>
          <section className="qr-report-section"><h2>分项判断与完整追溯</h2><p className="qr-meta">还有 {assessment.dimensions.length} 个维度、{record.hypotheses.length} 条假设和 {record.evidence.length} 项保存来源。</p><button onClick={() => changeView("full")}>打开完整记录 →</button></section>
          {independent && hasFocus ? <FocusResponse value={supplemental.response} error={supplemental.error} retry={supplemental.retry} onInspect={(v,trigger)=>select(v,trigger)}/> : null}
        </> : null}
        {view === "process" ? <section><header className="qr-view-intro"><span className="qr-eyebrow">从证据到回答</span><h2>这份报告是怎样形成的</h2><p>基础研究由一个代码证据环节和五个模型角色完成。{hasFocus ? "关注点由另一个模型角色在基础研究保存后回应。" : ""}代码核查另列。</p></header>
          {processError ? <p role="status">过程暂时无法读取。<button onClick={retryProcess}>重试</button></p> : null}
          {process?.roles.map((r,i) => <article className="qr-process-step" key={r.role_key}><span className="qr-step-index">{String(i+1).padStart(2,"0")}</span><div><h3>{r.label} <span className="qr-tag">{STATUS_LABELS[r.status] ?? "未记录"}</span></h3><p>{r.purpose}</p><p className="qr-meta">{outputLabel(r.output_availability,r.reason_code)}{r.output_count !== null ? ` · ${r.output_count} 项` : ""}</p><button onClick={e=>openAgent(r.role_key,null,e.currentTarget)}>回顾本环节产物 →</button></div></article>)}
          <details><summary>调用记录与统计口径</summary>{process ? <><p>主分析预算授权：{countLabel(process.counts.main_budget)}；结构化修复预算授权：{countLabel(process.counts.repair_budget)}</p><p>SDK 主发出授权：{countLabel(process.counts.sdk_main)}；修复发出授权：{countLabel(process.counts.sdk_repair)}；合计：{countLabel(process.counts.sdk_total)}</p>{process.counts.focus_budget ? <p>补充回应预算授权：{countLabel(process.counts.focus_budget)}；SDK 补充发出授权：{countLabel(process.counts.sdk_focus)}</p> : null}<p>数据能力调用：{countLabel(process.counts.data_capability)}；HTTP 尝试：{countLabel(process.counts.data_http)}</p><p className="qr-meta">发出授权不证明供应商接收或计费；重复保存 checkpoint 不重复计数。记录序列 {process.source_sequence}。</p></> : <p>未记录</p>}</details>
        </section> : null}
        {view === "agents" ? <ReaderAgentOutput role={role} process={process} output={agent.response} error={agent.error || processError} record={record} entity={entity} onRole={r=>{setRole(r);setEntity(null);}} onInspect={(v,trigger)=>select(v,trigger)} onLocate={locate} onRetry={()=>{agent.retry();if(processError)retryProcess();}}/> : null}
        {view === "evidence" ? <section><header className="qr-view-intro"><h2>证据目录</h2><p>按本次保存来源逐项核对；字段来源先看绑定事实，再展开原始数据。</p></header>{record.evidence.map(s=><article className="qr-catalog-card" key={s.evidence_id}><h3>{s.source_name}</h3><p className="qr-meta">{s.usable_as_of ?? "时间资格未验证"} · {s.content?.kind === "excerpt" ? "保存摘录" : s.content ? "保存字段" : "未保存正文"}</p>{inspectButton({kind:"source",id:s.evidence_id},"打开保存内容 →")}</article>)}</section> : null}
        {view === "full" ? <section className="qr-full-record"><header className="qr-view-intro"><h2>完整研究记录</h2><p>保留所有分项判断、假设、挑战、条件、事实与来源；首页未展示的内容仍可追溯。</p></header>
          <h3>全部分项判断</h3>{assessment.dimensions.map(d=><article className="qr-output-card" key={d.dimension}><h4>{DIMENSION_LABELS[d.dimension]} · {d.status === "unresolved" ? "待核查" : "有条件判断"}</h4><p>{d.judgement}</p>{d.claim_ids.map(id=><button key={id} onClick={e=>select({kind:"claim",id},e.currentTarget)}>{claimText(record.claims.find(c=>c.claim_id===id)?.statement ?? id)} →</button>)}{d.limitations.map((l,i)=><p className="qr-meta" key={i}>{limitationLabel(l)}</p>)}</article>)}
          <h3>全部假设与推翻条件</h3>{record.hypotheses.map(h=><article className="qr-output-card" key={h.hypothesis_id} data-entity={h.claim_id}><p>{record.claims.find(c=>c.claim_id===h.claim_id)?.statement}</p><h4>必要条件</h4>{h.assumptions.map((s,i)=><p key={i}>{s}</p>)}<h4>推翻条件</h4>{h.invalidation_conditions.map((s,i)=><p key={i}>{s}</p>)}{h.limitations.map((s,i)=><p className="qr-meta" key={i}>{limitationLabel(s)}</p>)}<footer className="qr-actions">{inspectButton({kind:"claim",id:h.claim_id})}{origin(h.claim_id) ? contribution(origin(h.claim_id)!,h.claim_id) : <span className="qr-meta">作者未记录</span>}</footer></article>)}
          <h3>全部挑战与最终核查结果</h3>{record.challenges.map(c=><article className="qr-output-card" key={c.challenge_id} data-entity={c.challenge_id}><h4>{c.severity === "critical" ? "关键挑战" : "挑战"}</h4><p>{c.statement}</p><h4>建议核查 · 不等于执行</h4><p>{c.proposed_test}</p>{assessment.schema_version === "research-assessment-v2" ? assessment.challenge_assessments.filter(a=>a.challenge_id===c.challenge_id).map(a=><LocalChallengeResult key={a.challenge_id} item={a}/>) : assessment.challenge_assessments.filter(a=>a.challenge_id===c.challenge_id).map(a=><p key={a.challenge_id}>{a.rationale}</p>)}<footer className="qr-actions">{inspectButton({kind:"challenge",id:c.challenge_id})}{contribution("challenge",c.challenge_id)}</footer></article>)}
          <LocalEvidenceChecks record={record} onInspect={(sources,_label,trigger)=>{if(sources[0])select({kind:"source",id:sources[0].evidence_id},trigger);}}/>
          <h3>全部条件验证（{record.verifications.length}）</h3>{record.verifications.map(v=><article className="qr-output-card" key={v.verification_id}><p>{v.condition_text}</p><p>{v.result}</p><p className="qr-meta">{v.status} · {v.scope}</p></article>)}
          <h3>全部事实与推断（{record.claims.length}）</h3>{record.claims.map(c=><article className="qr-fact" key={c.claim_id} data-entity={record.hypotheses.some(h=>h.claim_id===c.claim_id) ? undefined:c.claim_id}><span className="qr-tag">{c.kind === "fact" ? "事实" : c.kind === "inference" ? "推断" : "待查"}</span><p>{claimText(c.statement)}</p>{inspectButton({kind:"claim",id:c.claim_id})}</article>)}
          <h3>全部保存来源</h3>{record.evidence.map(s=><details key={s.evidence_id} data-entity={s.evidence_id}><summary>{s.source_name}</summary><SavedSource source={s}/></details>)}
          <h3>全部限制</h3>{[...new Set([...record.limitations,...assessment.limitations])].map((l,i)=><p className="qr-meta" key={i}>{limitationLabel(l)}</p>)}
          <details><summary>保存的完整公开研究字段</summary><pre>{JSON.stringify(record,null,2)}</pre></details>
        </section> : null}
      </div>
      {!narrow ? <aside className="qr-evidence-rail" ref={rail} aria-label="相关依据"><header><h2>相关依据</h2><p className="qr-meta">{pinned ? "已固定当前选择" : "随阅读位置切换"}</p><div className="qr-actions"><button onClick={()=>{setPinned(p=>!p);setTerm(null);}}>{pinned ? "恢复跟随" : "固定当前依据"}</button><button onClick={e=>showModal(e.currentTarget)}>放大阅读</button></div></header>{evidence}<footer><button onClick={()=>{if(selected)locate(selected);}}>回到对应完整记录 →</button></footer></aside> : null}
    </div>
    <button className="qr-evidence-entry" onClick={e=>showModal(e.currentTarget)}>{narrow ? "打开相关依据与概念解释" : "打开当前依据"}</button>
    {modal ? <EvidenceDialog onClose={closeModal}>{evidence}</EvidenceDialog> : null}
    <div className="qr-terms-footer"><span>常用概念</span>{Object.keys(TERMS).map(t=><button key={t} onClick={e=>{setTerm(t);setPinned(true);if(narrow)showModal(e.currentTarget);}}>{t} ?</button>)}</div>
  </section>;
}

function EvidenceDialog({ onClose, children }: {onClose(): void;children:React.ReactNode}) {
  const background=useMemo(()=>[document.getElementById("root")],[]);
  const {panelRef,onKeyDown}=useDrawerFocus({open:true,trap:true,background,onClose});
  return createPortal(<div className="record-dialog-backdrop" onClick={e=>{if(e.target===e.currentTarget)onClose();}}><section className="qr-evidence-dialog" role="dialog" aria-modal="true" aria-label="依据与概念解释" ref={panelRef} onKeyDown={onKeyDown}><header><h2>依据与概念解释</h2><button data-autofocus onClick={onClose}>关闭</button></header>{children}</section></div>,document.body);
}
