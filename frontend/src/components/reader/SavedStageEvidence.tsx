import { useState } from "react";
import type { ResearchRecordDTO } from "../../api/contracts";
import { limitationLabel } from "../../domain/researchCoverage";
import { SavedSource } from "./ReaderEvidence";
import { claimText } from "./ResearchRecordSection";

/** Actual saved material only; expanding a source never fetches new data. */
export function SavedStageEvidence({ record, factIds }: { record: ResearchRecordDTO; factIds?: string[] }) {
  const [query, setQuery] = useState("");
  const facts = record.claims.filter(c => c.kind === "fact" && (!factIds || factIds.includes(c.claim_id)));
  const sourceIds = new Set(facts.flatMap(f => f.evidence_ids));
  const sources = factIds ? record.evidence.filter(s => sourceIds.has(s.evidence_id)) : record.evidence;
  const readable = sources.filter(s => s.availability === "available" && s.content && s.usable_as_of);
  const term = query.trim().toLocaleLowerCase();
  const visible = facts.filter(f => `${f.statement} ${sources.filter(s => f.evidence_ids.includes(s.evidence_id)).map(s => s.source_name).join(" ")}`.toLocaleLowerCase().includes(term));
  return <section className="qr-saved-evidence" aria-label="实际保存的事实与来源">
    <p>{facts.length} 条事实 · {sources.length} 项来源记录，其中 {readable.length} 项已保存可核对内容。</p>
    <p className="qr-meta">事实反映资料在相应时点的记录；来源资格通过仍不代表足以支持投资结论。</p>
    <label className="qr-stage-search">查找事实或来源<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="输入关键词" /></label>
    <h3>保存事实{term ? `（匹配 ${visible.length} 条）` : ""}</h3>
    {!visible.length ? <p>{term ? "没有匹配的保存事实。" : "本环节未记录事实输入。"}</p> : null}
    {visible.map(f => <details key={f.claim_id} className="qr-output-card">
      <summary>{claimText(f.statement)}</summary>
      {f.limitations.length ? <details><summary>适用范围与字段定位</summary>{f.limitations.map((l, i) => <p className="qr-meta" key={i}>{limitationLabel(l)}</p>)}</details> : null}
      {record.evidence.filter(s => f.evidence_ids.includes(s.evidence_id)).map(s => <SavedSource key={s.evidence_id} source={s} />)}
    </details>)}
    <details className="qr-output-card"><summary>全部来源与资料缺口（{sources.length} 项记录）</summary>
      {sources.map(s => <details key={s.evidence_id} className="qr-source"><summary>{s.source_name} · {s.availability === "available" && s.content && s.usable_as_of ? "已保存内容" : "资料受限"}</summary><SavedSource source={s}/></details>)}
    </details>
  </section>;
}
