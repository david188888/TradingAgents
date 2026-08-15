import type { ResearchPackageDTO, MetricDefinitionDTO, MetricObservationDTO } from "../../api/contracts";

interface ResearchPackageSectionProps {
  researchPackage: ResearchPackageDTO;
}

function formatValue(value: number | null, unit: string): string {
  if (value === null) return "暂不可用";
  if (unit === "%") return `${(value * 100).toFixed(1)}%`;
  if (unit === "x") return `${value.toFixed(2)}x`;
  return `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${unit}`;
}

function statusLabel(observation: MetricObservationDTO | undefined): string {
  if (!observation) return "待补数据";
  if (observation.availability === "available") return "可用";
  return observation.unavailable_reason ?? "暂不可用";
}

function latestObservation(
  observations: MetricObservationDTO[],
  metricId: string,
  entityId: string,
): MetricObservationDTO | undefined {
  return observations
    .filter((item) => item.metric_id === metricId && item.entity_id === entityId)
    .sort((left, right) => right.as_of.localeCompare(left.as_of))[0];
}

function MetricDefinition({ definition }: { definition: MetricDefinitionDTO }): JSX.Element {
  return (
    <details className="research-metric-definition">
      <summary>{definition.label_zh}：怎么看？</summary>
      <div>
        <p>{definition.plain_explanation}</p>
        <dl>
          <div><dt>公式</dt><dd>{definition.formula_text}</dd></div>
          <div><dt>口径</dt><dd>{definition.unit}</dd></div>
          <div><dt>适用条件</dt><dd>{definition.validity_conditions.join("；") || "暂无"}</dd></div>
          <div><dt>常见误读</dt><dd>{definition.pitfalls.join("；") || "暂无"}</dd></div>
        </dl>
      </div>
    </details>
  );
}

export function ResearchPackageSection({ researchPackage }: ResearchPackageSectionProps): JSX.Element {
  const definitions = researchPackage.metric_definitions.filter((item) => item.required_inputs.length > 0);
  const targetEntity = researchPackage.target_entity_id ?? researchPackage.ticker;
  return (
    <section className="reader-section research-package-section" aria-label="指标与逻辑环">
      <div className="research-package-heading">
        <div>
          <span className="eyebrow">结构化研究包 · {researchPackage.schema_version}</span>
          <h3>核心指标与逻辑闭环</h3>
        </div>
        <span className="reader-tag reader-tag--muted">截止 {researchPackage.analysis_cutoff}</span>
      </div>
      <p className="research-package-note">
        数值只来自当前研究包；“暂不可用”表示没有足够的可验证输入，不代表指标等于零。
      </p>
      <div className="research-metric-table-wrap">
        <table className="research-metric-table">
          <caption>目标公司 {targetEntity} 的指标、历史和同行对比</caption>
          <thead><tr><th scope="col">指标</th><th scope="col">当前值</th><th scope="col">期间</th><th scope="col">同行对比</th><th scope="col">状态</th></tr></thead>
          <tbody>
            {definitions.map((definition) => {
              const observation = latestObservation(researchPackage.observations, definition.metric_id, targetEntity);
              const comparison = researchPackage.comparisons.find((item) => item.metric_id === definition.metric_id);
              return (
                <tr key={definition.metric_id}>
                  <th scope="row"><span>{definition.label_zh}</span><MetricDefinition definition={definition} /></th>
                  <td>{formatValue(observation?.value ?? null, definition.unit)}</td>
                  <td>{observation?.period ?? "未形成"}</td>
                  <td>{comparison?.availability === "available" && comparison.peer_median !== null
                    ? `同行中位数 ${formatValue(comparison.peer_median, definition.unit)} · ${comparison.target_percentile?.toFixed(0)} 分位`
                    : "同行比较不可用"}</td>
                  <td>{statusLabel(observation)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {researchPackage.unknowns.length ? (
        <div className="research-package-unknowns">
          <strong>当前保留的未知</strong>
          <ul>{researchPackage.unknowns.map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ) : null}
      {researchPackage.logic_edges.length ? (
        <section className="research-logic-loop" aria-label="逻辑闭环">
          <h4>逻辑边</h4>
          <ol>
            {researchPackage.logic_edges.map((edge) => (
              <li key={edge.edge_id} className={`research-logic-edge research-logic-edge--${edge.status}`}>
                <div><strong>{edge.from_node} → {edge.to_node}</strong><span>{edge.status}</span></div>
                <p>{edge.missing_evidence.length ? `缺口：${edge.missing_evidence.join("；")}` : "输入和证据已满足当前边的校验条件。"}</p>
                <small>下一验证：{edge.next_validation}。失效：{edge.invalidation}</small>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
}
