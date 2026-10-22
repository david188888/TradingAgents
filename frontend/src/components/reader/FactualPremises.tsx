import { limitationLabel } from "../../domain/researchCoverage";
import { createContext, useContext } from "react";
import type { NumericRecordedStageV1DTO, PremiseReceiptV1DTO } from "../../api/contracts";

type Entry = PremiseReceiptV1DTO & { text: string };
export const PremiseContext = createContext<Entry[]>([]);

export function premiseEntries(stages: NumericRecordedStageV1DTO[]): Entry[] {
  const seen = new Set<string>();
  return stages.flatMap(stage => stage.proof.fields.flatMap(field => {
    if (!field.premise) return [];
    const entry = { ...field.premise, text: field.segments.map(s => s.text).join("") };
    const key = JSON.stringify(entry);
    if (seen.has(key)) return [];
    seen.add(key);
    return [entry];
  }));
}

function PremiseDetail({ entry }: { entry: Entry }) {
  return <div className="qr-premise-evidence">
    <p className="qr-meta">观察的来源与计算可核对；解释的含义和因果尚未证实。</p>
    {entry.observations.length ? <details>
      <summary>已有观察与依据（{entry.observations.length}）</summary>
      {entry.observations.map(o => <article key={o.observation_id}>
        <strong>{o.kind === "source" ? "来源转述" : o.kind === "comparison" ? "代码比较" : "数值正负"}</strong>
        <p>{o.text}</p>
        {o.limitations.filter(l => !l.startsWith("source_field:") && !l.startsWith("native_dimension:")).map((l, i) => <p className="qr-meta" key={i}>{limitationLabel(l)}</p>)}
        <details><summary>保存的来源标识</summary>
          {o.evidence_ids.map(id => <p className="qr-meta" key={id}>{id}</p>)}
        </details>
      </article>)}
    </details> : <p className="qr-meta">尚未绑定可用观察，仅作为待研究问题。</p>}
    {entry.pending_questions.length ? <><strong>待验证前提 · 不作为已发生事实</strong>
      <ul>{entry.pending_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></> : null}
  </div>;
}

export function FactualPremises({ text }: { text: string }) {
  const entries = useContext(PremiseContext).filter(e => e.text === text);
  return <>{entries.map((entry, i) => <PremiseDetail key={i} entry={entry}/>)}</>;
}

export function PremiseLedger({ entries }: { entries: Entry[] }) {
  if (!entries.length) return null;
  return <details className="qr-output-card"><summary>观察、解释与待验证前提</summary>
    {entries.map((entry, i) => <article key={i}><p>{entry.text}</p><PremiseDetail entry={entry}/></article>)}
  </details>;
}
