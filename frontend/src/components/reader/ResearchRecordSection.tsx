import type { QuantitativeMetricV1DTO, ResearchRecordResponseDTO, ResearchRecordV1DTO, SourceEvidenceV1DTO } from "../../api/contracts";

const CONTENT_LABELS = { excerpt: "原文摘录", source_fields: "原始数据字段", saved_summary: "已保存摘要" };

export function SourceContent({ evidence }: { evidence: SourceEvidenceV1DTO }): JSX.Element {
  const content = evidence.content;
  return <section className="record-source-content">
    <h4>{content === null ? "来源内容未保存" : CONTENT_LABELS[content.kind]}</h4>
    {content === null ? <p>当前记录只保存了来源信息，无法展示原文。系统不会在打开引用时重新取数或生成摘要。</p> : <>
      <pre>{content.text}</pre>
      <p className="record-meta">{content.locator_label}{content.truncated ? " · 内容已截取，不能视为全文" : ""}</p>
    </>}
  </section>;
}

const UNAVAILABLE_LABELS: Record<string, string> = {
  qualified_benchmark_not_supplied: "未取得符合口径的基准行情",
  price_window_or_vintage_unqualified: "行情窗口或历史时点资格不足",
  ohlc_not_supplied: "缺少开盘、最高、最低或收盘价字段",
  metric_not_calculated: "本次未计算该指标",
};
const VERIFICATION_LABELS = { supports: "支持", contradicts: "反驳", inconclusive: "仍不确定", unavailable: "无法核查" };
const DIMENSION_LABELS = { operating_quality: "经营质量", valuation: "估值", market_context: "市场背景", catalyst_delivery: "催化兑现", holding_thesis: "原持仓假设" };
const ASSESSMENT_STATUS_LABELS = { supported: "有事实支持", conditional: "有条件判断", unresolved: "待核查" };

function ClaimEvidence({ record, claimId }: { record: ResearchRecordV1DTO; claimId: string }): JSX.Element | null {
  const claim = record.claims.find((item) => item.claim_id === claimId);
  if (!claim) return null;
  const supportingFacts = record.claims.filter((item) => claim.supporting_fact_ids.includes(item.claim_id));
  const evidenceIds = new Set([...claim.evidence_ids, ...supportingFacts.flatMap((fact) => fact.evidence_ids)]);
  const sources = record.evidence.filter((item) => evidenceIds.has(item.evidence_id));
  return <article className="record-evidence" data-claim={claimId}>
    <p>{claim.kind === "fact" ? "事实" : claim.kind === "inference" ? "推断" : "待查"} · {claim.statement}</p>
    <details><summary>核对依据与保存原文</summary>
      {supportingFacts.map((fact) => <p key={fact.claim_id}>支撑事实：{fact.statement}</p>)}
      {sources.map((source) => <section key={source.evidence_id}>
        <h4>{source.source_name}</h4><SourceContent evidence={source} />
        <p className="record-meta">{source.availability === "available" ? "来源记录可用" : "来源记录不可用或未验证"}</p>
      </section>)}
      {sources.length === 0 ? <p>没有可展示的来源记录。</p> : null}
      {claim.limitations.map((limitation, index) => <p className="record-meta" key={index}>{limitation}</p>)}
    </details>
  </article>;
}

