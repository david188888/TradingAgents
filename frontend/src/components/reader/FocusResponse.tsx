import type { FocusProposalDTO, ReaderFocusDTO } from "../../api/contracts";
import type { EvidenceSelection } from "./ReaderEvidence";

export const FOCUS_REASONS: Record<string, string> = {
  base_synthesis_unavailable: "基础综合未形成有效提议，跳过补充回应。",
  budget_exhausted: "剩余调用额度不足，未执行补充回应。",
  deadline_exceeded: "剩余时间不足，补充回应未完成。",
  response_unknown: "先前调用的结果未完整保存，未重复发出。",
  model_failed: "补充回应调用失败。",
  invalid_response: "补充回应未通过结构或证据引用校验。",
  publication_failed: "补充回应未能发布。",
  corrupt: "补充回应未通过保存记录校验。",
  not_published: "本次没有已发布的补充回应。",
  base_unavailable: "基础研究尚不可读取，无法展示补充回应。",
};

export function FocusAnswer({ proposal, onInspect }: {proposal: FocusProposalDTO; onInspect(value: EvidenceSelection, trigger?: HTMLElement): void}) {
  return <>
    <span className="qr-tag">{{answered:"已有证据可回应",partial:"只能部分回应",unresolved:"现有证据无法判断"}[proposal.answerability]}</span>
    <p>{proposal.answer}</p>
    {proposal.limitations.map((limit,i)=><p className="qr-meta" key={i}>{limit}</p>)}
    {proposal.suggested_next_check ? <><h3>建议后续核查 · 尚未执行</h3><p>{proposal.suggested_next_check}</p></> : null}
    <div className="qr-actions">{proposal.claim_ids.map((id,i)=><button key={id} onClick={e=>onInspect({kind:"claim",id},e.currentTarget)}>引用事实或推断 {i+1} →</button>)}{proposal.evidence_ids.map((id,i)=><button key={id} onClick={e=>onInspect({kind:"source",id},e.currentTarget)}>保存来源 {i+1} →</button>)}</div>
  </>;
}

export function FocusResponse({ value, error, retry, onInspect }: {value: ReaderFocusDTO | null; error: boolean; retry(): void; onInspect(value: EvidenceSelection, trigger?: HTMLElement): void}) {
  if (value?.state === "not_applicable") return null;
  const response = value?.response;
  return <section className="qr-report-section" id="qr-focus" aria-label="补充关注点回应">
    <h2>补充关注点回应</h2><p className="qr-meta">在独立基础研究完成后，依据已有保存证据补充回应；不改写上文的综合判断。</p>
    {value?.focus ? <h3>{value.focus}</h3> : null}
    {error ? <p role="status">补充回应暂时无法读取。<button onClick={retry}>重试读取补充回应</button></p>
      : !value || value.state === "pending" ? <p role="status">正在等待补充回应的保存与发布。</p>
      : response?.status === "available" && response.proposal ? <FocusAnswer proposal={response.proposal} onInspect={onInspect}/>
      : <p role="status">{FOCUS_REASONS[response?.reason_code ?? value.reason_code ?? ""] ?? "本次没有有效补充回应。"} 基础研究按独立保存记录呈现。</p>}
  </section>;
}
