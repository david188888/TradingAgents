/**
 * T29 — the evidence drawer.
 *
 * Design 4.4: evidence opens on demand (a desktop drawer, a narrow-screen
 * sheet), shows the public source identity plus what it supports and what it
 * limits, and manages focus, Esc, background inert and focus return. Those four
 * accessibility behaviours are *not* implemented here — they come from
 * `useDrawerFocus`, which is the same mechanism `CompanionPanel` and
 * `AuditDetailPanel` already use. What this component adds is the content
 * contract:
 *
 *  * **No internal locator, ever.** The projection carries `public_url`. When
 *    it is null the drawer shows the source identity and says the link is not
 *    available. There is no second code path that could leak an internal
 *    artifact path, because there is no field for one.
 *  * **No cross-run evidence.** `runId` is part of the component's identity
 *    and each evidence row is filtered to it. A caller that passes evidence
 *    belonging to a different run renders the empty state instead of that
 *    evidence.
 */
import { useMemo } from "react";
import type { CatalystEvidenceDTO, CatalystEventDTO, SourceEvidenceV1DTO, ResearchRecordV1DTO } from "../../api/contracts";
import { SourceContent } from "./ResearchRecordSection";
import { useDrawerFocus, useNarrowOverlay, useReturnFocus } from "../shared/drawerFocus";

export interface EvidenceDrawerProps {
  runId: string;
  evidence: CatalystEvidenceDTO[];
  events?: CatalystEventDTO[];
  sourceRecord?: { run_id: string; evidence: SourceEvidenceV1DTO[]; claims?: ResearchRecordV1DTO["claims"]; challenges?: ResearchRecordV1DTO["challenges"] };
  /** The object the reader clicked: an evidence id, event id, or challenge id. */
  openId: string | null;
  /** Short label for the clicked reference, shown as the drawer's title. */
  title?: string | null;
  background: ReadonlyArray<HTMLElement | null>;
  onClose(): void;
}

const TIER_LABELS: Record<CatalystEvidenceDTO["source_tier"], string> = {
  official: "官方",
  vendor: "数据供应商",
  media: "媒体",
  derived: "派生",
};

const AVAILABILITY_LABELS: Record<CatalystEvidenceDTO["availability"], string> = {
  available: "可用",
  unavailable: "不可用",
  unverified: "未验证",
};

function formatInstant(value: string | null): string | null {
  if (value === null) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString().slice(0, 19).replace("T", " ");
}

/**
 * A public link is only rendered when it is a plain http(s) URL.
 *
 * The backend already validates the protocol and rejects sensitive query
 * strings; re-checking here means a bad value degrades to the "no public link"
 * state instead of producing an `href` the reader could follow somewhere
 * unexpected.
 */
