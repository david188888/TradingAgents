/**
 * T27 — the catalyst form.
 *
 * The default form for `catalyst_v1` shows four fields: company, research
 * window, an optional question, and the start button. The classic form's role
 * checkboxes, research-depth selector, horizon, holding inputs and checkpoint
 * toggle are not shown, because none of them is an input to this flow.
 *
 * "Hidden fields must not pollute the new profile's request" is the rule this
 * component exists to make true, and it is enforced structurally rather than by
 * discipline: it never reads the classic selection state, and it submits
 * `buildCatalystRequest()`, which constructs its body from scratch. There is no
 * path by which a value from the classic form can reach a catalyst request.
 *
 * The classic form keeps its role selection — it is the right form for the
 * classic profile, and this component does not replace it.
 */
import type { ResearchProfile } from "../../api/contracts";
import type { EffectiveCatalystConfig } from "../../hooks/useConfig";

export interface CatalystFormProps {
  profile: ResearchProfile;
  onProfileChange: (profile: ResearchProfile) => void;
  ticker: string;
  onTickerChange: (value: string) => void;
  windowStart: string;
  windowEnd: string;
  onWindowChange: (start: string, end: string) => void;
  researchQuestion: string;
  onResearchQuestionChange: (value: string) => void;
  effective: EffectiveCatalystConfig;
  onStart: () => void;
  starting: boolean;
  disabled: boolean;
  error: string | null;
}

export function CatalystForm({
  profile,
  onProfileChange,
  ticker,
  onTickerChange,
  windowEnd,
  onWindowChange,
  researchQuestion,
  onResearchQuestionChange,
  effective,
  onStart,
  starting,
  disabled,
  error,
}: CatalystFormProps): JSX.Element {
  const unsupported = effective.supported === false;
  const startDisabled = disabled || starting || unsupported || ticker.trim() === "";

  return (
    <div className="catalyst-form">
      <div className="eyebrow">New research</div>
      <div className="section-title">
        <h2>发起研究</h2>
      </div>

      <div className="input-group">
        <label htmlFor="catalyst-profile">研究流程</label>
        <select
          id="catalyst-profile"
          value={profile}
          onChange={(event) =>
            onProfileChange(event.target.value === "catalyst_v1" ? "catalyst_v1" : "classic")
          }
        >
          <option value="catalyst_v1">新版催化研究（四个阶段）</option>
          <option value="classic">旧版研究流程</option>
        </select>
        {/*
          The effective-config summary, shown on the catalyst profile. This is
          what the *next run* will do, not a restatement of the four fields
          above: a reader who switches profile needs to know which stages and
          models they just committed to before pressing start.
        */}
        {profile === "catalyst_v1" ? (
          <dl className="catalyst-effective" data-testid="catalyst-effective-config">
            <div>
              <dt>阶段</dt>
              <dd>{effective.stages.join(" → ")}</dd>
            </div>
            <div>
              <dt>流程</dt>
              <dd>三个专项 → 单次反证 → 单次综合</dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd>
                {effective.quickThinkLlm || "未选择"} / {effective.deepThinkLlm || "未选择"}
              </dd>
            </div>
            <div>
              <dt>输出语言</dt>
              <dd>{effective.outputLanguage}</dd>
            </div>
            <div>
              <dt>部署支持</dt>
              <dd>
                {effective.supported === null
                  ? "未确认"
                  : effective.supported
                    ? "已支持"
                    : `不支持：${effective.reason ?? "服务端拒绝该 profile"}`}
              </dd>
            </div>
          </dl>
        ) : null}
      </div>

      {profile === "catalyst_v1" ? (
        <>
          <div className="input-group">
            <label htmlFor="catalyst-ticker">公司</label>
            <input
              id="catalyst-ticker"
              type="text"
              value={ticker}
              onChange={(event) => onTickerChange(event.target.value)}
              placeholder="如 600519（A 股普通股票）"
            />
          </div>

          <div className="input-group">
            <label htmlFor="catalyst-window-end">研究截止日</label>
            <div className="catalyst-window-range">
              <input
                id="catalyst-window-end"
                type="date"
                value={windowEnd}
                onChange={(event) => onWindowChange("", event.target.value)}
              />
            </div>
            <small>展望：自截止日起未来最多 12 周（84 天）。只使用截止时已公开的证据。</small>
          </div>

          <div className="input-group">
            <label htmlFor="catalyst-question">研究问题（可选）</label>
            <textarea
              id="catalyst-question"
              rows={2}
              value={researchQuestion}
              onChange={(event) => onResearchQuestionChange(event.target.value)}
              placeholder="留空则由流程自行选择最值得验证的问题。"
            />
            <small>问题会随本次运行记录。{Array.from(researchQuestion.trim()).length}/400 字符。</small>
          </div>
        </>
      ) : null}

      {error !== null ? (
        <div className="error-text" style={{ color: "var(--red)" }}>
          {error}
        </div>
      ) : null}

      <div className="actions">
        <button type="button" className="primary" onClick={onStart} disabled={startDisabled}>
          {starting ? "启动中…" : "开始研究"}
        </button>
      </div>
    </div>
  );
}
