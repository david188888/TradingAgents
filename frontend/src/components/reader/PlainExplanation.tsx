import { FactualPremises } from "./FactualPremises";
import { createContext, useContext } from "react";
import type { ReportExplanationDTO } from "../../api/contracts";

export const ExplanationContext = createContext<ReportExplanationDTO | null>(null);

export function readableReference(data: ReportExplanationDTO | null, target: string, fallback: string) {
  const item = data?.indicators[target];
  return item ? `${item.label}${item.value === null ? "" : `：${item.value}`}` : fallback;
}

export function useReadableReference() {
  const data = useContext(ExplanationContext);
  return (target: string, fallback: string) => readableReference(data, target, fallback);
}

export function ExplainedText(props: { target: string; text: string; className?: string }) {
  return <><ExplanationTextBody {...props}/><FactualPremises text={props.text}/></>;
}

function ExplanationTextBody({ target, text, className }: { target: string; text: string; className?: string }) {
  const data = useContext(ExplanationContext);
  const indicator = data?.indicators[target];
  const model = data && ["available","partial"].includes(data.state) ? data.entries[target] : undefined;
  if (indicator) return <div className={`qr-plain-reading ${className ?? ""}`}>
    {indicator.value !== null ? <p className="qr-readable-value">{indicator.value}</p> : null}
    {indicator.scope ? <p className="qr-meta">{indicator.scope}</p> : null}
    <p>{indicator.definition}</p>
    {indicator.interpretation ? <p>{indicator.interpretation}</p> : null}
    {indicator.caution ? <p className="qr-plain-caution">{indicator.caution}</p> : null}
    <details><summary>专业表述与完整数值</summary><p>{indicator.professional}</p>
      {indicator.raw_value !== null ? <p className="qr-meta">保存数值：{indicator.raw_value} {indicator.raw_unit}</p> : null}
    </details>
  </div>;
  if (model) return <div className={`qr-plain-reading ${className ?? ""}`}>
    <span className="qr-meta">通俗解读 · 模型解释</span><p>{model.explanation}</p>
    {model.uncertainty ? <p className="qr-plain-caution">{model.uncertainty}</p> : null}
    <details><summary>专业原文</summary><p>{text}</p></details>
  </div>;
  return <><p className={className}>{text}</p>{data?.unavailable_targets[target] ? <p className="qr-meta">此段通俗解读暂缺，保留专业原文。</p> : null}</>;
}

export function ExplanationStatus({ value, error, submitting, retry, reload }: {
  value: ReportExplanationDTO | null; error: boolean; submitting: boolean; retry(): void; reload(): void;
}) {
  if (error) return <p className="qr-meta" role="status">通俗解读暂时无法读取。<button onClick={reload}>重新读取解读</button></p>;
  if (!value || value.state === "unsupported") return null;
  const text = {
    not_generated: value.eligible ? "指标解释已可阅读，模型通俗版尚未生成。" : "历史报告提供指标释义与数值整理；专业分析保留原文。",
    generating: "正在生成通俗解读；专业报告已可阅读。",
    available: "通俗解读已保存；可随时展开专业原文核对。",
    partial: "部分通俗解读已保存；尚未覆盖的段落保留专业原文。",
    failed: "本次通俗解读未完成；指标解释与专业报告仍可阅读。",
    interrupted: "通俗解读曾中断，系统没有自动重复调用。",
    corrupt: "保存的通俗解读未通过校验；专业报告仍可阅读。",
  }[value.state];
  const canRetry = value.eligible && ["failed", "interrupted", "not_generated"].includes(value.state);
  const recovery = value.state === "failed" ? ({
    not_signed_in: "请在模型与账户设置中登录后，再主动重试。",
    invalid_identity: "请在模型与账户设置中重新登录后，再主动重试。",
    session_changed: "账户会话已变化，请重新登录后再试。",
    subscription_sharing_usage_limit_exceeded: "当前模型额度不足，请处理额度后再主动重试。",
    subscription_sharing_user_not_eligible: "当前账户暂不能使用此调用，请核对账户权限。",
    subscription_sharing_unsupported_capability: "所选模型暂不支持此调用，请核对模型设置。",
    model_not_available: "所选模型暂不可用，请核对账户模型列表。",
    deadline_exceeded: "这次解读超过了等待时间，可以稍后主动重试。",
    invalid_response: "这次解释未能可靠对应原报告，已保留专业原文。",
  } as Record<string,string>)[value.reason_code ?? ""] : null;
  return <div className="qr-explanation-status" role="status"><span>{text}</span>
    {recovery ? <span>{recovery}</span> : null}
    {value.model ? <span className="qr-meta">解释模型：{value.model}</span> : null}
    {canRetry ? <button disabled={submitting} onClick={retry}>{submitting ? "正在提交…" : "生成或重试通俗解读"}</button> : null}
  </div>;
}
