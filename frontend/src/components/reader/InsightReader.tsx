import type { InsightReportDTO, SourceEvidenceV1DTO, ReportExplanationDTO, SavedInsightDTO } from "../../api/contracts";

const ROLES: Record<string, string> = { operating_quality: "经营研究", event_context: "事件研究", market_context: "市场研究", focus_response: "关注点回应" };
const STATUS = { accepted: "可追溯研究观点", pending: "待验证", excluded: "已撤回或修订" };
const REVIEW = { challenged: "提出质疑", no_counterevidence: "审阅后未发现有效反证", unreviewed: "尚未审阅", failed: "审阅失败" };
const ACTION = { maintain: "维持", revise: "修订", withdraw: "撤回", uncertain: "尚不能回答" };

function gapLabel(value: string): string {
  if (value === "unreviewed_insights") return "部分观点尚未完成审阅。";
  if (value === "synthesis_unavailable") return "综合判断未通过生成或引用核验，合格专项观点仍保留。";
  for (const [role, label] of Object.entries(ROLES)) {
    if (value === `${role}_partial`) return `${label}部分输出未形成可采纳观点。`;
    if (value === `response_${role}_unresolved`) return `${label}仍有未解决的质疑。`;
  }
  if (value === "focus_unavailable") return "关注问题尚未形成有效回应，基础研究保留。";
  if (value.startsWith("search_")) return "定向补搜未完全补齐资料，请核查观点局限。";
  return value.startsWith("search_gap:") ? "资料搜索仍有未补齐事项。" : `资料限制：${value}`;
}

function Source({source}: {source: SourceEvidenceV1DTO}) {
  return <section>
    <h5>{source.source_name}</h5>
    {source.content ? <><p>定位：{source.content.locator_label}</p><pre style={{whiteSpace:"pre-wrap", overflowWrap:"anywhere"}}>{source.content.text}</pre></> : <p>未保存支持片段。</p>}
    {source.public_url && /^https?:\/\//i.test(source.public_url) ? <a href={source.public_url} target="_blank" rel="noreferrer">打开公开来源 ↗</a> : null}
    <p className="qr-meta">资料可用时间：{source.usable_as_of ?? "未记录"}</p>
    {source.limitations.map((text, i) => <p key={i}>{text}</p>)}
  </section>;
}

/** Read saved output only; viewing evidence never invokes a model. */
export function InsightReader({record, role, explanation}: {record: InsightReportDTO; role?: string; explanation?: ReportExplanationDTO | null}) {
  const sources = new Map(Object.values(record.catalogs).flatMap(c => c.sources).map(s => [s.evidence_id, s]));
  const numbers = new Map(Object.values(record.catalogs).flatMap(c => c.numbers).map(n => [n.anchor.anchor_id, n.anchor]));
  const facts = new Map(Object.values(record.catalogs).flatMap(c => c.evidence).map(e => [e.fact_id,e]));
  const evidenceDetails = (item: SavedInsightDTO, label: string) => (
    <details><summary>{label}（{item.source_ids.length} 项来源）</summary>
          {record.catalogs[item.catalog_id]?.evidence.filter(e => item.fact_ids.includes(e.fact_id)).map(e => <p key={e.ref}>{e.ref}：{e.text}</p>)}
          {item.source_ids.map(id => {const source = sources.get(id);return source ? <Source key={id} source={source}/> : <p key={id}>来源暂不可读。</p>;})}
          {item.numeric_ids.map(id => {const n = numbers.get(id);return n ? <section key={id}><h5>{n.label}</h5><p>{n.subject} · {n.value} {n.unit}</p><p>{JSON.stringify(n.metadata)}</p><details><summary>计算与原始输入</summary><pre style={{whiteSpace:"pre-wrap"}}>{JSON.stringify(n.lineage, null, 2)}</pre></details></section> : null;})}
        </details>
  );
  const synthesis = record.synthesis;
  const items = [...record.insights, ...record.focus_insights].filter(i => !role || role === "challenge" || role === "code_checks" || role === "evidence" || i.role === role || i.role === role.replace("response_", ""));
  return <article className="qr-reader" aria-label="Insight 研究报告">
    {!role || role === "synthesis" ? <section>
      <h3>综合判断</h3>
      {synthesis ? <>
        <p><strong>{synthesis.stance === null ? "暂不评级" : { favorable: "有利", neutral: "中性", unfavorable: "不利" }[synthesis.stance]}</strong></p>
        <p>{synthesis.judgement}</p><p>{synthesis.reasoning}</p>
        <p>局限：{synthesis.limitations}</p><p>后续核查：{synthesis.next_check}</p>
        <nav aria-label="综合依据">{synthesis.insight_ids.map((id, i) => <p key={id}><a href={`#${id}`}>查看依据 {i + 1}：{record.insights.find(item => item.insight_id === id)?.rendered.claim ?? "已保存观点"}</a></p>)}</nav>
      </> : <p>暂未形成总体判断；以下保留已保存的专项研究，不设置默认评级。</p>}
    </section> : null}
    {record.gaps.length ? <section aria-label="研究限制"><h3>资料与流程限制</h3><ul>{record.gaps.map((gap, i) => <li key={i}>{gapLabel(gap)}</li>)}</ul></section> : null}
    {record.company_basics && (!role || role === "evidence") ? <section><h3>公司基础资料</h3><p>{record.company_basics.company_name}</p>
      {[...record.company_basics.introduction, ...record.company_basics.fundamentals, ...record.company_basics.quantitative].map(field => <details key={field.claim_id}><summary>{field.label}</summary><p>{facts.get(field.claim_id)?.text}</p>{facts.get(field.claim_id)?.source_ids.map(id => {const source=sources.get(id);return source ? <Source key={id} source={source}/> : null;})}</details>)}</section> : null}
    <section><h3>专项观点与研究审阅</h3>
      {!record.insights.length ? <p>尚未形成可读研究观点，请查看资料和执行记录。</p> : null}
      {items.map(item => <section key={item.insight_id} id={item.insight_id}>
        <p className="qr-meta">{ROLES[item.role] ?? item.role} · {STATUS[item.status]}</p>
        {item.role === "focus_response" ? <p>关注问题：{record.focus_question}</p> : null}
        <h4>{item.rendered.claim}</h4><p>{item.rendered.reasoning}</p><p>反证或局限：{item.rendered.limitations}</p>
        {explanation?.entries["insight:" + item.insight_id] ? <aside><h5>通俗解读</h5><p>{explanation.entries["insight:" + item.insight_id].explanation}</p><p>{explanation.entries["insight:" + item.insight_id].uncertainty}</p></aside> : null}
        {item.issues.length ? <p>该观点存在引用、数值或资料缺口，暂不能作为总体判断依据。</p> : null}
        {record.reviews.filter(r => r.target_id === item.insight_id).map((review, i) => <section key={i}><h5>{REVIEW[review.status]}</h5><p>{review.concern}</p><p>{review.reasoning}</p>{review.note ? evidenceDetails(review.note, "查看质疑依据") : null}</section>)}
        {record.responses.filter(r => r.target_id === item.insight_id).map((reply, i) => <section key={i}><h5>回应：{ACTION[reply.action]}</h5><p>{reply.reasoning}</p>{evidenceDetails(reply.note, "查看回应依据")}{reply.replacement_id ? <a href={`#${reply.replacement_id}`}>查看修订观点</a> : null}</section>)}
        {evidenceDetails(item, "查看保存依据")}
      </section>)}
    </section>
  </article>;
}
