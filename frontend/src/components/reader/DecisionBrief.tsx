import type { RunViewEnvelopeDTO } from "../../api/contracts";

export interface DecisionBriefProps {
  envelope: RunViewEnvelopeDTO;
  onOpenAudit(): void;
}

function qualityLabel(level: string): string {
  return {
    healthy: "数据健康",
    limited: "数据受限",
    conflicted: "数据冲突",
    unknown: "数据状态未知",
  }[level] ?? "版本不支持";
}

export function DecisionBrief({ envelope, onOpenAudit }: DecisionBriefProps): JSX.Element {
  const { run, brief, data_quality, legacy_fallback } = envelope.view;
  const value = brief.value;
  const summary = value?.executive_summary;
  const execution = value?.execution;
  const hasLimitations = data_quality.degraded_capabilities.length + data_quality.unavailable_capabilities.length > 0;

  return (
    <section className="decision-brief" data-ready="true">
      <header className="decision-brief-head">
        <div>
          <span className="eyebrow">研究决策</span>
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
              <span>研究评级</span>
              <strong>{value.research_rating}</strong>
            </div>
            <div>
              <span>实际执行</span>
              <strong>
                {execution?.availability === "ready" && execution.effective_action
                  ? `${execution.effective_action} ${execution.effective_quantity ?? 0}`
                  : "不可用"}
              </strong>
            </div>
            <div>
              <span>运行时长</span>
              <strong>{run.duration_ms == null ? "进行中" : `${Math.round(run.duration_ms / 1000)} 秒`}</strong>
            </div>
          </div>
          <div className="brief-summary">
            <h3>结论</h3>
            {summary ? <p>{summary.text}</p> : <p className="placeholder">本次运行没有可验证的公开结论摘要。</p>}
          </div>
          <BriefClaims title="核心驱动" claims={value.drivers} empty="没有带可解析证据引用的核心驱动。" />
          <BriefClaims title="主要风险" claims={value.risks} empty="没有已公开的主要风险条目。" />
          <BriefClaims title="验证节点" claims={value.catalysts} empty="本次运行没有公开验证节点。" />
        </>
      ) : (
        <div className="brief-legacy">
          <h3>此运行尚无读者投影</h3>
          <p>
            该历史运行保留了完整审计事实，但没有当时已提交的类型化公共输出。
            为避免从 Markdown 猜测结论，系统不会将其伪装成可验证摘要。
          </p>
          {legacy_fallback?.final_signal ? <p>原始最终信号：<strong>{legacy_fallback.final_signal}</strong></p> : null}
        </div>
      )}

      {hasLimitations ? (
        <div className="brief-quality-note">
          {data_quality.unavailable_capabilities.length > 0 ? `不可用：${data_quality.unavailable_capabilities.join("、")}。` : ""}
          {data_quality.degraded_capabilities.length > 0 ? `已降级：${data_quality.degraded_capabilities.join("、")}。` : ""}
        </div>
      ) : null}

      <button type="button" className="brief-audit-command" onClick={onOpenAudit}>
        打开审计阅读器
      </button>
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
