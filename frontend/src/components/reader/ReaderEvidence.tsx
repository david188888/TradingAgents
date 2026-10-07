import type { ResearchRecordV1DTO, SourceEvidenceV1DTO } from "../../api/contracts";
import { limitationLabel } from "../../domain/researchCoverage";
import { TERMS } from "../../domain/readerExplanation";
import { claimText } from "./ResearchRecordSection";

export type EvidenceSelection = { kind: "claim" | "challenge" | "check" | "metric" | "valuation" | "source"; id: string };
export function selectionContent(record: ResearchRecordV1DTO, selected: EvidenceSelection | null) {
  const claimIds = new Set<string>(), evidenceIds = new Set<string>();
  let title = "选择左侧判断，核对支撑依据";
  if (selected?.kind === "claim") { const c = record.claims.find(c => c.claim_id === selected.id); if (c) { title = c.statement; claimIds.add(c.claim_id); } }
  if (selected?.kind === "challenge") { const c = record.challenges.find(c => c.challenge_id === selected.id); if (c) { title = c.statement; c.target_claim_ids.forEach(id => claimIds.add(id)); } }
  if (selected?.kind === "check") { const c = record.evidence_checks?.checks.find(c => c.check_id === selected.id); if (c) { title = c.question; c.evidence_ids.forEach(id => evidenceIds.add(id)); } }
  if (selected?.kind === "metric") { const c = record.metrics.find(c => c.metric_id === selected.id); if (c) { title = c.label; c.input_evidence_ids.forEach(id => evidenceIds.add(id)); } }
  if (selected?.kind === "valuation" && record.valuation) { title = "估值的输入与来源"; record.valuation.input_evidence_ids.forEach(id => evidenceIds.add(id)); }
  if (selected?.kind === "source") {
    evidenceIds.add(selected.id); title = "已保存来源";
    record.claims.filter(c => c.kind === "fact" && c.evidence_ids.includes(selected.id)).forEach(c => claimIds.add(c.claim_id));
  }
  const boundClaims = record.claims.filter(c => claimIds.has(c.claim_id));
  boundClaims.forEach(c => { c.supporting_fact_ids.forEach(id => claimIds.add(id)); c.evidence_ids.forEach(id => evidenceIds.add(id)); });
  const facts = record.claims.filter(c => c.kind === "fact" && claimIds.has(c.claim_id));
  facts.forEach(c => c.evidence_ids.forEach(id => evidenceIds.add(id)));
  return { title, boundClaims, facts, sources: record.evidence.filter(s => evidenceIds.has(s.evidence_id)) };
}

export function SavedSource({ source }: { source: SourceEvidenceV1DTO }) {
  const content = source.content;
  return <article className="qr-source">
    <h4>{source.source_name}</h4>
    <p className="qr-meta">可用时点 {source.usable_as_of ?? "未验证"} · 发布 {source.published_at ?? "未保存"}</p>
    {content?.kind === "excerpt" || content?.kind === "saved_summary" ? <>
      <p className="qr-source-text">{content.text}</p>
      <p className="qr-meta">{content.locator_label}{content.truncated ? " · 已截取，不能视为全文" : ""}</p>
    </> : content ? <p className="qr-meta">此来源保存的是结构化字段。先核对上方绑定事实，再按需展开数据。</p> : <p>本次未保存可读内容，不能在此核对原文。</p>}
    {source.limitations.map((l, i) => <p className="qr-meta" key={i}>{limitationLabel(l)}</p>)}
    {source.public_url && /^https?:\/\//i.test(source.public_url) ? <a href={source.public_url} target="_blank" rel="noreferrer">打开公开来源 ↗</a> : null}
    <details><summary>{content?.kind === "source_fields" ? "保存的原始字段与完整数值" : "技术信息与保存字段"}</summary>
      {content?.kind === "source_fields" ? <pre>{content.text}</pre> : null}
      <p>抓取时间：{source.captured_at ?? "未保存"}</p><p>定位：{content?.locator_label ?? "未保存"}</p>
      <p>内容校验：{content?.content_sha256 ?? "未保存"}</p>
      <p>读取状态：{source.availability}</p>
    </details>
  </article>;
}

export function ReaderEvidence({ record, selected, term, onTerm }: {
  record: ResearchRecordV1DTO; selected: EvidenceSelection | null; term: string | null; onTerm(term: string | null): void;
}) {
  const content = selectionContent(record, selected);
  if (term && TERMS[term]) return <div className="qr-evidence-body"><span className="qr-tag">概念解释 · 一般方法</span><h3>{term}</h3><p>{TERMS[term]}</p><p className="qr-meta">这段说明不是新增公司事实或研究结论。</p><button onClick={() => onTerm(null)}>返回当前依据</button></div>;
  return <div className="qr-evidence-body">
    <span className="qr-tag">本次保存的依据</span><h3>{content.title}</h3>
    {content.boundClaims.filter(c => c.kind !== "fact" && selected?.kind !== "claim").map(c => <p className="qr-meta" key={c.claim_id}>待验证推断：{c.statement}</p>)}
    {content.facts.length ? <section><h4>{selected?.kind === "source" ? "此来源中的保存事实" : "绑定的支撑事实"}</h4>{content.facts.map(f => <div className="qr-fact" key={f.claim_id}><p>{claimText(f.statement)}</p>{f.limitations.length ? <details><summary>字段定位与适用范围</summary>{f.limitations.map((l, i) => <p className="qr-meta" key={i}>{limitationLabel(l)}</p>)}</details> : null}</div>)}</section> : <p className="qr-meta">该项直接绑定来源或计算输入，未逐条指定支撑事实。请结合下方来源、方法和判断范围核对。</p>}
    {selected?.kind === "metric" ? <p>{record.metrics.find(m => m.metric_id === selected.id)?.method}</p> : null}
    <div className="qr-method-note"><h4>如何读这些依据</h4><p>事实是已保存资料中的信息；推断是对事实的解释。引用关系可追溯，仍需核对资料是否足以支持判断。</p></div>
    {content.sources.map(source => <SavedSource key={source.evidence_id} source={source} />)}
    {!content.sources.length ? <p>没有绑定的保存来源。系统不会在打开此处时补取资料。</p> : null}
    <details><summary>金融概念解释</summary><div className="qr-terms">{Object.keys(TERMS).map(t => <button key={t} onClick={() => onTerm(t)}>{t} ?</button>)}</div></details>
  </div>;
}
