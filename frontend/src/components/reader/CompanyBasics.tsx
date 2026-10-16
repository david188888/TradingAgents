import { useContext } from "react";
import { ExplainedText, ExplanationContext } from "./PlainExplanation";
import type { ResearchRecordV1DTO } from "../../api/contracts";
import type { EvidenceSelection } from "./ReaderEvidence";
import { claimText } from "./ResearchRecordSection";

export function CompanyBasics({record,onInspect}: {record:ResearchRecordV1DTO;onInspect(value:EvidenceSelection,trigger?:HTMLElement):void}) {
  const basics=record.company_basics;
  const explanations=useContext(ExplanationContext);
  if (!basics) return null;
  return <section className="qr-report-section" aria-label="公司基础资料">
    <h2>公司基础资料 · {basics.company_name ?? record.ticker}</h2>
    {([['公司公开介绍',basics.introduction],['基本面数据',basics.fundamentals],['量化与行情',basics.quantitative]] as const).map(([label,fields])=><div key={label}>
      <h3>{label}</h3>
      {fields.length ? fields.map(field=><article className="qr-output-card" key={field.claim_id}>
        <h4>{explanations?.indicators[`claim:${field.claim_id}`]?.label ?? field.label}{field.report_period ? ` · 报告期 ${field.report_period}` : ''}</h4>
        <ExplainedText target={`claim:${field.claim_id}`} text={claimText(record.claims.find(claim=>claim.claim_id===field.claim_id)?.statement ?? '')}/>
        <button className="qr-text-button" onClick={event=>onInspect({kind:'claim',id:field.claim_id},event.currentTarget)}>核对保存来源 →</button>
      </article>) : <p className="qr-meta">此项明确字段未取得；其他已保存资料继续交付。</p>}
    </div>)}
    {basics.gaps.length ? <details><summary>基础资料的具体缺口</summary>{basics.gaps.map(gap=><p className="qr-meta" key={gap}>{gap}</p>)}</details> : null}
  </section>;
}
