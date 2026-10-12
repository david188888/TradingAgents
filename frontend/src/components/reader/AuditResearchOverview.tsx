import type { AuditSummaryDTO, ReaderProcessDTO, ResearchRecordResponseDTO } from "../../api/contracts";
import { AGENT_LABELS, outputLabel, STATUS_LABELS } from "../../domain/readerExplanation";

const SOURCE_FAILURES: Record<string, string> = {
  document_parser_not_installed: "公告已取得，但本机缺少正文解析工具。",
  source_transport_unavailable: "部分资料来源连接失败，未取得可用内容。",
  document_fetch_failed: "部分公告正文未能下载，不能据公告标题推断具体内容。",
  document_parse_failed: "部分公告正文未能可靠解析，相关内容未采用。",
};

export function AuditResearchOverview({ summary, process, response, loading, error, onRetry }: {
  summary: AuditSummaryDTO; process: ReaderProcessDTO | null; response: ResearchRecordResponseDTO | null;
  loading: boolean; error: boolean; onRetry(): void;
}) {
  const record = response?.state === "ready" ? response.record : null;
  const assessment = record?.assessment;
  const unknowns = record?.claims.filter(item => item.kind === "unknown") ?? [];
  const failed = process?.roles.filter(role => ["failed", "cancelled", "interrupted"].includes(role.status)) ?? [];
  const hasReport = summary.counts.reports > 0 || record !== null;
  const missingPublication = response?.state === "unavailable" && ["not_published", "publication_failed"].includes(response.reason_code);
  const resultTitle = record ? "已发布研究报告" : hasReport ? "已保存报告，当前研究正文未能核验" : missingPublication ? "本次未发布研究报告" : loading ? "正在核对研究结果…" : response ? "研究记录未通过读取核验" : "研究结果暂时无法核验";
  return <div className="audit-research-overview">
    <section className="audit-research-result">
      <span className="eyebrow">{summary.run.ticker} · 研究检查</span>
      <h4>{resultTitle}</h4>
      <p>{assessment ? assessment.quality === "PASS" && assessment.completeness === "complete" ? "报告通过当前发布检查；判断仍须结合依据与风险阅读。" : "报告存在证据或研究环节限制，不能当作充分验证的公司结论。" : hasReport ? "请回到报告核对依据与限制；技术记录完整不代表研究判断可靠。" : missingPublication ? "当前没有可供判断这家公司的最终结论。已保存的过程记录不等于已通过核验的研究成果。" : "当前无法核验研究正文是否可用，请重新读取研究检查。不能把读取失败解释成没有报告。"}</p>
      {record ? <p>已发布记录包含 {record.evidence.length} 项来源、{record.claims.filter(item => item.kind === "fact").length} 条事实；数量不代表覆盖充分。</p> : null}
    </section>
    {error ? <p role="status">部分研究检查暂时无法读取。<button onClick={onRetry}>重新读取研究检查</button></p> : null}
    <section>
      <h4>失败位置与原因</h4>
      {loading ? <p aria-busy="true">正在读取环节状态…</p> : failed.length ? failed.map(role => {
        const failures = process?.model_failures?.filter(item => item.stage === role.role_key) ?? [];
        return <article className="audit-research-issue" key={role.role_key}><strong>{AGENT_LABELS[role.role_key]} · {STATUS_LABELS[role.status]}</strong>{failures.length ? failures.map((item, index) => <p key={index}>{item.safe_message}</p>) : <p>本环节未能形成可采用的结果，具体原因未记录。</p>}</article>;
      }) : <p>{!process || process.availability === "not_applicable" ? "历史记录未提供可核验的逐环节失败原因。" : summary.run.status === "completed" ? "未记录失败环节；完成状态不能证明研究充分。" : "运行已终止，尚未记录可定位的失败环节。"}</p>}
    </section>
    <section>
      <h4>资料缺口与使用限制</h4>
      {process?.source_failures.length ? process.source_failures.map(code => <p key={code}>{SOURCE_FAILURES[code] ?? "部分资料未通过获取或来源检查，请结合报告的来源与未知项核对。"}</p>) : <p>{record ? "未记录额外的来源获取失败；仍须核对下列研究未知项。" : "尚无已发布记录可供核对资料覆盖。未发布不代表没有资料，也不能据此认定资料充分。"}</p>}
      {record?.limitations.slice(0, 3).map((item, index) => <p key={index}>{item}</p>)}
      {unknowns.slice(0, 5).map(item => <p key={item.claim_id}>{item.statement}</p>)}
      {unknowns.length > 5 || (record?.limitations.length ?? 0) > 3 ? <p>其余未知项与限制请在完整研究记录中核对。</p> : null}
      {record && !unknowns.length ? <p>记录未列出未知项；这不能证明公司没有风险。</p> : null}
    </section>
    <section className="audit-research-stages">
      <h4>各环节留下了什么</h4>
      {process?.roles.length ? process.roles.map(role => <article key={role.role_key}><strong>{AGENT_LABELS[role.role_key]}</strong><span>{STATUS_LABELS[role.status] ?? "状态未记录"}</span><p>{role.status === "not_reached" ? "后续未执行" : outputLabel(role.output_availability, role.reason_code, summary.run.status)}</p></article>) : <p>此运行没有可核验的研究环节记录。</p>}
      <p>回顾可用的研究正文和依据，请回到主面板中的“研究如何推进”。</p>
    </section>
  </div>;
}
