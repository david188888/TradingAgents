import type { ReaderBriefDTO, RunViewEnvelopeDTO } from "../../api/contracts";
import type { AuditOpenHandler } from "./AuditCenter";

export interface DecisionBriefProps {
  envelope: RunViewEnvelopeDTO;
  onOpenAudit: AuditOpenHandler;
}

function qualityLabel(level: string): string {
  return {
    healthy: "数据健康",
    limited: "数据受限",
    conflicted: "数据冲突",
    unknown: "数据状态未知",
  }[level] ?? "版本不支持";
}

function modeLabel(mode: "company_research" | "holding_review"): string {
  return mode === "holding_review" ? "持仓复盘" : "公司研究";
}

export function DecisionBrief({ envelope, onOpenAudit }: DecisionBriefProps): JSX.Element {
  const { run, brief, data_quality, legacy_fallback } = envelope.view;
  const value = brief.value;
  const summary = value?.executive_summary;
  const hasLimitations = data_quality.degraded_capabilities.length + data_quality.unavailable_capabilities.length > 0;

  return (
    <section className="decision-brief" data-ready="true">
      <header className="decision-brief-head">
        <div>
          <span className="eyebrow">研究结论</span>
          <h2>{run.ticker}</h2>
        </div>
        <div className="brief-statuses">
          <span className={`brief-status status-${run.status}`}>{run.status === "completed" ? "已完成" : run.status}</span>
          <span className={`brief-status quality-${data_quality.level}`}>{qualityLabel(data_quality.level)}</span>
        </div>
      </header>

      {value ? (
        <>
          <div className="decision-result-grid">
            <div>
              <span>研究模式</span>
              <strong>{modeLabel(run.mode)}</strong>
            </div>
            <div>
              <span>研究倾向</span>
              <strong>{value.research_rating ?? "证据待补充"}</strong>
            </div>
            <div>
              <span>运行时长</span>
              <strong>{run.duration_ms == null ? "进行中" : `${Math.round(run.duration_ms / 1000)} 秒`}</strong>
            </div>
          </div>
          <div className="brief-summary">
            <h3>结论</h3>
            {summary ? <p>{summary.text}</p> : value.learning_summary ? <p>{value.learning_summary.inferences[0] ?? "本次研究保留为待验证结论。"}</p> : <p className="placeholder">本次运行没有可验证的公开结论摘要。</p>}
          </div>
          {value.learning_summary ? <LearningSummary summary={value.learning_summary} /> : null}
          {value.holding_review ? <HoldingReview review={value.holding_review} /> : null}
          <BriefClaims title="核心驱动" claims={value.drivers} empty="没有带可解析证据引用的核心驱动。" />
          <BriefClaims title="主要风险" claims={value.risks} empty="没有已公开的主要风险条目。" />
          <BriefClaims title="验证节点" claims={value.catalysts} empty="本次运行没有公开验证节点。" />
        </>
      ) : (
        <div className="brief-legacy">
          <h3>此运行尚无结构化研究摘要</h3>
          <p>
            该运行保留了完整审计事实，但没有已提交的类型化研究结论。
            为避免从 Markdown 猜测结论，系统不会把它伪装成可验证摘要；可在审计中心按需查看报告与证据。
          </p>
          {legacy_fallback?.final_signal ? <p>运行结果：<strong>{legacy_fallback.final_signal}</strong></p> : null}
        </div>
      )}

      {hasLimitations ? (
        <div className="brief-quality-note">
          {data_quality.unavailable_capabilities.length > 0 ? `不可用：${data_quality.unavailable_capabilities.join("、")}。` : ""}
          {data_quality.degraded_capabilities.length > 0 ? `已降级：${data_quality.degraded_capabilities.join("、")}。` : ""}
        </div>
      ) : null}

      <button
        type="button"
        className="brief-audit-command"
        onClick={(event) => onOpenAudit({ section: "overview" }, event.currentTarget)}
      >
        进入审计中心
      </button>
    </section>
  );
}

function LearningSummary({ summary }: { summary: NonNullable<ReaderBriefDTO["learning_summary"]> }): JSX.Element {
  const scenarioRows = [["上行", summary.upside], ["基准", summary.base], ["下行", summary.downside]] as const;
  return (
    <section className="brief-claims learning-summary">
      <h3>研究摘要</h3>
      <p>置信度：{Math.round(summary.confidence * 100)}%</p>
      <BriefTextList title="事实" items={summary.facts} empty="暂无已整理事实。" />
      <BriefTextList title="推论" items={summary.inferences} empty="暂无额外推论。" />
      <BriefTextList title="未知与待验证" items={summary.unknowns} empty="暂无额外未知项。" />
      <h4>三种情景</h4>
      <ul>{scenarioRows.map(([label, scenario]) => <li key={label}><strong>{label}：{scenario.title}</strong>。条件：{scenario.condition}；研究含义：{scenario.implication}</li>)}</ul>
      <BriefTextList title="催化剂" items={summary.catalysts} empty="暂无已验证催化剂。" />
      <BriefTextList title="失效条件" items={summary.invalidation_conditions} empty="暂无额外失效条件。" />
      <h4>下次复核</h4>
      <p>{summary.next_review}</p>
      {summary.holding_thesis_assessment ? <><h4>持仓理由复核</h4><p>当前证据评估：{summary.holding_thesis_assessment.status}。{summary.holding_thesis_assessment.rationale}</p><p>当前可观察研究假设：{summary.holding_thesis_assessment.current_research_hypothesis}</p></> : null}
    </section>
  );
}

function BriefTextList({ title, items, empty }: { title: string; items: string[]; empty: string }): JSX.Element {
  return <><h4>{title}</h4>{items.length ? <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="placeholder">{empty}</p>}</>;
}

function HoldingReview({ review }: { review: NonNullable<ReaderBriefDTO["holding_review"]> }): JSX.Element {
  const unavailable = (item: { status: string; reason_code?: string }): string =>
    item.status === "available" ? "可计算" : `暂不可计算：${item.reason_code ?? "unknown"}`;
  return (
    <section className="brief-claims holding-review-summary">
      <h3>持仓复盘</h3>
      <ul>
        <li>原始理由：{review.original_thesis.status === "provided" ? "已提供" : `未提供（${review.original_thesis.reason_code}）`}</li>
        <li>集中度：{review.concentration.status === "available" ? `${((review.concentration.weight ?? 0) * 100).toFixed(1)}%` : unavailable(review.concentration)}</li>
        <li>未实现盈亏：{review.unrealized_pnl.status === "available" ? `${review.unrealized_pnl.amount?.toFixed(2) ?? "—"}（${((review.unrealized_pnl.return_ratio ?? 0) * 100).toFixed(1)}%）` : unavailable(review.unrealized_pnl)}</li>
        <li>情景敏感性：{review.scenario_sensitivity.status === "available" ? `每变动 1 个价格单位，持仓市值变动 ${review.scenario_sensitivity.value_change_per_price_unit ?? "—"}` : unavailable(review.scenario_sensitivity)}</li>
      </ul>
    </section>
  );
}

function BriefClaims({ title, claims, empty }: { title: string; claims: Array<{ claim_id: string; text: string }>; empty: string }): JSX.Element {
  return (
    <section className="brief-claims">
      <h3>{title}</h3>
      {claims.length ? (
        <ul>{claims.map((claim) => <li key={claim.claim_id}>{claim.text}</li>)}</ul>
      ) : <p className="placeholder">{empty}</p>}
    </section>
  );
}
