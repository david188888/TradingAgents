import { useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useDrawerFocus, useReturnFocus } from "../shared/drawerFocus";
import { ValuationPositionCard } from "./ValuationPositionCard";
import type { CheckObservationV1DTO, ChallengeAssessmentV2DTO, QuantitativeMetricV1DTO, ResearchRecordResponseDTO, ResearchRecordV1DTO, SourceEvidenceV1DTO } from "../../api/contracts";
import { limitationLabel } from "../../domain/researchCoverage";

const CONTENT_LABELS = { excerpt: "原文摘录", source_fields: "原始数据字段", saved_summary: "已保存摘要" };
const CHECK_LABELS = { operating_disclosures: "经营披露依据", cash_conversion: "现金流桥核对", valuation_context: "估值补充背景" };
const CHECK_STATUS = { passed: "所需证据已核对", unavailable: "所需证据不足", conflict: "数据冲突，待核查" };
const OUTCOME_LABELS = { evidence_sufficient: "证据子问题已回答", risk_supported: "数据支持所列风险", future_observation: "保留未来观察", unresolved: "尚未解决" };

function observationValue(item: CheckObservationV1DTO): string {
  const value = Number(item.value);
  if (!Number.isFinite(value)) return item.value;
  const format = (n: number) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(n);
  if (item.unit === "CNY") return Math.abs(value) >= 1e8 ? `${format(value / 1e8)} 亿元` : Math.abs(value) >= 1e4 ? `${format(value / 1e4)} 万元` : `${format(value)} 元`;
  return `${format(value)} ${item.unit === "CNY/share" ? "元/股" : item.unit}`;
}

function LocalChallengeResult({ item }: { item: ChallengeAssessmentV2DTO }): JSX.Element {
  return <section aria-label="挑战核查结果">
    <p><strong>{OUTCOME_LABELS[item.outcome]}</strong> · 经济判断仍待核查</p>
    {item.answered_question ? <p>本次回答范围：{item.answered_question}</p> : null}
    <p>{item.rationale}</p>
    {item.observation_date ? <p>后续观察日期：{item.observation_date}</p> : null}
    {item.observations.map(value => <p key={value.key}>{value.label}：{observationValue(value)}</p>)}
    {item.limitations.map((value, i) => <p className="record-meta" key={i}>{limitationLabel(value)}</p>)}
  </section>;
}

function LocalEvidenceChecks({ record, onInspect }: { record: ResearchRecordV1DTO; onInspect: InspectSources }): JSX.Element | null {
  const checks = record.evidence_checks;
  if (!checks) return null;
  return <section aria-label="证据核查">
    <h3>证据核查</h3>
    <p className="record-meta">按具体问题核对已保存资料。可选资料缺失会保留局部判断；核对通过仍需结合经济原因和后续变化。</p>
    {checks.checks.map(check => <details key={check.check_id} className="record-evidence">
      <summary>{CHECK_LABELS[check.check_id]} · {CHECK_STATUS[check.status]}</summary>
      <p>{check.question}</p>
      {check.observations.map(value => <p key={value.key}><strong>{value.label}：{observationValue(value)}</strong><br /><span className="record-meta">{value.method}</span></p>)}
      {check.limitations.map((value, i) => <p className="record-meta" key={i}>{limitationLabel(value)}</p>)}
      {check.missing.length > 0 ? <p className="record-meta">待补充或受限：{check.missing.map(limitationLabel).join("；")}</p> : null}
      {check.evidence_ids.length > 0 ? <button type="button" className="record-reference" onClick={event => onInspect(record.evidence.filter(source => check.evidence_ids.includes(source.evidence_id)), check.question, event.currentTarget)}>核对保存的依据</button> : null}
    </details>)}
  </section>;
}

