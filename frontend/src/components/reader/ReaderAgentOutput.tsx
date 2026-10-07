import type { AgentKey, ReaderAgentDTO, ReaderProcessDTO, ResearchRecordV1DTO } from "../../api/contracts";
import { AGENT_LABELS, countLabel, DIMENSION_LABELS, outputLabel, STATUS_LABELS } from "../../domain/readerExplanation";
import { CHECK_LABELS, LocalChallengeResult, LocalEvidenceChecks, claimText } from "./ResearchRecordSection";
import type { EvidenceSelection } from "./ReaderEvidence";

export function ReaderAgentOutput({ role, process, output, error, record, entity, onRole, onInspect, onLocate, onRetry }: {
  role: AgentKey; process: ReaderProcessDTO | null; output: ReaderAgentDTO | null; error: boolean; record: ResearchRecordV1DTO | null; entity: string | null;
  onRole(role: AgentKey): void; onInspect(selection: EvidenceSelection, trigger?: HTMLElement): void; onLocate(selection: EvidenceSelection): void; onRetry(): void;
}) {
  const meta = process?.roles.find(r => r.role_key === role), p = output?.proposal;
  const relations = (id: string) => output?.relations.find(r => r.entity_id === id);
  const relation = (id: string, kind: "claim" | "challenge") => {
    const r = relations(id);
    return r ? <footer className="qr-actions"><span className="qr-meta">{r.in_record ? "进入完整记录" : "未进入记录"}{r.is_key ? kind === "challenge" && process?.primary_selection === "code" ? " · 代码置顶主要疑点" : " · 综合选为重点" : " · 未列为首页重点"}{r.dimensions.length ? ` · ${r.dimensions.map(d => DIMENSION_LABELS[d] ?? d).join("、")}引用` : ""}{r.challenge_ids.length ? ` · 关联 ${r.challenge_ids.length} 条挑战` : ""}</span><button onClick={() => onLocate({kind, id})}>定位最终记录 →</button></footer> : null;
  };
  return <section className="qr-agent-review" aria-label="Agent 产物回顾">
    <div className="qr-agent-tabs" aria-label="选择角色">{Object.entries(AGENT_LABELS).map(([key, label]) => <button key={key} aria-pressed={role === key} onClick={() => onRole(key as AgentKey)}>{label}{key === "evidence" || key === "code_checks" ? " · 代码" : ""}</button>)}</div>
    <header><span className="qr-eyebrow">{meta?.origin === "code" ? "代码环节" : "Agent 保存产物"}</span><h2>{AGENT_LABELS[role]}</h2><p>{meta?.purpose}</p><p className="qr-meta">{STATUS_LABELS[meta?.status ?? ""] ?? "状态未记录"} · {meta ? outputLabel(meta.output_availability, meta.reason_code) : "正在读取保存状态"}</p></header>
    <div className="qr-method-note"><h3>使用了什么输入</h3><p>{output?.input_description ?? "等待读取已保存的输入范围说明。"}</p><p className="qr-meta">这里只展示研究字段，不包含模型对话、提示词或内部思考。</p></div>
    {error ? <p role="status">产物暂时无法读取。<button onClick={onRetry}>重试读取</button></p> : !output ? <p aria-busy="true">正在读取所选角色的保存产物…</p> : output.availability !== "available" ? <p role="status">{outputLabel(output.availability, output.reason_code)}。最终报告仍可按原保存记录阅读。</p> : <>
      {p && "hypotheses" in p ? <>
        <h3>全部研究假设（{p.hypotheses.length}）</h3>
        {!p.hypotheses.length ? <p>该专项返回了合法的零假设提议。</p> : null}
        {p.hypotheses.map((h, i) => { const id = output.claim_ids[i]; return <article className="qr-output-card" key={id} data-entity={id} data-highlighted={id === entity ? "true" : undefined}>
          <span className="qr-tag">假设 {i + 1} · 待验证</span><h3>{h.statement}</h3>
          <h4>必要条件</h4>{h.conditions.filter(c => c.condition_role === "necessary").map((c, i) => <p key={i}>{c.text}</p>)}
          <h4>推翻条件</h4>{h.conditions.filter(c => c.condition_role === "invalidation").map((c, i) => <p key={i}>{c.text}</p>)}
          <h4>替代解释</h4><p>{h.alternative_explanation}</p>
          <h4>支撑事实</h4>{h.supporting_fact_ids.map(fid => <button className="qr-fact-link" key={fid} onClick={event => onInspect({kind:"claim",id:fid}, event.currentTarget)}>{claimText(record?.claims.find(c => c.claim_id === fid)?.statement ?? "事实不在当前读取记录中")} →</button>)}
          {relation(id, "claim")}
        </article>; })}
        <h3>本专项待查（{p.unknowns.length}）</h3><p className="qr-meta">专项只看对应证据子集，这里的未知项不代表全局资料缺失。</p>{p.unknowns.map((u, i) => <p key={i}>{u}</p>)}
      </> : null}
      {p && "challenges" in p ? <>
        <h3>全部挑战提议（{p.challenges.length}）</h3>{!p.challenges.length ? <p>保存的是合法的零挑战提议；不代表不存在风险。</p> : null}
        {p.challenges.map((c,i) => { const id = output.challenge_ids[i], h = record?.hypotheses.find(h => h.hypothesis_id === c.hypothesis_id); return <article className="qr-output-card" key={id} data-entity={id} data-highlighted={id === entity ? "true" : undefined}>
          <span className="qr-tag warn">{c.severity === "critical" ? "关键" : c.severity === "material" ? "重要" : "一般"}挑战</span><h3>{c.statement}</h3>
          <h4>针对哪条假设</h4><p>{record?.claims.find(f => f.claim_id === h?.claim_id)?.statement ?? "当前记录未定位到目标"}</p>
          <h4>建议如何核查 · 尚非执行结果</h4><p>{c.proposed_test}</p>
          {c.check_id ? <p className="qr-meta">关联固定证据子问题：{CHECK_LABELS[c.check_id]}</p> : null}
          {c.observation_date ? <p>提议观察日期：{c.observation_date}</p> : null}
          {c.condition_id ? <details><summary>绑定的条件与研究字段</summary><pre>{JSON.stringify(c, null, 2)}</pre></details> : null}
          {relation(id,"challenge")}
          <button onClick={() => onInspect({kind:"challenge",id})}>核对目标假设的依据 →</button>
          {record?.assessment?.schema_version === "research-assessment-v2" ? record.assessment.challenge_assessments.filter(a => a.challenge_id === id).map(a => <details key={a.challenge_id}><summary>最终代码核查结果 · 另列来源</summary><LocalChallengeResult item={a}/></details>) : null}
        </article>; })}
      </> : null}
      {p && "judgement" in p ? <>
        <article className="qr-output-card"><h3>原回答</h3><p>{p.judgement}</p><h3>完整下一步</h3><p>{p.next_check}</p></article>
        <h3>原分项判断</h3>{p.dimensions.map(d => <article className="qr-output-card" key={d.dimension}><h4>{DIMENSION_LABELS[d.dimension]}</h4><p>{d.judgement}</p><p className="qr-meta">提议状态：{d.status === "unresolved" ? "待核查" : d.status === "conditional" ? "有条件判断" : "提议有支持"}</p>{d.claim_ids.map(id => <button key={id} onClick={() => onInspect({kind:"claim",id})}>{claimText(record?.claims.find(c => c.claim_id === id)?.statement ?? id)}</button>)}<details><summary>维度研究字段</summary><pre>{JSON.stringify(d,null,2)}</pre></details></article>)}
        <h3>重点依据的选择</h3>{p.key_claim_ids.map(id => <article key={id}><p>{record?.claims.find(c => c.claim_id === id)?.statement}</p>{relation(id,"claim")}</article>)}
        <h3>主要疑点的选择</h3><p>{record?.challenges.find(c => c.challenge_id === p.primary_challenge_id)?.statement ?? "原提议未选择主要疑点"}</p>
        <p className="qr-meta">{process?.primary_selection === "code" ? "最终主要疑点由代码关键级别规则置顶，与本提议不同。" : "原提议与最终主要疑点一致；仍受发布规则约束。"}</p>
        <h3>提议的挑战处理意见</h3>{p.challenge_assessments.map(a => <article className="qr-output-card" key={a.challenge_id}><p>{record?.challenges.find(c => c.challenge_id === a.challenge_id)?.statement}</p><p>{a.rationale}</p><span className="qr-tag warn">原提议：尚未解决</span><button onClick={() => onLocate({kind:"challenge",id:a.challenge_id})}>核对最终结果 →</button></article>)}
      </> : null}
      {output.origin === "code" && record ? <>
        <h3>保存的代码产物</h3><p>{role === "evidence" ? `冻结了 ${record.claims.filter(c => c.kind === "fact").length} 条事实和 ${record.evidence.length} 项来源。` : `保存了 ${record.verifications.length} 次额外条件验证。固定证据子问题与最终发布资格如下。`}</p>
        <LocalEvidenceChecks record={record} onInspect={(sources, _label, trigger) => { if(sources[0]) onInspect({kind:"source",id:sources[0].evidence_id}, trigger); }}/>
        {record.verifications.map(v => <article className="qr-output-card" key={v.verification_id}><p>{v.condition_text}</p><p>{v.result}</p><p className="qr-meta">{v.status} · 只核查指定条件</p></article>)}
        <p>记录完整性：{record.assessment?.completeness === "complete" ? "完整" : "部分"}；结论质量：{record.assessment?.quality === "PASS" ? "通过当前质量门槛" : "证据或挑战仍有保留"}。</p>
        <button onClick={() => onLocate({kind:"source",id:record.evidence[0]?.evidence_id ?? ""})}>查看全部事实、来源与最终记录 →</button>
      </> : null}
      <details><summary>{output.origin === "model" ? "保存的结构化提议（JSON）" : "保存的代码产物字段"}</summary><pre>{JSON.stringify(output.origin === "model" ? output.proposal : { code_sections:output.code_sections, evidence_checks:record?.evidence_checks, verifications:record?.verifications, assessment:record?.assessment }, null, 2)}</pre></details>
    </>}
    {meta ? <details><summary>执行统计与记录口径</summary><p>主分析预算授权：{countLabel(meta.main_budget)}；SDK 主发出授权：{countLabel(meta.sdk_main)}；SDK 修复发出授权：{countLabel(meta.sdk_repair)}。</p><p>授权不证明网络送达、供应商接收、成功完成或计费。</p></details> : null}
  </section>;
}
