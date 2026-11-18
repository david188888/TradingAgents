import type { InsightReportDTO, SourceEvidenceV1DTO, ReportExplanationDTO, SavedInsightDTO } from "../../api/contracts";
import { SafeMarkdown } from "../shared/SafeMarkdown";

const ROLES: Record<string, string> = { operating_quality: "经营研究", event_context: "事件研究", market_context: "市场研究", focus_response: "关注点回应" };
const ROLE_ORDER = ["operating_quality", "event_context", "market_context", "focus_response"];
const STATUS = { accepted: "可追溯研究观点", pending: "待验证", excluded: "已撤回或修订" };
const REVIEW = { challenged: "提出质疑", no_counterevidence: "本次审阅范围内未发现有效反证", unreviewed: "尚未审阅", failed: "审阅失败", verified: "决策核验通过" };
const ACTION = { maintain: "维持", revise: "修订", withdraw: "撤回", uncertain: "尚不能回答" };
const STANCE = { favorable: "有利", neutral: "中性", unfavorable: "不利" };

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
  return <section className="ir-source">
    <h5>{source.source_name}</h5>
    {source.content ? <><p>定位：{source.content.locator_label}</p><pre>{source.content.text}</pre></> : <p>未保存支持片段。</p>}
    {source.public_url && /^https?:\/\//i.test(source.public_url) ? <a href={source.public_url} target="_blank" rel="noreferrer">打开公开来源 ↗</a> : null}
    <p className="qr-meta">资料可用时间：{source.usable_as_of ?? "未记录"}</p>
    {source.limitations.map((text, index) => <p key={index}>{text}</p>)}
  </section>;
}