export function SourceContent({ evidence }: { evidence: SourceEvidenceV1DTO }): JSX.Element {
  const content = evidence.content;
  return <section className="record-source-content">
    <h4>{content === null ? "来源内容未保存" : CONTENT_LABELS[content.kind]}</h4>
    {content === null ? <p>当前记录只保存了来源信息，无法展示原文。系统不会在打开引用时重新取数或生成摘要。</p> : <>
      <pre>{content.text}</pre>
      <p className="record-meta">{content.locator_label}{content.truncated ? " · 内容已截取，不能视为全文" : ""}</p>
    </>}
    <dl className="record-source-meta">
      <dt>可用时点</dt><dd>{evidence.usable_as_of ?? "未验证"}</dd>
      <dt>抓取时间</dt><dd>{evidence.captured_at ?? "未保存"}</dd>
      <dt>内容校验</dt><dd>{content?.content_sha256 ?? "未保存"}</dd>
    </dl>
    {evidence.public_url && /^https?:\/\//i.test(evidence.public_url) ? <a href={evidence.public_url} target="_blank" rel="noreferrer">打开公开来源</a> : null}
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

function claimText(statement: string): string {
  const match = /^合并财务字段：报告期 (\d{4}-\d{2}-\d{2})，(?:income|balancesheet|cashflow)\.(\w+) = ([\d.-]+) CNY。$/.exec(statement);
  const labels: Record<string, string> = { revenue: "营业收入", n_income: "净利润", n_income_attr_p: "归母净利润", total_assets: "总资产", total_liab: "总负债", n_cashflow_act: "经营现金流净额" };
  if (!match || !labels[match[2]] || !Number.isFinite(Number(match[3]))) return statement;
  const value = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(Number(match[3]) / 100000000);
  return `${match[1]} 报告期 · ${labels[match[2]]} ${value} 亿元（合并口径）`;
}

type InspectSources = (sources: SourceEvidenceV1DTO[], title: string, trigger: HTMLElement) => void;

function ClaimEvidence({ record, claimId, onInspect }: { record: ResearchRecordV1DTO; claimId: string; onInspect: InspectSources }): JSX.Element | null {
  const claim = record.claims.find((item) => item.claim_id === claimId);
  if (!claim) return null;
  const supportingFacts = record.claims.filter((item) => claim.supporting_fact_ids.includes(item.claim_id));
  const evidenceIds = new Set([...claim.evidence_ids, ...supportingFacts.flatMap((fact) => fact.evidence_ids)]);
  const sources = record.evidence.filter((item) => evidenceIds.has(item.evidence_id));
  return <article className="record-evidence" data-claim={claimId}>
    <p>{claim.kind === "fact" ? "事实" : claim.kind === "inference" ? "推断" : "待查"} · {claimText(claim.statement)}</p>
    <button type="button" className="record-reference" onClick={(event) => onInspect(sources, claim.statement, event.currentTarget)}>查看引用（{sources.length}）</button>
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

function NativeAssessment({ record, onInspect }: { record: ResearchRecordV1DTO; onInspect: InspectSources }): JSX.Element | null {
  const assessment = record.assessment;
  if (!assessment) return null;
  const primaryChallenge = record.challenges.find((item) => item.challenge_id === assessment.primary_challenge_id);
  const primaryAssessment = assessment.challenge_assessments.find((item) => item.challenge_id === assessment.primary_challenge_id);
  const criticalChallenges = record.challenges.filter((item) => item.severity === "critical");
  return <section aria-label="研究简报">
    <h3>研究判断</h3>
    <p className="record-meta">截至 {record.analysis_date}{assessment.forward_window_calendar_days === 84 ? " · 展望 84 个日历日" : ""}</p>
    <p>{assessment.research_question}</p>
    <p className="record-judgement">{assessment.judgement}</p>
    {assessment.quality === "LOW_CONFIDENCE" || assessment.completeness === "partial" ? <p role="status">证据受限：本次判断为部分研究，需继续核查。</p> : null}
    <div className="record-limits" aria-label="本次研究缺口">
      {assessment.dimensions.filter(d => d.status === "unresolved").map(d => <span key={d.dimension}>{DIMENSION_LABELS[d.dimension]}待核查</span>)}
      {record.limitations.filter(l => l.startsWith("native_stage_unavailable:")).map(l => <span key={l}>部分专项未形成合格输出</span>)}
    </div>
    <h4>主要风险与疑点</h4>
    <p>{primaryChallenge?.statement ?? (record.challenges.length > 0 ? "挑战条目尚未确定主次，请查看完整记录。" : "本次未形成挑战条目；不代表不存在风险。")}</p>
    {primaryChallenge ? <p className="record-meta">{primaryChallenge.severity === "critical" ? "关键挑战" : "挑战"} · {primaryAssessment ? OUTCOME_LABELS[primaryAssessment.outcome] : "尚未解决"}{assessment.schema_version === "research-assessment-v2" ? " · 经济判断仍待核查" : ""}{primaryAssessment ? `：${primaryAssessment.rationale}` : ""}</p> : null}
    {criticalChallenges.length > 0 ? <p className="record-meta">共 {criticalChallenges.length} 项关键{assessment.schema_version === "research-assessment-v2" ? "经济问题仍待核查" : "挑战尚未解决"}，完整条目见下方验证记录。</p> : null}
    <h4>关键依据</h4>
    {assessment.key_claim_ids.slice(0, 3).map((claimId) => <ClaimEvidence key={claimId} record={record} claimId={claimId} onInspect={onInspect} />)}
    {assessment.key_claim_ids.length === 0 ? <p>当前没有可展示的重点依据。</p> : null}

    <details><summary>分项判断与覆盖限制</summary>
      {assessment.dimensions.map((dimension) => <section key={dimension.dimension}>
        <h4>{DIMENSION_LABELS[dimension.dimension]} · {ASSESSMENT_STATUS_LABELS[dimension.status]}</h4>
        <p>{dimension.judgement}</p>
        {dimension.claim_ids.map((claimId) => <ClaimEvidence key={claimId} record={record} claimId={claimId} onInspect={onInspect} />)}
        {dimension.challenge_ids.map((challengeId) => <p key={challengeId}>未解决挑战：{record.challenges.find((item) => item.challenge_id === challengeId)?.statement}</p>)}
        {dimension.limitations.map((limitation, index) => <p className="record-meta" key={index}>{limitationLabel(limitation)}</p>)}
      </section>)}
      <h4>全局覆盖与专项待查</h4>
      <p className="record-meta">专项只读取对应证据子集；专项未见资料不等于整个研究没有资料。</p>
      {[...new Set([...record.limitations, ...assessment.limitations])].map((limitation, index) => <p className="record-meta" key={index}>{limitationLabel(limitation)}</p>)}
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
  const [inspection, setInspection] = useState<{ runId: string; sources: SourceEvidenceV1DTO[]; title: string } | null>(null);
  const focus = useReturnFocus();
  const closeInspection = useCallback(() => { setInspection(null); focus.release(); }, [focus.release]);
  const inspect: InspectSources = (sources, title, trigger) => {
    focus.remember(trigger);
    setInspection({ runId, sources, title });
  };
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
    <NativeAssessment record={record} onInspect={inspect} />
    <LocalEvidenceChecks record={record} onInspect={inspect} />
    <section aria-label="估值定位" className="record-valuation">
      <h3>估值定位与参考区间</h3>
      {record.valuation ? <>
        <p className="record-meta">报价截至 {record.valuation.inputs.snapshot?.as_of ?? record.analysis_date}。历史倍数为本次取数的回溯序列；参考区间依赖盈利和倍数假设。</p>
        {record.valuation.assessment.synthesis.contributing_anchor_ids.length === 1 ? <p className="record-meta">当前只有一个估值锚点，未做交叉验证；该区间不能视为充分估值。</p> : null}
        <ValuationPositionCard assessment={record.valuation.assessment} />
        <button type="button" className="record-reference" onClick={(event) => inspect(record.evidence.filter(source => record.valuation!.input_evidence_ids.includes(source.evidence_id)), "估值输入与来源", event.currentTarget)}>核对估值输入与来源</button>
        <details><summary>计算输入与校验</summary><pre>{JSON.stringify(record.valuation.inputs, null, 2)}</pre><p className="record-meta">输入 SHA256：{record.valuation.input_sha256}</p></details>
      </> : <p className="record-meta">本次没有可用的合格估值输入，无法计算参考区间；需补齐报价、历史倍数和年度归母净利润。</p>}
    </section>
    {record.metrics.length > 0 ? <section aria-label="量化摘要">
      <h3>量化背景</h3>
      <p className="record-meta">代码计算的历史描述指标；不代表价值区间或未来损失上限。</p>
      <div className="record-metric-grid">{primary.map((metric) => <MetricCard key={metric.metric_id} metric={metric} />)}</div>
      {additional.length > 0 ? <details><summary>更多量化指标（{additional.length}）</summary>
        <div className="record-metric-grid">{additional.map((metric) => <MetricCard key={metric.metric_id} metric={metric} />)}</div>
      </details> : null}
    </section> : null}
    {record.assessment ? <section className="record-next"><h3>下一步核查</h3><p>{record.assessment.next_check}</p></section> : null}
    <details className="record-detail"><summary>查看证据、假设与验证记录</summary>
      <p>{record.verifications.length === 0 ? (record.evidence_checks ? "已执行上述本地证据核查；尚未执行新增来源的独立工具验证。经济假设仍需后续验证。" : "尚未执行独立工具验证。推断、反证处理意见和模型置信度都不等于验证结果。") : `保存了 ${record.verifications.length} 次验证执行；各项结果如下。`}</p>
      {record.hypotheses.map((hypothesis) => <article key={hypothesis.hypothesis_id}>
        <h4>{hypothesis.origin === "adapted_inference" ? "待验证推断（来自原流程）" : "研究假设"}</h4>
        <p>{record.claims.find((claim) => claim.claim_id === hypothesis.claim_id)?.statement}</p>
        {hypothesis.invalidation_conditions.length > 0 ? <p>推翻条件：{hypothesis.invalidation_conditions.join("；")}</p> : <p className="record-meta">原流程未记录明确的推翻条件。</p>}
      </article>)}
      {record.challenges.map((challenge) => <article key={challenge.challenge_id}>
        <h4>挑战</h4><p>{challenge.statement}</p><p>拟核查：{challenge.proposed_test}</p>
        {record.assessment?.schema_version === "research-assessment-v2" ? record.assessment.challenge_assessments.filter(item => item.challenge_id === challenge.challenge_id).map(item => <LocalChallengeResult key={item.challenge_id} item={item} />) : null}
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
    {inspection?.runId === runId ? <SavedSourcesDialog sources={inspection.sources} title={inspection.title} onClose={closeInspection} /> : null}

  </section>;
}

function SavedSourcesDialog({ sources, title, onClose }: { sources: SourceEvidenceV1DTO[]; title: string; onClose(): void }): JSX.Element {
  const background = useMemo(() => [document.getElementById("root")], []);
  const { panelRef, onKeyDown } = useDrawerFocus({ open: true, trap: true, background, onClose });
  return createPortal(<div className="record-dialog-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside ref={panelRef} role="dialog" aria-modal="true" aria-label="保存的引用" className="record-source-dialog" onKeyDown={onKeyDown}>
      <header><h3>保存的引用</h3><button type="button" onClick={onClose} data-autofocus aria-label="关闭引用">关闭</button></header>
      <p>{title}</p><p className="record-meta">显示本次保存的证据内容，打开此处不会重新取数或调用模型。</p>
      {sources.map(source => <section key={source.evidence_id}><h4>{source.source_name}</h4><SourceContent evidence={source} /></section>)}
      {sources.length === 0 ? <p>没有可展示的来源记录。</p> : null}
    </aside>
  </div>, document.body);
}
