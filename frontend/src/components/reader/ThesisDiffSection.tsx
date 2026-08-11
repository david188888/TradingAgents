import type {
  ReaderEvidenceRefDTO,
  ThesisChangeFlagDTO,
  ThesisDiffDTO,
  ThesisDiffEntryDTO,
  ThesisDiffKindDTO,
} from "../../api/contracts";

interface ThesisDiffSectionProps {
  diff: ThesisDiffDTO | null;
  evidenceRefs: ReaderEvidenceRefDTO[];
}

const stateCopy: Record<ThesisDiffKindDTO, { label: string; note: string }> = {
  new: { label: "新增", note: "本轮首次形成" },
  maintained: { label: "延续", note: "核心判断仍成立" },
  invalidated: { label: "已被反证", note: "出现可追溯的反向证据" },
  unresolved: { label: "仍待确认", note: "本轮明确保留未知状态" },
  not_reassessed: { label: "本轮未复核", note: "上轮存在，但本轮没有重新评估" },
};

const flagLabels: Record<ThesisChangeFlagDTO, string> = {
  text_changed: "表述变化",
  evidence_changed: "证据变化",
  confidence_changed: "置信度变化",
  status_changed: "状态变化",
};

function StateIcon({ kind }: { kind: ThesisDiffKindDTO }): JSX.Element {
  const common = {
    className: "thesis-state-icon",
    viewBox: "0 0 20 20",
    "aria-hidden": true,
  } as const;
  if (kind === "new") {
    return <svg {...common}><path d="M10 3v14M3 10h14" /></svg>;
  }
  if (kind === "maintained") {
    return <svg {...common}><path d="m4 10 3.5 3.5L16 5" /></svg>;
  }
  if (kind === "invalidated") {
    return <svg {...common}><path d="M5 5l10 10M15 5 5 15" /></svg>;
  }
  if (kind === "unresolved") {
    return <svg {...common}><path d="M7.5 7a2.6 2.6 0 1 1 3.8 2.3c-.9.5-1.3 1-1.3 2M10 15.5h.01" /></svg>;
  }
  return <svg {...common}><circle cx="10" cy="10" r="6.5" /><path d="M10 6.5v4l2.6 1.6" /></svg>;
}

function percent(value: number | null): string {
  return value === null ? "未评估" : `${Math.round(value * 100)}%`;
}

function lifecycleLabel(value: ThesisDiffEntryDTO["current_lifecycle_status"]): string {
  if (value === null) return "未复核";
  return { active: "有效", resolved: "已解决", invalidated: "已失效" }[value];
}

function baselineLabel(diff: ThesisDiffDTO): string {
  if (!diff.previous_run_id || !diff.baseline_completed_at) return "首次建立研究基线";
  const timestamp = new Date(diff.baseline_completed_at);
  if (Number.isNaN(timestamp.getTime())) return "与上一轮研究基线比较";
  const date = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(timestamp);
  return `与 ${date} 的研究基线比较`;
}

function changeDetail(entry: ThesisDiffEntryDTO, flag: ThesisChangeFlagDTO): string | null {
  if (flag === "confidence_changed") {
    return `${percent(entry.previous_confidence)} → ${percent(entry.current_confidence)}`;
  }
  if (flag === "status_changed") {
    return `${lifecycleLabel(entry.previous_lifecycle_status)} → ${lifecycleLabel(entry.current_lifecycle_status)}`;
  }
  return null;
}

function EntryText({ entry }: { entry: ThesisDiffEntryDTO }): JSX.Element {
  const comparesText =
    entry.change_flags.includes("text_changed") &&
    entry.previous_text !== null &&
    entry.current_text !== null;
  if (comparesText) {
    return (
      <div className="thesis-entry-comparison">
        <div><span>上次</span><p>{entry.previous_text}</p></div>
        <div><span>本轮</span><p>{entry.current_text}</p></div>
      </div>
    );
  }
  return (
    <p className="thesis-entry-text">
      {entry.current_text ?? entry.previous_text ?? "本轮没有可展示的论点文本。"}
    </p>
  );
}

