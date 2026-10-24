import type { ResearchRecordDTO, ResearchRecordV2DTO, SearchRoleDTO } from '../../api/contracts';
import type { EvidenceSelection } from './ReaderEvidence';

const roles: Record<SearchRoleDTO, string> = {operating_quality:'经营研究', event_context:'事件研究', market_context:'市场研究'};
const dispositions = {maintained:'维持原有条件判断', revised:'修正原推断', withdrawn:'撤回原推断', unanswerable:'现有材料仍无法回答'};
const fieldLabels: Record<string,string> = {revenue:'营业收入', n_income:'合并净利润', n_income_attr_p:'归母净利润', n_cashflow_act:'经营现金流净额', name:'公司名称', list_date:'上市日期', introduction:'公司简介', main_business:'主营业务', industry:'所属行业'};
const stops: Record<string,string> = {
  search_disabled:'本次研究已关闭联网搜索，未解决问题保留待查',
  no_eligible_gaps:'没有需要继续搜索的明确缺口', no_qualified_delta:'本轮未取得新的合格材料，停止补搜',
  round_limit_reached:'已达到三轮补搜上限，剩余问题保留待查', round_budget_exhausted:'补搜轮次额度已用完',
  search_budget_or_time_exhausted:'搜索次数或活动时间已用完，剩余问题保留待查',
};

function unreviewed(record: ResearchRecordV2DTO): SearchRoleDTO[] {
  const baseline = record.snapshots.find(s=>s.snapshot_id===record.dialogue?.input_snapshot_id)?.version ?? 0;
  return (Object.keys(roles) as SearchRoleDTO[]).filter(role=>{
    const evidence = record.claims.filter(c=>c.kind==='fact' && c.limitations.includes(`native_dimension:${role}`)
      && !c.limitations.includes('native_dimension:company_introduction')).flatMap(c=>c.evidence_ids);
    const changed = Math.max(baseline, ...evidence.map(id=>record.snapshots.find(s=>s.evidence_ids.includes(id))?.version ?? baseline));
    const reviewed = Math.max(baseline, ...record.search_reviews.filter(r=>r.role===role).map(r=>record.snapshots.find(s=>s.snapshot_id===r.input_snapshot_id)?.version ?? baseline));
    return changed > reviewed;
  });
}

export function SearchResearch({record, onInspect}: {record: ResearchRecordDTO; onInspect?(selection: EvidenceSelection, trigger: HTMLElement): void}) {
  if (record.schema_version !== 'research-record-v2') return null;
  const missing = new Set(record.search_batches.flatMap(b=>b.requests.flatMap(r=>r.requirements))
    .filter(r=>!record.recovered_fields.some(f=>f.field===r.field && f.period===r.period && f.basis===r.basis && f.unit===r.unit))
    .map(f=>fieldLabels[f.field] ?? f.field));
  return <section className="qr-report-section" aria-label="联网补证与专项复核">
    <h2>联网补证与专项复核</h2>
    <p className="qr-meta">公司身份与量化数据优先使用专用接口；新闻、行业与竞争信息通过 DeepSeek 与 Tavily 双路搜索。新材料仅在通过来源与时间核对后参与研究。</p>
    {record.search_batches.map(batch=>{
      const request = batch.requests[0];
      if (!request) return null;
      const label = request.kind==='supplement' ? `第 ${request.round_id} 轮补证` : request.kind==='recovery' ? '接口补缺' : '初始双路搜索';
      const failed = [...new Set(batch.outcomes.filter(o=>o.status==='unavailable' || o.status==='failed' || o.status==='refused').map(o=>o.provider==='deepseek' ? 'DeepSeek' : 'Tavily'))];
      return <article className="qr-check" key={batch.batch_id}>
        <h3>{label}</h3>
        <p className="qr-meta">{[...new Set(batch.requests.map(r=>r.provider==='deepseek' ? 'DeepSeek' : 'Tavily'))].join(' · ')} · {batch.hits.length} 条合并发现记录</p>
        {failed.length ? <p>{failed.length===1 ? '单路降级' : '双路未取得可用结果'}：{failed.join('、')}；已保存材料与待查问题继续保留。</p> : null}
        {batch.hits.some(h=>!h.content && !h.document && h.summary) ? <p className="qr-meta">部分发现仅搜索摘要，未作为原文入库。</p> : null}
        {record.search_reviews.filter(r=>r.round_id===request.round_id && request.kind==='supplement').map(review=><div key={review.review_id}>
          <strong>{roles[review.role]} · {dispositions[review.disposition]}</strong><p>{review.rationale}</p>
          <p className="qr-meta">依据证据版本 V{record.snapshots.find(s=>s.snapshot_id===review.input_snapshot_id)?.version ?? '未知'}；原假设及原条件保留。</p>
          {review.new_risks.map((risk,i)=><p key={i}>新增待核查风险：{risk}</p>)}
        </div>)}
      </article>;
    })}
    {unreviewed(record).map(role=><p className="qr-boundary" key={role}>{roles[role]}有新材料尚未完成复核；不能沿用旧推断作为肯定性依据。</p>)}
    {record.recovered_fields.length ? <details><summary>接口补缺：已恢复 {record.recovered_fields.length} 个合格字段</summary>
      {record.recovered_fields.map((field,i)=><p key={`${field.evidence_id}.${field.field}.${i}`}>
        {fieldLabels[field.field] ?? field.field}{field.period ? ` · ${field.period}` : ''}：{field.value} {field.unit==='text' ? '' : field.unit}
        {onInspect ? <button className="qr-text-button" onClick={e=>onInspect({kind:'source', id:field.evidence_id},e.currentTarget)}>核对恢复字段的原文 →</button> : null}
      </p>)}
    </details> : null}
    {missing.size ? <p className="qr-meta">仍未恢复的请求字段：{[...missing].join('、')}。已取得的字段继续保留。</p> : null}
    <details><summary>证据版本与适用范围</summary>
      {record.snapshots.map(snapshot=><p key={snapshot.snapshot_id}>V{snapshot.version} · 保存 {snapshot.evidence_ids.length} 项来源。后续版本保留此前证据，原专项和复核各自绑定实际输入版本。</p>)}
    </details>
    {record.search_gaps.length ? <><h3>继续保留的待查问题</h3><ul>{record.search_gaps.map(gap=><li key={gap.gap_id}>{gap.question}</li>)}</ul></> : null}
    {record.search_stop_reasons.map(reason=><p className="qr-meta" key={reason}>{reason.startsWith('review_unavailable:') ? '相关专项未完成有效复核，保留待查。' : stops[reason] ?? '搜索已停止，未解决问题保留待查。'}</p>)}
  </section>;
}