/** Structured saved fields drive the page; Markdown is only an inert presentation supplement. */
export function InsightReader({record, role, explanation, presentation = "report"}: {
  record: InsightReportDTO; role?: string; explanation?: ReportExplanationDTO | null;
  presentation?: "report" | "artifacts";
}) {
  const sources = new Map(Object.values(record.catalogs).flatMap(catalog => catalog.sources).map(source => [source.evidence_id, source]));
  const numbers = new Map(Object.values(record.catalogs).flatMap(catalog => catalog.numbers).map(number => [number.anchor.anchor_id, number.anchor]));
  const facts = new Map(Object.values(record.catalogs).flatMap(catalog => catalog.evidence).map(evidence => [evidence.fact_id, evidence]));
  const evidenceDetails = (item: SavedInsightDTO, label: string) => (
    <details className="ir-evidence"><summary>{label}（{item.source_ids.length} 项来源）</summary>
      {record.catalogs[item.catalog_id]?.evidence.filter(evidence => item.fact_ids.includes(evidence.fact_id)).map(evidence => <p key={evidence.ref}>{evidence.ref}：{evidence.text}</p>)}
      {item.source_ids.map(id => { const source = sources.get(id); return source ? <Source key={id} source={source}/> : <p key={id}>来源暂不可读。</p>; })}
      {item.numeric_ids.map(id => { const number = numbers.get(id); return number ? <section key={id} className="ir-number"><h5>{number.label}</h5><p>{number.subject} · {number.value} {number.unit}</p><p>{JSON.stringify(number.metadata)}</p><details><summary>计算与原始输入</summary><pre>{JSON.stringify(number.lineage, null, 2)}</pre></details></section> : null; })}
    </details>
  );
  const renderCard = (item: SavedInsightDTO) => {
    const reviews = record.reviews.filter(review => review.target_id === item.insight_id);
    const responses = record.responses.filter(response => response.target_id === item.insight_id);
    const entry = explanation?.entries["insight:" + item.insight_id];
    return <article className="ir-insight" key={item.insight_id} id={item.insight_id} data-status={item.status}>
      <div className="ir-insight-meta"><span>{ROLES[item.role] ?? item.role}</span><span>{STATUS[item.status]}</span></div>
      {item.role === "focus_response" ? <p className="ir-focus-question">关注问题：{record.focus_question}</p> : null}
      <h4>{item.rendered.claim}</h4>
      <div className="ir-limit"><strong>反证或局限</strong><SafeMarkdown content={item.rendered.limitations}/></div>
      {item.issues.length ? <p className="ir-issue">该观点存在引用、数值或资料缺口，暂不能作为总体判断依据。</p> : null}
      <details className="ir-reasoning"><summary>查看完整推理</summary><SafeMarkdown content={item.rendered.reasoning}/>
        {entry ? <aside className="ir-explanation"><h5>通俗解读</h5><SafeMarkdown content={entry.explanation}/><p>{entry.uncertainty}</p></aside> : null}
      </details>
      {reviews.length || responses.length ? <details className="ir-review"><summary>质疑与回应（{reviews.length + responses.length}）</summary>
        {reviews.map((review, index) => <section key={index}><h5>{REVIEW[review.status]}</h5>{review.concern ? <p>{review.concern}</p> : null}<SafeMarkdown content={review.reasoning}/>{review.note ? evidenceDetails(review.note, "查看质疑依据") : null}</section>)}
        {responses.map((response, index) => <section key={index}><h5>回应：{ACTION[response.action]}</h5><SafeMarkdown content={response.reasoning}/>{evidenceDetails(response.note, "查看回应依据")}{response.replacement_id ? <a href={`#${response.replacement_id}`}>查看修订观点</a> : null}</section>)}
      </details> : null}
      {evidenceDetails(item, "查看保存依据")}
    </article>;
  };
  const allItems = [...record.insights, ...record.focus_insights];
  const items = allItems.filter(item => !role || ["challenge", "jev_verify", "code_checks", "evidence"].includes(role) || item.role === role || item.role === role.replace("response_", ""));
  const renderGroup = (groupRole: string) => {
    const groupItems = items.filter(item => item.role === groupRole);
    if (!groupItems.length) return null;
    const current = groupItems.filter(item => item.status !== "excluded");
    const archived = groupItems.filter(item => item.status === "excluded");
    const accepted = groupItems.filter(item => item.status === "accepted").length;
    return <section className="ir-specialty" key={groupRole} aria-label={`${ROLES[groupRole] ?? groupRole} Insight`}>
      <header className="ir-specialty-head"><div><span className="ir-role-mark">{(ROLES[groupRole] ?? groupRole).slice(0, 1)}</span><h3>{ROLES[groupRole] ?? groupRole}</h3></div><span>{accepted} 条可追溯{current.length > accepted ? ` · ${current.length - accepted} 条待验证` : ""}</span></header>
      <div className="ir-insight-list">{current.length ? current.map(renderCard) : <p className="ir-empty">本专项当前没有可采纳观点。</p>}</div>
      {archived.length ? <details className="ir-archived"><summary>已撤回或修订观点（{archived.length}）</summary><div className="ir-insight-list">{archived.map(renderCard)}</div></details> : null}
    </section>;
  };
  const synthesis = record.synthesis;
  const longReasoning = synthesis ? synthesis.reasoning.length > 1000 : false;
  const referencedInsights = synthesis?.insight_ids.map(id => record.insights.find(item => item.insight_id === id)).filter(Boolean) ?? [];
  return <article className={`qr-reader ir-${presentation}`} aria-label={presentation === "artifacts" ? `${ROLES[role ?? ""] ?? "专项"}阶段产物` : "Insight 研究报告"}>
    {presentation === "report" && (!role || role === "synthesis") ? <section className="ir-report" aria-label="综合报告">
      {synthesis ? <>
        <header className={`ir-report-hero ir-stance-${synthesis.stance ?? "none"}`}>
          <div className="ir-report-label"><span>综合判断</span><strong className="ir-stance">{synthesis.stance === null ? "暂不评级" : STANCE[synthesis.stance]}</strong></div>
          <SafeMarkdown content={synthesis.judgement} className="ir-judgement"/>
          <footer><span>基于 {synthesis.insight_ids.length} 条可追溯 Insight · 资料截至 {record.analysis_date}</span></footer>
        </header>
        <nav className="ir-report-nav" aria-label="综合报告导航"><a href="#ir-reasoning">综合论证</a><a href="#ir-boundaries">研究边界</a><a href="#ir-specialists">专项 Insight</a></nav>
        <section className="ir-reasoning-section" id="ir-reasoning"><h3>判断依据</h3>
          <details className="ir-longform" open={!longReasoning} data-longform><summary>{longReasoning ? "展开完整综合论证" : "综合论证"}{longReasoning ? <span>内容较长，默认收起</span> : null}</summary><SafeMarkdown content={synthesis.reasoning}/></details>
          {referencedInsights.length ? <div className="ir-reference-list"><h4>本判断引用的观点</h4>{referencedInsights.map((item, index) => <a key={item!.insight_id} href={`#${item!.insight_id}`}><span>{String(index + 1).padStart(2, "0")}</span>{item!.rendered.claim}</a>)}</div> : null}
        </section>
        <div className="ir-boundaries" id="ir-boundaries"><section><h3>研究限制</h3><SafeMarkdown content={synthesis.limitations}/></section><section><h3>后续核查</h3><SafeMarkdown content={synthesis.next_check}/></section></div>
      </> : <section className="ir-no-synthesis"><h3>暂未形成总体判断</h3><p>以下保留已保存的专项研究，不设置默认评级。</p></section>}
    </section> : null}
    {presentation === "report" && record.gaps.length ? <section className="ir-gaps" aria-label="资料与流程限制"><h3>资料与流程限制</h3><ul>{record.gaps.map((gap, index) => <li key={index}>{gapLabel(gap)}</li>)}</ul></section> : null}
    {presentation === "report" && record.company_basics && (!role || role === "evidence") ? <details className="ir-company"><summary><span>公司基础资料</span><strong>{record.company_basics.company_name}</strong></summary>
      {[...record.company_basics.introduction, ...record.company_basics.fundamentals, ...record.company_basics.quantitative].map(field => <details key={field.claim_id}><summary>{field.label}</summary><p>{facts.get(field.claim_id)?.text}</p>{facts.get(field.claim_id)?.source_ids.map(id => { const source = sources.get(id); return source ? <Source key={id} source={source}/> : null; })}</details>)}
    </details> : null}
    <section className="ir-specialties" id={presentation === "report" ? "ir-specialists" : undefined}>
      {presentation === "report" ? <header className="ir-section-heading"><h2>专项 Insight</h2><p>有效观点优先；已撤回或修订版本单独收拢，不与报告依据混杂。</p></header> : null}
      {!items.length ? <p className="ir-empty">尚未形成可读研究观点，请查看资料和执行记录。</p> : null}
      {ROLE_ORDER.map(renderGroup)}
    </section>
  </article>;
}