function NativeAssessment({ record }: { record: ResearchRecordV1DTO }): JSX.Element | null {
  const assessment = record.assessment;
  if (!assessment) return null;
  const primaryChallenge = record.challenges.find((item) => item.challenge_id === assessment.primary_challenge_id);
  const primaryAssessment = assessment.challenge_assessments.find((item) => item.challenge_id === assessment.primary_challenge_id);
  const criticalChallenges = record.challenges.filter((item) => item.severity === "critical");
  return <section aria-label="研究简报">
    <h3>研究判断</h3>
    <p className="record-meta">截至 {record.analysis_date}{assessment.forward_window_calendar_days === 84 ? " · 展望 84 个日历日" : ""}</p>
    <p>{assessment.research_question}</p>
    <strong>{assessment.judgement}</strong>
    {assessment.quality === "LOW_CONFIDENCE" || assessment.completeness === "partial" ? <p role="status">证据受限：本次判断为部分研究，需继续核查。</p> : null}
    <h4>关键依据</h4>
    {assessment.key_claim_ids.slice(0, 3).map((claimId) => <ClaimEvidence key={claimId} record={record} claimId={claimId} />)}
    {assessment.key_claim_ids.length === 0 ? <p>当前没有可展示的重点依据。</p> : null}
    <h4>主要风险与疑点</h4>
    <p>{primaryChallenge?.statement ?? (record.challenges.length > 0 ? "挑战条目尚未确定主次，请查看完整记录。" : "本次未形成挑战条目；不代表不存在风险。")}</p>
    {primaryChallenge ? <p className="record-meta">{primaryChallenge.severity === "critical" ? "关键挑战" : "挑战"} · 尚未解决{primaryAssessment ? `：${primaryAssessment.rationale}` : ""}</p> : null}
    {criticalChallenges.length > 0 ? <p className="record-meta">共 {criticalChallenges.length} 项关键挑战尚未解决，完整条目见下方验证记录。</p> : null}
    <h4>下一步核查</h4><p>{assessment.next_check}</p>
    <details><summary>分项判断与覆盖限制</summary>
      {assessment.dimensions.map((dimension) => <section key={dimension.dimension}>
        <h4>{DIMENSION_LABELS[dimension.dimension]} · {ASSESSMENT_STATUS_LABELS[dimension.status]}</h4>
        <p>{dimension.judgement}</p>
        {dimension.claim_ids.map((claimId) => <ClaimEvidence key={claimId} record={record} claimId={claimId} />)}
        {dimension.challenge_ids.map((challengeId) => <p key={challengeId}>未解决挑战：{record.challenges.find((item) => item.challenge_id === challengeId)?.statement}</p>)}
        {dimension.limitations.map((limitation, index) => <p className="record-meta" key={index}>{limitation}</p>)}
      </section>)}
      {assessment.limitations.map((limitation, index) => <p className="record-meta" key={index}>{limitation}</p>)}
    </details>
  </section>;
}

function metricValue(metric: QuantitativeMetricV1DTO): string {
  if (metric.availability !== "available" || metric.value === null || !Number.isFinite(metric.value)) return "暂不可用";
  if (metric.unit.endsWith("return_fraction")) return new Intl.NumberFormat("zh-CN", { style: "percent", maximumFractionDigits: 2 }).format(metric.value);
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(metric.value) + (metric.unit === "CNY/share" ? " 元/股" : "");
}

function MetricCard({ metric }: { metric: QuantitativeMetricV1DTO }): JSX.Element {
  return <article className="record-metric">
    <h4>{metric.label}</h4><strong>{metricValue(metric)}</strong>
    <details><summary>口径与依据</summary>
      <p>{metric.method}</p><p>{metric.window_start ?? "—"} → {metric.window_end ?? "—"}</p>
      <p>样本 {metric.sample_size ?? "未取得"}{metric.tail_sample_size === null ? "" : ` · 尾部样本 ${metric.tail_sample_size}`}</p>
      {metric.unavailable_reason ? <p>不可用原因：{UNAVAILABLE_LABELS[metric.unavailable_reason] ?? "数据或样本未满足计算要求"}</p> : null}
      {metric.limitations.includes("fewer_than_five_tail_observations") ? <p>尾部样本少于 5 个，分位与 ES 估计不稳定。</p> : null}
      <p>算法 {metric.calculation_version}</p>
    </details>
  </article>;
}

