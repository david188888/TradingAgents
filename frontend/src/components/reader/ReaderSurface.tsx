import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type {
  CompanionSelectionDTO,
  LearningReaderV2DTO,
  PublicClaimV2DTO,
  ReaderEvidenceRefDTO,
  ReaderResponseDTO,
  ResearchScenarioDTO,
  ReviewItemDTO,
} from "../../api/contracts";
import { useCompanion } from "../../hooks/useCompanion";
import { useReader } from "../../hooks/useReader";
import { useResearchPackage } from "../../hooks/useResearchPackage";
import { CompanionPanel } from "./CompanionPanel";
import type { CompanionPanelMode } from "./CompanionPanel";
import { ThesisDiffSection } from "./ThesisDiffSection";
import { ResearchPackageSection } from "./ResearchPackageSection";
import type { AuditOpenHandler } from "./AuditCenter";

export interface ReaderSurfaceProps {
  runId: string;
  onOpenAudit?: AuditOpenHandler;
}

type CompanionMode = "closed" | CompanionPanelMode;
type CompanionSelectHandler = (
  selection: CompanionSelectionDTO,
  trigger: HTMLElement,
) => void;

const WIDE_COMPANION_QUERY = "(min-width: 1400px)";

function useWideCompanion(): boolean {
  const [wide, setWide] = useState(() => (
    typeof window === "undefined" || typeof window.matchMedia !== "function"
      ? true
      : window.matchMedia(WIDE_COMPANION_QUERY).matches
  ));

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(WIDE_COMPANION_QUERY);
    const handleChange = (event: MediaQueryListEvent): void => setWide(event.matches);
    setWide(query.matches);
    query.addEventListener("change", handleChange);
    return () => query.removeEventListener("change", handleChange);
  }, []);

  return wide;
}

function useDrawerBackgroundInert(
  active: boolean,
  layoutRef: RefObject<HTMLDivElement>,
): void {
  useEffect(() => {
    if (!active) return;
    const layout = layoutRef.current;
    if (layout === null) return;
    const main = layout.closest("main");
    const targets = [
      document.querySelector<HTMLElement>(".topbar"),
      document.querySelector<HTMLElement>(".sidebar"),
      ...Array.from(main?.children ?? []).filter(
        (item): item is HTMLElement => item instanceof HTMLElement && item !== layout,
      ),
    ].filter((item): item is HTMLElement => item !== null);
    const previous = targets.map((item) => ({
      item: item as HTMLElement & { inert: boolean },
      inert: (item as HTMLElement & { inert: boolean }).inert,
      ariaHidden: item.getAttribute("aria-hidden"),
    }));
    for (const { item } of previous) {
      item.inert = true;
      item.setAttribute("aria-hidden", "true");
    }
    return () => {
      for (const state of previous) {
        state.item.inert = state.inert;
        if (state.ariaHidden === null) state.item.removeAttribute("aria-hidden");
        else state.item.setAttribute("aria-hidden", state.ariaHidden);
      }
    };
  }, [active, layoutRef]);
}

function modeLabel(mode: "company_research" | "holding_review"): string {
  return mode === "holding_review" ? "持仓复盘" : "公司研究";
}

function tiltLabel(tilt: LearningReaderV2DTO["research_tilt"]): string {
  if (tilt === null) return "证据待补充";
  return {
    favorable: "偏多",
    neutral: "中性",
    cautious: "偏谨慎",
    insufficient_evidence: "证据不足",
  }[tilt];
}

function eligibilityLabel(
  eligibility: LearningReaderV2DTO["decision_eligibility"],
): string {
  return {
    full: "可决策",
    limited: "受限",
    none: "不出评级",
  }[eligibility];
}

function qualityLabel(level: LearningReaderV2DTO["data_quality"]["level"]): string {
  return {
    healthy: "健康",
    limited: "受限",
    conflicted: "冲突",
    blocked: "阻断",
  }[level];
}

/** Map an omission code to friendly Chinese; unknown codes surface raw. */
function omissionLabel(code: string): string {
  return ({
    "research_case.evidence_bound_claims_unavailable": "证据化结论暂不可用",
    "research_case.rating_withheld": "因证据不足未给评级",
    "research_case.evidence_key_unresolved": "部分证据引用无法解析，已剔除",
    "research_case.coverage_key_unresolved": "部分数据覆盖引用无法解析，已剔除",
    "research_case.claim_omitted_missing_evidence": "部分结论因缺少证据绑定被剔除",
    "research_case.claim_omitted_missing_supporting": "部分推断因缺少支撑结论被剔除",
    "research_case.claim_omitted_unsupported_evidence": "部分推断因引用的证据与其支撑事实无交集被剔除",
    "research_case.review_item_omitted": "部分复查项因引用无法解析被剔除",
    "research_case.scenarios_invalid_or_incomplete": "情景集不完整或未通过校验，暂不展示",
  })[code] ?? code;
}

