import { ExplainedText, useReadableReference } from "./PlainExplanation";
import type { ResearchRecordV1DTO } from "../../api/contracts";
import { AGENT_LABELS, DISPOSITION_LABELS, STANCE_LABELS, dimensionLabel } from "../../domain/readerExplanation";
import type { EvidenceSelection } from "./ReaderEvidence";
import { LocalChallengeResult, claimText } from "./ResearchRecordSection";

/** Public saved fields only: reasons, falsifiers and the bounded reply chain. */
export function InvestmentJudgement({record,onInspect}: {record:ResearchRecordV1DTO;onInspect(value:EvidenceSelection,trigger?:HTMLElement):void}) {
  const assessment=record.assessment;
  const readable=useReadableReference();
  if (assessment?.schema_version !== "research-assessment-v3") return null;
  const claim = (id:string) => record.claims.find(c=>c.claim_id===id);
  const reference = (id:string) => <button className="qr-fact-link" key={id} onClick={e=>onInspect({kind:"claim",id},e.currentTarget)}>{readable(`claim:${id}`,claimText(claim(id)?.statement ?? id))} →</button>;
  return <section className="qr-report-section" aria-label="投资判断依据">
    <h2>{assessment.investment_stance === null ? "已有分析 · 暂未形成总体评级" : `投资吸引力 · ${STANCE_LABELS[assessment.investment_stance]}`}</h2>
    <p className="qr-meta">{assessment.report_status === 'specialist_summary' || assessment.report_status === 'basic_report' ? '综合阶段未完成；以下保留真实基础观察、有效专项观点和待查条件。' : '结合公司经营与当前价格形成有条件的研究判断。'}</p>
    {([['支持理由',assessment.supporting_arguments,'supporting_arguments'],['反对理由与反证',assessment.opposing_arguments,'opposing_arguments']] as const).map(([label,arguments_,field])=><div key={label}><h3>{label}</h3>{arguments_.length ? arguments_.map((a,i)=><article className="qr-output-card" key={i}><ExplainedText target={`assessment:${field}:${i}`} text={a.rationale}/>{a.claim_ids.map(reference)}{a.response_ids.map(id=><p className="qr-meta" key={id}>引用专项回应：{record.dialogue?.responses.find(r=>r.response_id===id)?.rationale}</p>)}</article>) : <p className="qr-meta">本次未形成合格的此类理由。</p>}</div>)}
    <h3>哪些条件会改变判断</h3>
    {assessment.change_conditions.map((c,i)=>{const h=record.hypotheses.find(h=>h.hypothesis_id===c.hypothesis_id);return <article className="qr-output-card" key={`${c.hypothesis_id}:${c.invalidation_index}`}><ExplainedText target={`assessment:change_conditions:${i}`} text={c.text}/>{h ? reference(h.claim_id) : null}</article>;})}
    <h3>四个维度的判断</h3>
    {assessment.dimensions.map(d=><article className="qr-output-card" key={d.dimension}><h4>{dimensionLabel(d.dimension,true)} · {d.status === 'unresolved' ? '待核查' : '有条件判断'}</h4><ExplainedText target={`dimension:${d.dimension}`} text={d.judgement}/>{d.claim_ids.map(reference)}</article>)}
  </section>;
}

export function ResearchDialogue({record,onInspect}: {record:ResearchRecordV1DTO;onInspect(value:EvidenceSelection,trigger?:HTMLElement):void}) {
  const assessment=record.assessment;
  const readable=useReadableReference();
  if (assessment?.schema_version !== "research-assessment-v3" || !record.dialogue) return null;
  const retained = assessment.report_status === 'specialist_summary' || assessment.report_status === 'basic_report';
  return <section className="qr-report-section" aria-label="一轮质疑与专项回应"><h2>一轮质疑与专项回应</h2><p className="qr-meta">{retained ? '保留原观点、实际核查和专项回应；综合阶段未完成，回应仍待进一步验证。' : '保留原观点、实际核查、专项回应和综合裁决；回应不自动关闭经济挑战。'}</p>
    {!record.dialogue.responses.length ? <p>没有需要专项回应的挑战，未调用回应环节。</p> : null}
    {record.dialogue.responses.map(r=>{const h=record.hypotheses.find(h=>h.hypothesis_id===r.hypothesis_id), c=record.challenges.find(c=>c.challenge_id===r.challenge_id), a=assessment.adjudications.find(a=>a.response_id===r.response_id);return <article className="qr-output-card" key={r.response_id} data-entity={r.response_id}>
      <h3>原观点 · {AGENT_LABELS[r.role]}</h3><p>{record.claims.find(c=>c.claim_id===h?.claim_id)?.statement}</p>
      <h4>质疑</h4><p>{c?.statement}</p><button onClick={e=>onInspect({kind:"challenge",id:r.challenge_id},e.currentTarget)}>核对目标与依据 →</button>
      <h4>实际代码核查</h4>{assessment.challenge_assessments.filter(a=>a.challenge_id===r.challenge_id).map(a=><LocalChallengeResult key={a.challenge_id} item={a}/>)}
      <h4>专项回应 · {r.status === "unavailable" ? "回应缺席" : DISPOSITION_LABELS[r.disposition]}</h4><ExplainedText target={`reply:${r.response_id}`} text={r.rationale}/>{r.supporting_fact_ids.map(id=><button key={id} onClick={e=>onInspect({kind:"claim",id},e.currentTarget)}>{readable(`claim:${id}`,claimText(record.claims.find(c=>c.claim_id===id)?.statement ?? id))} →</button>)}
      {r.remaining_unknowns.map((u,i)=><p className="qr-meta" key={i}>尚未确定：{u}</p>)}
      <h4>{retained ? `保留的专项回应状态 · ${a ? DISPOSITION_LABELS[a.disposition] : "未记录"}` : assessment.report_status ? '综合意见' : `综合裁决 · ${a ? DISPOSITION_LABELS[a.disposition] : "未记录"}`}</h4><ExplainedText target={`adjudication:${r.response_id}`} text={a?.rationale ?? ""}/>
      {r.disposition === "withdrawn" || r.disposition === "revised" ? <p className="qr-meta">原观点保留用于追溯，已退出结论的有效支撑。</p> : null}
    </article>;})}
  </section>;
}