function safePublicHref(value: string | null): string | null {
  if (value === null) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

export function EvidenceDrawer({
  runId,
  evidence,
  events = [],
  sourceRecord,
  openId,
  title,
  background,
  onClose,
}: EvidenceDrawerProps): JSX.Element | null {
  const narrow = useNarrowOverlay();
  const focus = useDrawerFocus({ open: openId !== null, trap: true, background, onClose });
  const returnFocus = useReturnFocus();

  const record = useMemo(() => {
    if (openId === null) return null;
    // Filter by run first. Evidence from a different run must never appear
    // in this drawer, even if the caller handed it over by mistake.
    const own = evidence.filter((item) => item.run_id === runId);
    const event = events.find((item) => item.run_id === runId && item.event_id === openId) ?? null;
    const saved = sourceRecord?.run_id === runId ? sourceRecord : undefined;
    const claim = saved?.claims?.find((item) => item.claim_id === openId);
    const challenge = saved?.challenges?.find((item) => item.challenge_id === openId);
    const refs = new Set([openId, ...(claim?.evidence_ids ?? []), ...(challenge?.evidence_ids ?? []), ...(event?.date_evidence_ids ?? [])]);
    const matches = own.filter((item) => refs.has(item.evidence_id));
    return { own, matches, event, challenge };
  }, [evidence, events, openId, runId, sourceRecord]);

  if (openId === null) return null;

  const { own, matches, event, challenge } = record ?? { own: [], matches: [], event: null, challenge: undefined };
  const heading = title ?? matches[0]?.source_name ?? event?.title ?? "证据详情";

  return (
    <div className={`catalyst-drawer-layer${narrow ? " is-narrow" : ""}`}>
      <button
        type="button"
        className="catalyst-drawer-backdrop"
        aria-label="关闭证据面板背景"
        onClick={() => {
          returnFocus.release();
          onClose();
        }}
      />
      <aside
        ref={focus.panelRef}
        className="catalyst-drawer"
        role="dialog"
        aria-modal={narrow ? true : undefined}
        aria-label="证据详情"
        onKeyDown={focus.onKeyDown}
      >
        <header className="catalyst-drawer-head">
          <div>
            <span className="eyebrow">Evidence · {runId}</span>
            <h3>{heading}</h3>
          </div>
          <button
            type="button"
            data-autofocus="true"
            className="catalyst-drawer-close"
            aria-label="关闭证据详情"
            onClick={() => {
              returnFocus.release();
              onClose();
            }}
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>

        <div className="catalyst-drawer-body" aria-live="polite">
          {challenge ? <section><h4>待核查的挑战</h4><p>{challenge.statement}</p><p>拟核查：{challenge.proposed_test}</p></section> : null}
          {matches.length > 0 ? matches.map((match) => {
            const href = safePublicHref(match.public_url);
            const source = sourceRecord?.run_id === runId ? sourceRecord.evidence.find((item) => item.evidence_id === match.evidence_id) : undefined;
            return <section key={match.evidence_id}>
              {source ? <SourceContent evidence={source} /> : <section>
                <span className="catalyst-drawer-kicker">来源内容未保存</span>
                <p>该记录只有来源信息，无法展示原文或摘要。</p>
              </section>}
              <section>
                <span className="catalyst-drawer-kicker">来源身份</span>
                <dl className="catalyst-drawer-facts">
                  <div>
                    <dt>来源</dt>
                    <dd>{match.source_name}</dd>
                  </div>
                  <div>
                    <dt>层级</dt>
                    <dd>{TIER_LABELS[match.source_tier] ?? match.source_tier}</dd>
                  </div>
                  <div>
                    <dt>能力</dt>
                    <dd>{match.capability || "未记录"}</dd>
                  </div>
                  <div>
                    <dt>状态</dt>
                    <dd>{AVAILABILITY_LABELS[match.availability] ?? match.availability}</dd>
                  </div>
                  <div>
                    <dt>发布时间</dt>
                    <dd>{formatInstant(match.published_at) ?? "未记录"}</dd>
                  </div>
                  <div>
                    <dt>可用截止</dt>
                    <dd>{formatInstant(match.usable_as_of) ?? "未记录"}</dd>
                  </div>
                </dl>
              </section>

              <section>
                <span className="catalyst-drawer-kicker">公开来源</span>
                {href === null ? (
                  <p className="catalyst-drawer-nolink">
                    该证据没有可公开的来源链接。系统只显示来源标识与限制，不暴露内部定位符。
                  </p>
                ) : (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    打开公开来源
                  </a>
                )}
              </section>

              <section>
                <span className="catalyst-drawer-kicker">时间与数值口径</span>
                <p>
                  {match.time_basis || "未记录时间口径"}
                  {match.value_basis ? ` · ${match.value_basis}` : ""}
                </p>
              </section>

              {match.republished_from_evidence_id !== null ? (
                <section>
                  <span className="catalyst-drawer-kicker">转载关系</span>
                  <p>
                    本条转载自同一来源家族内的另一条证据（{match.source_family_id}）。
                    多个站点转载同一条公告不增加独立支持数。
                  </p>
                </section>
              ) : null}

              <section>
                <span className="catalyst-drawer-kicker">适用范围</span>
                <p>
                  本次运行引用了该来源。是否支持具体主张，需要核对来源内容、时间与数值口径。
                </p>
              </section>
            </section>;
          }) : challenge ? <p>该挑战没有直接引用已保存的反证来源；拟核查事项尚不等于验证结果。</p> : event !== null ? (
            <>
              <section>
                <span className="catalyst-drawer-kicker">事件</span>
                <p>{event.title}</p>
              </section>
              <section>
                <span className="catalyst-drawer-kicker">状态与时间</span>
                <p>
                  {event.status} · {event.date_precision === "unknown" ? "时间待确认" : formatInstant(event.occurred_on) ?? "未记录"}
                </p>
              </section>
            </>
          ) : (
            <div className="catalyst-drawer-empty">
              <strong>该引用在本次运行内无法解析</strong>
              <p>
                {own.length === 0
                  ? "本次运行没有可展示的证据记录。"
                  : "点击的引用没有对应到本次运行已提交的证据，因此不展示任何内容。"}
              </p>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