function verdictLabel(verdict: LearningReaderV2DTO["evidence_verdict"]): string {
  return {
    PASS: "证据通过",
    LOW_CONFIDENCE: "证据置信度低",
    FAIL_STOP: "证据未通过",
    GATE_ERROR: "证据校验异常",
  }[verdict];
}

function pct(value: number | null): string | null {
  if (value == null) return null;
  return `${Math.round(value * 100)}%`;
}

function lensLabel(lens: LearningReaderV2DTO["analyst_cards"][number]["lens"]): string {
  return {
    market: "市场",
    fundamentals: "基本面",
    news: "新闻",
    sentiment: "情绪",
  }[lens];
}

function triggerLabel(item: ReviewItemDTO): string {
  const kind = {
    date: "日期",
    event: "事件",
    price: "价格",
    filing: "公告",
  }[item.trigger_kind];
  return `${kind}:${item.trigger_value}`;
}

function statusLabel(status: ReviewItemDTO["status"]): string {
  return {
    pending: "待验证",
    met: "已满足",
    invalidated: "已失效",
  }[status];
}

function availabilityLabel(
  availability: LearningReaderV2DTO["analyst_cards"][number]["availability"],
): string {
  return {
    ready: "就绪",
    limited: "受限",
    unavailable: "不可用",
  }[availability];
}