export function ResearchRecordSection({ runId, response, loading, error }: {
  runId: string; response: ResearchRecordResponseDTO | null; loading: boolean; error: boolean;
}): JSX.Element | null {
  if (loading) return <p className="record-meta" aria-busy="true">正在读取保存的证据与计算记录…</p>;
  if (error) return <p className="record-meta" role="status">证据与计算记录暂时无法读取。</p>;
  if (response === null || response.run_id !== runId) return null;
  if (response.state === "unavailable") return <p className="record-meta" role="status">
    {response.reason_code === "not_published" ? "该运行未保存新版证据与计算记录。" : "新版证据与计算记录未通过读取校验。"}
  </p>;
  const record = response.record;
  if (record.run_id !== runId) return null;
  const preferred = record.metrics.filter((metric) => /\.(annualized_volatility|historical_var_95|max_drawdown|atr_14)$/.test(metric.metric_id));
  const primary = (preferred.length > 0 ? preferred : record.metrics).slice(0, 4);
  const primaryIds = new Set(primary.map((metric) => metric.metric_id));
  const additional = record.metrics.filter((metric) => !primaryIds.has(metric.metric_id));
  return <section className="research-record" data-run={runId} aria-label="证据与计算记录">
    <NativeAssessment record={record} />
    {record.metrics.length > 0 ? <section aria-label="量化摘要">
      <h3>量化背景</h3>
      <p className="record-meta">代码计算的历史描述指标；不代表价值区间或未来损失上限。</p>
      <div className="record-metric-grid">{primary.map((metric) => <MetricCard key={metric.metric_id} metric={metric} />)}</div>
      {additional.length > 0 ? <details><summary>更多量化指标（{additional.length}）</summary>
        <div className="record-metric-grid">{additional.map((metric) => <MetricCard key={metric.metric_id} metric={metric} />)}</div>
      </details> : null}
    </section> : null}
    <details className="record-detail"><summary>查看证据、假设与验证记录</summary>
      <p>{record.verifications.length === 0 ? "尚未执行独立工具验证。推断、反证处理意见和模型置信度都不等于验证结果。" : `保存了 ${record.verifications.length} 次验证执行；各项结果如下。`}</p>
      {record.hypotheses.map((hypothesis) => <article key={hypothesis.hypothesis_id}>
        <h4>{hypothesis.origin === "adapted_inference" ? "待验证推断（来自原流程）" : "研究假设"}</h4>
        <p>{record.claims.find((claim) => claim.claim_id === hypothesis.claim_id)?.statement}</p>
        {hypothesis.invalidation_conditions.length > 0 ? <p>推翻条件：{hypothesis.invalidation_conditions.join("；")}</p> : <p className="record-meta">原流程未记录明确的推翻条件。</p>}
      </article>)}
      {record.challenges.map((challenge) => <article key={challenge.challenge_id}>
        <h4>挑战</h4><p>{challenge.statement}</p><p>拟核查：{challenge.proposed_test}</p>
      </article>)}
      {record.verifications.map((verification) => <article key={verification.verification_id}>
        <h4>{verification.scope === "predicate_only" ? "条件核查" : "验证执行"} · {VERIFICATION_LABELS[verification.status]}</h4>
        {verification.scope === "predicate_only" ? <>
          <p>核查条件：{verification.condition_text}</p>
          <p className="record-meta">仅核查指定条件，不证明整条假设，也不自动关闭挑战。</p>
        </> : null}
        <p>{verification.result}</p>
      </article>)}
      <h4>保存的来源内容</h4>
      {record.evidence.map((evidence) => <details key={evidence.evidence_id} className="record-evidence">
        <summary>{evidence.source_name}</summary><SourceContent evidence={evidence} />
        <p className="record-meta">{evidence.availability === "available" ? "来源记录可用；引用支撑关系仍需核查" : "来源记录不可用或未验证"}</p>
      </details>)}
      {record.evidence.length === 0 ? <p>没有可展示的来源记录。</p> : null}
    </details>
  </section>;
}