function ThesisEntry({
  entry,
  evidenceLabels,
}: {
  entry: ThesisDiffEntryDTO;
  evidenceLabels: Map<string, string>;
}): JSX.Element {
  const counterSources = Array.from(
    new Set(
      entry.counter_evidence_ref_ids
        .map((refId) => evidenceLabels.get(refId))
        .filter((label): label is string => Boolean(label)),
    ),
  );
  const copy = stateCopy[entry.diff_kind];
  return (
    <li className={`thesis-entry thesis-entry--${entry.diff_kind}`}>
      <div className="thesis-entry-head">
        <span className="thesis-state-mark"><StateIcon kind={entry.diff_kind} /></span>
        <div>
          <strong>{copy.label}</strong>
          <span>{copy.note}</span>
        </div>
      </div>
      <EntryText entry={entry} />
      {entry.change_flags.length ? (
        <div className="thesis-change-flags" aria-label="变化维度">
          {entry.change_flags.map((flag) => {
            const detail = changeDetail(entry, flag);
            return (
              <span key={flag} className="thesis-change-flag">
                <b>{flagLabels[flag]}</b>
                {detail ? <small>{detail}</small> : null}
              </span>
            );
          })}
        </div>
      ) : null}
      {entry.counter_evidence_ref_ids.length ? (
        <p className="thesis-counter-evidence">
          {counterSources.length
            ? `反证来源：${counterSources.join("、")}`
            : "反证来源当前不可公开展示"}
        </p>
      ) : null}
    </li>
  );
}

export function ThesisDiffSection({
  diff,
  evidenceRefs,
}: ThesisDiffSectionProps): JSX.Element {
  const evidenceLabels = new Map(
    evidenceRefs
      .filter((ref) => ref.resolution_status === "available")
      .map((ref) => [ref.ref_id, ref.source_label]),
  );
  const counts = diff
    ? Object.fromEntries(
        (Object.keys(stateCopy) as ThesisDiffKindDTO[]).map((kind) => [
          kind,
          diff.entries.filter((entry) => entry.diff_kind === kind).length,
        ]),
      ) as Record<ThesisDiffKindDTO, number>
    : null;

  return (
    <section className="thesis-diff" aria-label="论点变化">
      <header className="thesis-diff-head">
        <div>
          <span className="eyebrow">学习报告 · Thesis ledger</span>
          <h3>论点变化</h3>
        </div>
        <span className={`thesis-baseline ${diff?.previous_run_id ? "" : "thesis-baseline--first"}`}>
          {diff ? baselineLabel(diff) : "对比暂不可用"}
        </span>
      </header>

      {diff === null ? (
        <div className="thesis-diff-empty">
          <strong>本轮未生成可比较的论点变化</strong>
          <p>当前研究正文仍可独立阅读；完成可用基线后，这里会区分新增、延续、反证与未复核内容。</p>
        </div>
      ) : (
        <>
          <div className="thesis-diff-summary" aria-label="变化概览">
            {(Object.keys(stateCopy) as ThesisDiffKindDTO[]).map((kind) => (
              <div key={kind} className={`thesis-summary-item thesis-summary-item--${kind}`}>
                <StateIcon kind={kind} />
                <span>{stateCopy[kind].label}</span>
                <strong>{counts?.[kind] ?? 0}</strong>
              </div>
            ))}
          </div>
          {diff.entries.length ? (
            <ol className="thesis-entry-list">
              {diff.entries.map((entry) => (
                <ThesisEntry
                  key={entry.claim_key}
                  entry={entry}
                  evidenceLabels={evidenceLabels}
                />
              ))}
            </ol>
          ) : (
            <div className="thesis-diff-empty thesis-diff-empty--compact">
              <strong>基线已建立，本轮暂无可比较论点</strong>
            </div>
          )}
        </>
      )}
    </section>
  );
}