function ClaimRow({
  claim,
  evidenceRefs,
  onCompanionSelect,
}: {
  claim: PublicClaimV2DTO;
  evidenceRefs: Map<string, ReaderEvidenceRefDTO>;
  onCompanionSelect: CompanionSelectHandler;
}): JSX.Element {
  const confidence = pct(claim.confidence);
  const publicEvidence = claim.evidence_ref_ids.flatMap((refId) => {
    const ref = evidenceRefs.get(refId);
    return ref === undefined ? [] : [ref];
  });
  return (
    <li className="reader-claim">
      <div className="reader-claim-head">
        <p className="reader-claim-text">{claim.text}</p>
        <button
          type="button"
          className="reader-companion-trigger"
          aria-label={`查看论点伴读：${claim.text}`}
          onClick={(event) => onCompanionSelect(
            { kind: "claim", id: claim.claim_key },
            event.currentTarget,
          )}
        >
          查看伴读 <span aria-hidden="true">↗</span>
        </button>
      </div>
      <div className="reader-claim-meta">
        {confidence ? <span className="reader-claim-confidence">{confidence} 置信</span> : null}
        <span className="reader-claim-evidence">{claim.evidence_ref_ids.length} 份证据</span>
        {claim.supporting_claim_keys.length ? <span>{claim.supporting_claim_keys.length} 条支撑结论</span> : null}
        {claim.coverage_ref_ids.length ? <span>{claim.coverage_ref_ids.length} 处覆盖引用</span> : null}
        {claim.lifecycle_status !== "active" ? (
          <span className="reader-tag reader-tag--muted">
            {claim.lifecycle_status === "superseded" ? "已被取代" : "已失效"}
          </span>
        ) : null}
      </div>
      {publicEvidence.length ? (
        <div className="reader-evidence-links" aria-label="公开证据来源">
          {publicEvidence.map((ref) => (
            <button
              type="button"
              key={ref.ref_id}
              className="reader-evidence-link"
              aria-label={`查看证据伴读：${ref.source_label}`}
              onClick={(event) => onCompanionSelect(
                { kind: "evidence", id: ref.ref_id },
                event.currentTarget,
              )}
            >
              {ref.source_label}
            </button>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function ScenarioBlock({ scenario }: { scenario: ResearchScenarioDTO }): JSX.Element {
  const confidence = pct(scenario.confidence);
  return (
    <div className="reader-scenario">
      <h4>{scenario.title}</h4>
      <p>{scenario.research_implication}</p>
      {confidence ? <span className="reader-scenario-confidence">{confidence} 置信</span> : null}
    </div>
  );
}

function ReviewItemList({
  title,
  items,
  onCompanionSelect,
}: {
  title: string;
  items: ReviewItemDTO[];
  onCompanionSelect?: CompanionSelectHandler;
}): JSX.Element | null {
  if (!items.length) return null;
  return (
    <section className="reader-section reader-section--list">
      <h3>{title}</h3>
      <ul className="reader-review-list">
        {items.map((item) => (
          <li key={item.item_id}>
            <span className="reader-tag reader-tag--muted">{statusLabel(item.status)}</span>
            <p>{item.text}</p>
            <span className="reader-trigger">{triggerLabel(item)}</span>
            {onCompanionSelect ? (
              <button
                type="button"
                className="reader-companion-trigger"
                aria-label={`查看风险伴读：${item.text}`}
                onClick={(event) => onCompanionSelect(
                  { kind: "risk", id: item.item_id },
                  event.currentTarget,
                )}
              >
                查看伴读 <span aria-hidden="true">↗</span>
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TypedSurface({
  reader,
  onOpenAudit,
}: {
  reader: LearningReaderV2DTO;
  onOpenAudit?: AuditOpenHandler;
}): JSX.Element {
  const [selection, setSelection] = useState<CompanionSelectionDTO | null>(null);
  const [companionMode, setCompanionMode] = useState<CompanionMode>("closed");
  const triggerRef = useRef<HTMLElement | null>(null);
  const layoutRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);
  const wideCompanion = useWideCompanion();
  const companion = useCompanion(reader.run_id, selection);
  const { researchPackage } = useResearchPackage(reader.run_id);
  useDrawerBackgroundInert(companionMode === "drawer", layoutRef);
  useEffect(() => {
    const surface = surfaceRef.current as (HTMLElement & { inert: boolean }) | null;
    if (surface !== null) surface.inert = companionMode === "drawer";
    return () => {
      if (surface !== null) surface.inert = false;
    };
  }, [companionMode]);
  const evidenceRefs = useMemo(
    () => new Map(reader.evidence_refs.map((ref) => [ref.ref_id, ref])),
    [reader.evidence_refs],
  );
  const claimsByType = {
    fact: reader.claims.filter((c) => c.claim_type === "fact"),
    inference: reader.claims.filter((c) => c.claim_type === "inference"),
    unknown: reader.claims.filter((c) => c.claim_type === "unknown"),
  };
  const scenarioRows: Array<[string, ResearchScenarioDTO]> = reader.scenarios
    ? [["上行", reader.scenarios.upside], ["基准", reader.scenarios.base], ["下行", reader.scenarios.downside]]
    : [];

  const tiltConfidence = pct(reader.rating_confidence);

  const closeCompanion = useCallback((): void => {
    setCompanionMode("closed");
    setSelection(null);
    const trigger = triggerRef.current;
    if (trigger?.isConnected) {
      const surface = trigger.closest(".reader-surface") as (HTMLElement & { inert: boolean }) | null;
      if (surface !== null) {
        surface.inert = false;
        surface.removeAttribute("aria-hidden");
      }
      trigger.focus({ preventScroll: true });
    }
  }, []);

  const openCompanion = useCallback<CompanionSelectHandler>((next, trigger) => {
    triggerRef.current = trigger;
    setSelection(next);
    setCompanionMode((current) => {
      if (!wideCompanion) return "drawer";
      return current === "pinned" ? "pinned" : "temporary";
    });
  }, [wideCompanion]);

  useEffect(() => {
    setCompanionMode((current) => {
      if (current === "closed") return current;
      if (!wideCompanion) return "drawer";
      return current === "drawer" ? "temporary" : current;
    });
  }, [wideCompanion]);

  useEffect(() => {
    if (companionMode === "closed") return;
    const handleEscape = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeCompanion();
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [closeCompanion, companionMode]);

  return (
    <div ref={layoutRef} className={`reader-companion-layout reader-companion-layout--${companionMode}`}>
    <section
      ref={surfaceRef}
      className="reader-surface"
      aria-hidden={companionMode === "drawer" ? true : undefined}
    >
      <header className="reader-surface-head">
        <div>
          <span className="eyebrow">证据化研究结论 · ResearchCase v2</span>
          <h2>{reader.ticker}</h2>
        </div>
        <div className="reader-badges">
          <span className="reader-badge reader-badge--neutral">{modeLabel(reader.mode)}</span>
          <span className={`reader-badge ${tiltBadgeClass(reader)}`}>{tiltLabel(reader.research_tilt)}{tiltConfidence ? ` ${tiltConfidence}` : ""}</span>
          <span className={`reader-badge ${eligibilityBadgeClass(reader)}`}>{eligibilityLabel(reader.decision_eligibility)}</span>
          <span className={`reader-badge ${verdictBadgeClass(reader.evidence_verdict)}`}>{verdictLabel(reader.evidence_verdict)}</span>
          <span className={`reader-badge ${qualityBadgeClass(reader)}`}>{qualityLabel(reader.data_quality.level)}</span>
        </div>
      </header>

      {reader.omissions.length ? (
        <div className="reader-omission-note">
          {reader.omissions.map((code) => (
            <p key={code}>降级提示：{omissionLabel(code)}</p>
          ))}
        </div>
      ) : null}

      <ThesisDiffSection diff={reader.thesis_diff} evidenceRefs={reader.evidence_refs} />
      {researchPackage ? <ResearchPackageSection researchPackage={researchPackage} /> : null}

      <section className="reader-section reader-section--claims">
        <h3>事实</h3>
        {claimsByType.fact.length ? <ul className="reader-claims">{claimsByType.fact.map((claim) => <ClaimRow key={claim.claim_key} claim={claim} evidenceRefs={evidenceRefs} onCompanionSelect={openCompanion} />)}</ul> : <p className="placeholder">暂无事实结论。</p>}
      </section>
      <section className="reader-section reader-section--claims">
        <h3>推断</h3>
        {claimsByType.inference.length ? <ul className="reader-claims">{claimsByType.inference.map((claim) => <ClaimRow key={claim.claim_key} claim={claim} evidenceRefs={evidenceRefs} onCompanionSelect={openCompanion} />)}</ul> : <p className="placeholder">暂无推断结论。</p>}
      </section>
      <section className="reader-section reader-section--claims">
        <h3>待查</h3>
        {claimsByType.unknown.length ? <ul className="reader-claims">{claimsByType.unknown.map((claim) => <ClaimRow key={claim.claim_key} claim={claim} evidenceRefs={evidenceRefs} onCompanionSelect={openCompanion} />)}</ul> : <p className="placeholder">暂无待查结论。</p>}
      </section>

      {!reader.claims.length ? (
        <p className="reader-empty-claims">本次运行未产出证据化结论（见上方降级提示）。</p>
      ) : null}

      {scenarioRows.length ? (
        <section className="reader-section">
          <h3>情景</h3>
          <div className="reader-scenarios">
            {scenarioRows.map(([label, scenario]) => (
              <ScenarioBlock key={label} scenario={scenario} />
            ))}
          </div>
        </section>
      ) : null}

      <ReviewItemList title="催化剂" items={reader.catalysts} />
      <ReviewItemList title="失效条件" items={reader.invalidation_conditions} onCompanionSelect={openCompanion} />

      {reader.analyst_cards.length ? (
        <section className="reader-section reader-section--analysts">
          <h3>分析视角</h3>
          {reader.analyst_cards.map((card, index) => {
            const confidence = pct(card.confidence);
            return (
              <div className="reader-analyst" key={card.lens + index}>
                <div className="reader-analyst-head">
                  <strong>{lensLabel(card.lens)}</strong>
                  <span className="reader-tag reader-tag--muted">{availabilityLabel(card.availability)}</span>
                  {confidence ? <span className="reader-tag">{confidence} 置信</span> : null}
                </div>
                <p>{card.summary}</p>
                <button
                  type="button"
                  className="reader-companion-trigger"
                  aria-label={`查看${lensLabel(card.lens)}视角伴读`}
                  onClick={(event) => openCompanion(
                    { kind: "role", id: card.lens },
                    event.currentTarget,
                  )}
                >
                  查看伴读 <span aria-hidden="true">↗</span>
                </button>
              </div>
            );
          })}
        </section>
      ) : null}

      <footer className="reader-surface-foot">
        {onOpenAudit ? (
          <button
            type="button"
            className="reader-audit-entry"
            onClick={(event) => onOpenAudit({ section: "overview" }, event.currentTarget)}
          >
            {reader.audit_entry.artifact_count} 个产物 · {reader.audit_entry.tool_call_count} 次工具调用 · 数据降级 {reader.audit_entry.degradation_count} 处
            <span>进入审计中心 →</span>
          </button>
        ) : (
          <p>
            {reader.audit_entry.artifact_count} 个产物 · {reader.audit_entry.tool_call_count} 次工具调用 · 数据降级 {reader.audit_entry.degradation_count} 处
          </p>
        )}
        <p>
          {reader.evidence_refs.length} 条证据引用 · {reader.coverage_refs.length} 处覆盖记录
        </p>
      </footer>
    </section>
      {companionMode === "drawer" ? (
        <div className="companion-backdrop" aria-hidden="true" />
      ) : null}
      {companionMode !== "closed" && selection !== null ? (
        <CompanionPanel
          mode={companionMode}
          selection={selection}
          companion={companion.companion}
          loading={companion.loading}
          error={companion.error}
          onClose={closeCompanion}
          onPinToggle={() => setCompanionMode((current) => (
            current === "pinned" ? "temporary" : "pinned"
          ))}
          onRetry={companion.retry}
        />
      ) : null}
    </div>
  );
}

function tiltBadgeClass(reader: LearningReaderV2DTO): string {
  if (reader.research_tilt === null) return "reader-badge--amber";
  if (reader.research_tilt === "favorable") return "reader-badge--green";
  if (reader.research_tilt === "cautious") return "reader-badge--red";
  return "reader-badge--neutral";
}

function eligibilityBadgeClass(reader: LearningReaderV2DTO): string {
  if (reader.decision_eligibility === "none") return "reader-badge--muted";
  if (reader.decision_eligibility === "limited") return "reader-badge--amber";
  return "reader-badge--neutral";
}

function verdictBadgeClass(verdict: LearningReaderV2DTO["evidence_verdict"]): string {
  if (verdict === "PASS") return "reader-badge--green";
  if (verdict === "FAIL_STOP") return "reader-badge--red";
  return "reader-badge--amber";
}

function qualityBadgeClass(reader: LearningReaderV2DTO): string {
  if (reader.data_quality.level === "healthy") return "reader-badge--green";
  if (reader.data_quality.level === "conflicted" || reader.data_quality.level === "blocked") return "reader-badge--red";
  return "reader-badge--amber";
}

function unavailableReason(reasonCode: ReaderUnavailableCode): string {
  return {
    research_case_unavailable: "证据化研究结论尚未生成",
    reader_projection_failed: "研究结论投影失败",
    unsupported_research_case_major: "研究结论版本不受支持",
  }[reasonCode];
}

type ReaderUnavailableCode =
  | "research_case_unavailable"
  | "reader_projection_failed"
  | "unsupported_research_case_major";

function UnavailableSurface({
  reasonCode,
  ticker,
  runId,
}: {
  reasonCode: ReaderUnavailableCode;
  ticker: string | null;
  runId: string;
}): JSX.Element {
  return (
    <section className="reader-surface reader-surface--state">
      <span className="eyebrow">证据化研究结论</span>
      <h2>{ticker ?? runId}</h2>
      <p className="reader-state-text">{unavailableReason(reasonCode)}</p>
      <p className="reader-state-meta">运行标识：{runId}</p>
    </section>
  );
}

function LegacySurface({ reader }: { reader: ReaderResponseDTO & { kind: "legacy" } }): JSX.Element {
  return (
    <section className="reader-surface reader-surface--state">
      <span className="eyebrow">研究结论 · 历史运行</span>
      <h2>{reader.ticker}</h2>
      <p className="reader-state-text">这是学习型改造前的历史运行，以原始结论为准</p>
      {reader.final_signal ? <p className="reader-legacy-signal">原始结论：{reader.final_signal}</p> : null}
    </section>
  );
}

export function ReaderSurface({ runId, onOpenAudit }: ReaderSurfaceProps): JSX.Element {
  const { reader, loading, error } = useReader(runId);

  if (loading) {
    return (
      <section className="reader-surface reader-surface--loading" aria-busy="true">
        <span className="eyebrow">正在读取证据化研究结论</span>
      </section>
    );
  }

  if (error) {
    return (
      <section className="reader-surface reader-surface--error">
        <span className="eyebrow">证据化研究结论</span>
        {error instanceof Error && (error as { status?: number }).status === 404 ? (
          <p className="reader-state-text">该运行暂无 Reader 投影</p>
        ) : (
          <p className="reader-state-text">暂时无法读取 Reader 投影，请稍后重试</p>
        )}
      </section>
    );
  }

  if (!reader) {
    return (
      <section className="reader-surface reader-surface--state">
        <span className="eyebrow">证据化研究结论</span>
        <p className="reader-state-text">暂无可用数据</p>
      </section>
    );
  }

  if (reader.kind === "unavailable") {
    return <UnavailableSurface reasonCode={reader.reason_code} ticker={reader.ticker} runId={reader.run_id} />;
  }

  if (reader.kind === "legacy") {
    return <LegacySurface reader={reader} />;
  }

  return <TypedSurface key={reader.run_id} reader={reader} onOpenAudit={onOpenAudit} />;
}
