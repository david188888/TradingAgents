/**
 * T28 — the first screen, rendered.
 *
 * The pure reading layer's rules are asserted in `catalystWorkbench.test.ts`.
 * This file asserts the *rendering* of those rules, because the rule the design
 * is strictest about — the safety overflow — is a UI rule as much as a data
 * one: a correct array can still be rendered behind a collapse, behind a
 * count, or truncated to the first two entries, and the reader would learn
 * exactly the wrong thing.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import budgetFixture from "../../test/fixtures/catalyst-brief-budget.json";
import catalystMinimalComplete from "../../../../shared_fixtures/catalyst/catalyst_minimal_complete.json";
import type {
  CatalystBriefDTO,
  CatalystReadState,
  CatalystResearchPriority,
} from "../../api/contracts";
import {
  buildCatalystFirstScreen,
  catalystScreenState,
  parseCatalystCase,
} from "../../domain/catalystWorkbench";
import { CatalystBrief } from "./CatalystBrief";

interface BriefLineBody {
  text: string;
  event_ids?: string[];
  finding_ids?: string[];
  challenge_ids?: string[];
}

function toBrief(body: {
  kind: "ordinary" | "safety_overflow";
  judgement: string;
  priority: CatalystResearchPriority;
  primary_catalyst_event_id: string | null;
  primary_catalyst: BriefLineBody | null;
  key_evidence: BriefLineBody[];
  key_question: BriefLineBody;
  next_check: BriefLineBody;
  critical_limitations: BriefLineBody[];
  overflow_reason?: string;
}): CatalystBriefDTO {
  const line = (item: BriefLineBody) => ({
    text: item.text,
    event_ids: item.event_ids ?? [],
    finding_ids: item.finding_ids ?? [],
    challenge_ids: item.challenge_ids ?? [],
  });
  return {
    kind: body.kind,
    judgement: body.judgement,
    priority: body.priority,
    primary_catalyst_event_id: body.primary_catalyst_event_id,
    primary_catalyst: body.primary_catalyst === null ? null : line(body.primary_catalyst),
    key_evidence: body.key_evidence.map(line),
    key_question: line(body.key_question),
    next_check: line(body.next_check),
    critical_limitations: body.critical_limitations.map(line),
    overflow_reason: body.overflow_reason ?? null,
  };
}

const budgetCases = (
  budgetFixture as {
    cases: Array<{ name: string; body: Parameters<typeof toBrief>[0] }>;
  }
).cases;

const readyFixture = catalystMinimalComplete as unknown as CatalystReadState;
const RUN_ID = "run_catalyst_minimal";

function screenOf(brief: CatalystBriefDTO) {
  const overflowing = brief.kind === "safety_overflow";
  const state = {
    ...(readyFixture as object),
    priority: brief.priority,
    completeness: overflowing ? "partial" : "complete",
    quality: overflowing ? "LOW_CONFIDENCE" : "PASS",
  } as unknown as CatalystReadState;
  return {
    screen: buildCatalystFirstScreen(brief, parseCatalystCase(catalystMinimalComplete.case)),
    state: catalystScreenState({
      run_status: "completed",
      state,
      completeness: overflowing ? "partial" : "complete",
      quality: overflowing ? "LOW_CONFIDENCE" : "PASS",
      profile: "catalyst_v1",
      error: null,
    }),
  };
}

function renderBrief(brief: CatalystBriefDTO, onOpenEvidence = vi.fn()) {
  const { screen: built, state } = screenOf(brief);
  return {
    ...render(
      <CatalystBrief
        runId={RUN_ID}
        screen={built}
        state={state}
        asOf={null}
        onOpenEvidence={onOpenEvidence}
      />,
    ),
    onOpenEvidence,
    built,
    state,
  };
}

describe("CatalystBrief renders the seven first-screen rows", () => {
  it("renders all seven rows of design 4.3 in order", () => {
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    const labels = Array.from(container.querySelectorAll(".catalyst-row-label")).map(
      (node) => node.textContent,
    );
    expect(labels).toEqual([
      "研究判断",
      "研究优先级",
      "关键催化",
      "依据",
      "最大疑点",
      "下一验证",
      "关键限制",
    ]);
  });

  it("shows the research priority as one of four categories, never a percentage", () => {
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    const row = container.querySelector(".catalyst-row-priority")!;
    expect(within(row as HTMLElement).getByText("优先核查")).toBeInTheDocument();
    // No score of any kind appears next to the category.
    expect(row.textContent).not.toMatch(/\d+\s*%|\d+\s*分|评分|置信度\s*[:：]\s*\d/);
  });

  it("keeps at most one primary catalyst and at most three key-evidence lines", () => {
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    expect(container.querySelectorAll(".catalyst-row-catalyst .catalyst-row-line").length).toBeLessThanOrEqual(1);
    expect(container.querySelectorAll(".catalyst-row-evidence .catalyst-row-line").length).toBeLessThanOrEqual(3);
  });

  it("always states a doubt rather than reporting that none was found", () => {
    const brief = toBrief(budgetCases.find((c) => c.name === "ordinary_minimum")!.body);
    const { container } = renderBrief(brief);
    const row = container.querySelector(".catalyst-row-doubt")!;
    expect(row.querySelectorAll(".catalyst-row-line").length).toBeGreaterThanOrEqual(1);
    expect(row.textContent).not.toMatch(/未发现反证|无反证/);
  });

  it("shows a placeholder instead of an empty section when there is no catalyst", () => {
    const base = budgetCases.find((c) => c.name === "ordinary_minimum")!.body;
    const brief = toBrief({ ...base, primary_catalyst: null, primary_catalyst_event_id: null });
    const { container } = renderBrief(brief);
    expect(container.querySelectorAll(".catalyst-row-catalyst .catalyst-row-line")).toHaveLength(0);
    expect(container.querySelector(".catalyst-row-catalyst .catalyst-row-placeholder")!.textContent).toContain(
      "未发现明确的近期主催化",
    );
  });
});

/**
 * The safety overflow. Design 4.3 states the rule and then says it outranks the
 * length target: when the server could not fit every major counter-evidence
 * into 420 characters it emits a ≤120-character template and a full limitation
 * list that is exempt from the budget. The list must be complete, expanded, and
 * reachable. Each assertion below is one way the list could be lost in the UI.
 */
