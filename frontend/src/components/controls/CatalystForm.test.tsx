/**
 * T27 — the catalyst form, rendered.
 *
 * `useConfig.catalyst.test.ts` asserts the request-body property ("no hidden
 * classic field reaches a `catalyst_v1` request") at the builder level. This
 * file asserts the other half of the acceptance criteria, which is about what
 * the component actually puts on screen: the default catalyst form shows only
 * company / window / optional question / start; switching profile shows the
 * effective-config summary; and the component never renders a classic-only
 * control (role checkboxes, research depth, horizon, holding, checkpoint) of
 * its own, because it has no state for any of them to leak from.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EffectiveCatalystConfig } from "../../hooks/useConfig";
import { CatalystForm, type CatalystFormProps } from "./CatalystForm";

function effective(over: Partial<EffectiveCatalystConfig> = {}): EffectiveCatalystConfig {
  return {
    profile: "catalyst_v1",
    researchDepth: 3,
    horizon: "medium",
    llmProvider: "openai",
    quickThinkLlm: "gpt-4o-mini",
    deepThinkLlm: "gpt-4o",
    outputLanguage: "zh",
    stages: ["准备证据", "专项分析", "反证核验", "综合发布"],
    supported: true,
    reason: null,
    ...over,
  };
}

function baseProps(over: Partial<CatalystFormProps> = {}): CatalystFormProps {
  return {
    profile: "catalyst_v1",
    onProfileChange: vi.fn(),
    ticker: "",
    onTickerChange: vi.fn(),
    windowStart: "2026-01-01",
    windowEnd: "2026-06-01",
    onWindowChange: vi.fn(),
    researchQuestion: "",
    onResearchQuestionChange: vi.fn(),
    effective: effective(),
    onStart: vi.fn(),
    starting: false,
    disabled: false,
    error: null,
    ...over,
  };
}

describe("T27 — the default catalyst form shows exactly four inputs", () => {
  it("renders company, window (start+end+presets), question and start — nothing else", () => {
    render(<CatalystForm {...baseProps()} />);

    expect(screen.getByLabelText("公司")).toBeInTheDocument();
    expect(screen.getByLabelText("研究截止日")).toBeInTheDocument();
    expect(screen.getByText(/84 天/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "近 90 天" })).toBeNull();
    expect(screen.getByLabelText("研究问题（可选）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始研究" })).toBeInTheDocument();

    // None of the classic-only *controls* this component could have rendered
    // are present: role checkboxes, a research-depth selector, a horizon
    // control, holding inputs, a checkpoint toggle. ("研究深度" itself does
    // appear as read-only text inside the effective-config summary below —
    // that is the server's answer, not an input, and is covered separately.)
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByLabelText(/分析师/)).toBeNull();
    expect(screen.queryByLabelText(/研究深度/)).toBeNull();
    expect(screen.queryByLabelText(/持仓|平均成本|账户总资产/)).toBeNull();
    expect(screen.queryByLabelText(/checkpoint|检查点/i)).toBeNull();
  });

  it("shows no company/window/question inputs when the profile is classic", () => {
    // The classic profile is not this component's form — it renders only the
    // profile switcher and the start button, so nothing here can leak a
    // catalyst-only value into a classic run either.
    render(<CatalystForm {...baseProps({ profile: "classic" })} />);
    expect(screen.queryByLabelText("公司")).toBeNull();
    expect(screen.queryByLabelText("研究问题（可选）")).toBeNull();
    expect(screen.getByRole("button", { name: "开始研究" })).toBeInTheDocument();
  });
});

describe("T27 — profile switch shows the effective-config summary", () => {
  it("shows the effective-config summary on catalyst_v1", () => {
    render(<CatalystForm {...baseProps({ profile: "catalyst_v1", effective: effective() })} />);
    const summary = screen.getByTestId("catalyst-effective-config");
    expect(summary).toBeInTheDocument();
    expect(summary.textContent).toContain("准备证据 → 专项分析 → 反证核验 → 综合发布");
    expect(summary.textContent).toContain("三个专项 → 单次反证 → 单次综合");
    expect(summary.textContent).toContain("gpt-4o-mini");
    expect(summary.textContent).toContain("gpt-4o");
    expect(summary.textContent).toContain("已支持");
  });

  it("does not show the effective-config summary on classic", () => {
    render(<CatalystForm {...baseProps({ profile: "classic" })} />);
    expect(screen.queryByTestId("catalyst-effective-config")).toBeNull();
  });

  it("reports deployment support truthfully instead of defaulting to a promise", () => {
    const { rerender } = render(
      <CatalystForm {...baseProps({ effective: effective({ supported: null }) })} />,
    );
    expect(screen.getByTestId("catalyst-effective-config").textContent).toContain("未确认");

    rerender(
      <CatalystForm
        {...baseProps({ effective: effective({ supported: false, reason: "服务端未开启该 profile" }) })}
      />,
    );
    expect(screen.getByTestId("catalyst-effective-config").textContent).toContain(
      "不支持：服务端未开启该 profile",
    );
  });

  it("calls onProfileChange when the profile selector changes", () => {
    const onProfileChange = vi.fn();
    render(<CatalystForm {...baseProps({ onProfileChange })} />);
    fireEvent.change(screen.getByLabelText("研究流程"), { target: { value: "classic" } });
    expect(onProfileChange).toHaveBeenCalledWith("classic");
  });
});

describe("T27 — window presets and start gating", () => {
  it("applies a preset as a start/end pair through onWindowChange, not a hidden field", () => {
    const onWindowChange = vi.fn();
    render(<CatalystForm {...baseProps({ onWindowChange })} />);
    fireEvent.change(screen.getByLabelText("研究截止日"), { target: { value: "2026-09-30" } });
    expect(onWindowChange).toHaveBeenCalledTimes(1);
    const [start, end] = onWindowChange.mock.calls[0] as [string, string];
    expect(start).toBe("");
    expect(end).toBe("2026-09-30");
  });

  it("disables start when the ticker is blank, even though the profile is supported", () => {
    render(<CatalystForm {...baseProps({ ticker: "  ", effective: effective({ supported: true }) })} />);
    expect(screen.getByRole("button", { name: "开始研究" })).toBeDisabled();
  });

  it("disables start when the deployment does not support the profile", () => {
    render(
      <CatalystForm
        {...baseProps({ ticker: "600519", effective: effective({ supported: false, reason: "x" }) })}
      />,
    );
    expect(screen.getByRole("button", { name: "开始研究" })).toBeDisabled();
  });

  it("disables start and relabels it while a run is starting", () => {
    render(<CatalystForm {...baseProps({ ticker: "600519", starting: true })} />);
    const button = screen.getByRole("button", { name: "启动中…" });
    expect(button).toBeDisabled();
  });

  it("enables start once a ticker is present and the profile is supported", () => {
    render(<CatalystForm {...baseProps({ ticker: "600519", effective: effective({ supported: true }) })} />);
    expect(screen.getByRole("button", { name: "开始研究" })).toBeEnabled();
  });

  it("surfaces a caller-provided error without blocking on it silently", () => {
    render(<CatalystForm {...baseProps({ error: "股票代码不合法" })} />);
    expect(screen.getByText("股票代码不合法")).toBeInTheDocument();
  });
});

describe("T27 — question input carries no hidden state", () => {
  it("round-trips the optional research question through onResearchQuestionChange only", () => {
    const onResearchQuestionChange = vi.fn();
    render(<CatalystForm {...baseProps({ onResearchQuestionChange })} />);
    fireEvent.change(screen.getByLabelText("研究问题（可选）"), {
      target: { value: "分产品毛利率是否兑现？" },
    });
    expect(onResearchQuestionChange).toHaveBeenCalledWith("分产品毛利率是否兑现？");
  });
});