describe("safety overflow renders the full limitation list", () => {
  const overflow = budgetCases.find((c) => c.name === "safety_overflow")!;
  const LIMITATION_COUNT = overflow.body.critical_limitations.length;

  it("uses the shared multi-risk fixture rather than a single limitation", () => {
    // A one-item list passes every assertion below trivially. The design's
    // failure mode is specifically *several* major risks competing for 420
    // characters, so the fixture under test has to have several.
    expect(LIMITATION_COUNT).toBeGreaterThanOrEqual(4);
  });

  it("renders every limitation, including the last one, in full", () => {
    const brief = toBrief(overflow.body);
    const { container } = renderBrief(brief);
    const list = container.querySelector(".catalyst-row-limitations .catalyst-limitations-scroll")!;
    const items = Array.from(list.querySelectorAll(".catalyst-row-line"));
    expect(items).toHaveLength(LIMITATION_COUNT);
    // The last risk is the one a truncated list drops. It is present and its
    // text is the whole string, not a prefix.
    const last = overflow.body.critical_limitations[LIMITATION_COUNT - 1].text;
    expect(items[items.length - 1].textContent).toContain(last);
    for (const limitation of overflow.body.critical_limitations) {
      expect(container.textContent).toContain(limitation.text);
    }
  });

  it("is expanded by default — not a <details>, not a hidden panel", () => {
    const brief = toBrief(overflow.body);
    const { container } = renderBrief(brief);
    // No collapse element of any kind, and no `hidden` / `aria-hidden` on the
    // list or on the row.
    expect(container.querySelector("details")).toBeNull();
    expect(container.querySelector("[aria-expanded]")).toBeNull();
    const row = container.querySelector(".catalyst-row-limitations")!;
    expect(row.hasAttribute("hidden")).toBe(false);
    expect(row.getAttribute("aria-hidden")).toBeNull();
    const list = row.querySelector("ul")!;
    expect(list.hasAttribute("hidden")).toBe(false);
    expect(list.getAttribute("aria-hidden")).toBeNull();
  });

  it("is scrollable and reachable, and never replaced by a count", () => {
    const brief = toBrief(overflow.body);
    const { container } = renderBrief(brief);
    // Focusable and labelled as its own region: a long list inside a fixed
    // box has to be reachable by keyboard, not only by pointer.
    const list = screen.getByRole("region", { name: "影响判断的限制（完整列表）" });
    expect(list).toHaveAttribute("tabindex", "0");
    expect(list.className).toContain("catalyst-limitations-scroll");
    // The list itself, and not a summary, is what the reader is shown.
    expect(container.textContent).not.toMatch(/共\s*\d+\s*条限制|仅显示前|查看全部限制|还有\s*\d+\s*条/);
    // All four risks are in the DOM simultaneously.
    expect(within(list as HTMLElement).getAllByRole("listitem")).toHaveLength(LIMITATION_COUNT);
  });

  it("states the overflow reason and says the list is outside the budget", () => {
    const brief = toBrief(overflow.body);
    const { container } = renderBrief(brief);
    const note = container.querySelector(".catalyst-overflow-note")!;
    expect(note.textContent).toContain("brief_safety_overflow");
    expect(note.textContent).toContain("不受该预算限制");
    // The footer reports the ≤120 template budget, not the 420 one: the page
    // must not hold a 120-character answer to the 420 rule.
    const foot = container.querySelector(".catalyst-brief-foot")!;
    expect(foot.textContent).toContain("/ 120 字");
  });

  it("exempts the limitation list from the character budget", () => {
    const brief = toBrief(overflow.body);
    const { built, container } = renderBrief(brief);
    // The reported count covers only the template, so it stays under 120 even
    // though the rendered limitations total far more.
    expect(built.budget).toBe(120);
    expect(built.character_count).toBeLessThanOrEqual(120);
    const limitationCharacters = overflow.body.critical_limitations.reduce(
      (total, item) => total + Array.from(item.text).length,
      0,
    );
    expect(limitationCharacters).toBeGreaterThan(built.character_count);
    // The list is rendered regardless of that count.
    expect(container.querySelectorAll(".catalyst-row-limitations .catalyst-row-line")).toHaveLength(
      LIMITATION_COUNT,
    );
  });

  it("still renders a judgement, a question and a next check on the overflow path", () => {
    const brief = toBrief(overflow.body);
    const { container } = renderBrief(brief);
    expect(container.querySelector(".catalyst-row-judgement")!.textContent).toContain(
      overflow.body.judgement,
    );
    expect(container.querySelector(".catalyst-row-next")!.textContent).toContain(
      overflow.body.next_check.text,
    );
    // "Not enough information" is stated plainly, per design 4.3 row 1.
    expect(container.textContent).toContain("信息不足");
  });
});
