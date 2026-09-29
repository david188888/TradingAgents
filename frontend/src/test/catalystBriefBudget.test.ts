import { describe, expect, it } from "vitest";

import fixture from "./fixtures/catalyst-brief-budget.json";

/**
 * The frontend half of the shared first-screen character budget.
 *
 * Design section 4.3 caps ordinary first-screen body text at 420 Unicode
 * characters. The same fixture file is loaded, unchanged, by
 * `tests/agents/test_catalyst_brief_budget.py` on the Python side, and both
 * sides assert the same integers. If the two implementations ever disagreed,
 * the page would enforce a budget the backend never applied and the reader
 * would see a differently-truncated first screen from the one that was
 * published — so this file is deliberately a re-implementation of the count,
 * not an import of a backend helper.
 *
 * What counts is the body text a reader actually sees: the judgement, the
 * primary catalyst line, every key-evidence line, the key question, the next
 * check, and every critical limitation. What does not count is navigation,
 * field labels, the company name, and time metadata — none of which exist in
 * the brief payload at all, so there is nothing to exclude here.
 */
interface BriefLineBody {
  text: string;
  event_ids?: string[];
  finding_ids?: string[];
  challenge_ids?: string[];
}

interface BriefBody {
  kind: "ordinary" | "safety_overflow";
  judgement: string;
  key_evidence: BriefLineBody[];
  key_question: BriefLineBody;
  next_check: BriefLineBody;
  primary_catalyst: BriefLineBody | null;
  critical_limitations: BriefLineBody[];
}

interface FixtureCase {
  name: string;
  note: string;
  expected_characters: number;
  body: BriefBody;
}

const cases = (fixture as { cases: FixtureCase[] }).cases;

/**
 * Mirrors `CatalystBrief.budgeted_texts()` in
 * `tradingagents/agents/schemas/_catalyst_research.py`.
 *
 * An ordinary brief counts everything on the first screen. The safety-overflow
 * template counts only the code template (judgement, question, next check):
 * the critical-limitation list is the payload that the overflow rule exists to
 * keep intact, and design section 4.3 explicitly exempts it. Counting it would
 * push the overflow path back toward the truncation the rule forbids.
 */
function budgetedTexts(brief: BriefBody): string[] {
  if (brief.kind === "safety_overflow") {
    return [brief.judgement, brief.key_question.text, brief.next_check.text];
  }
  return [
    brief.judgement,
    ...(brief.primary_catalyst === null ? [] : [brief.primary_catalyst.text]),
    ...brief.key_evidence.map((line) => line.text),
    brief.key_question.text,
    brief.next_check.text,
    ...brief.critical_limitations.map((line) => line.text),
  ];
}

/**
 * Unicode characters, not UTF-16 code units.
 *
 * `String.prototype.length` counts UTF-16 units, so a character outside the
 * basic multilingual plane would be counted as two here and as one in Python.
 * `Array.from` iterates by code point, which is what "Unicode characters"
 * means in the design and what `len()` means in Python.
 */
function characterCount(brief: BriefBody): number {
  return budgetedTexts(brief).reduce(
    (total, text) => total + Array.from(text).length,
    0,
  );
}

describe("catalyst first-screen character budget", () => {
  it("pins the same budgets the backend pins", () => {
    expect(fixture.budget).toBe(420);
    expect(fixture.safety_overflow_budget).toBe(120);
    expect(fixture.schema_version).toBe("catalyst-research-case-v1");
  });

  it.each(cases)(
    "counts $name to the character total the backend asserts",
    ({ name, body, expected_characters }) => {
      expect(characterCount(body), name).toBe(expected_characters);
    },
  );

  it("agrees with the backend on the boundary case to the character", () => {
    const boundary = cases.find(
      (candidate) => candidate.name === "ordinary_exactly_at_budget",
    );
    expect(boundary).toBeDefined();
    expect(characterCount(boundary!.body)).toBe(fixture.budget);
  });

  it("refuses to truncate the boundary case to make room", () => {
    // The overflow template is the only legal response to an over-budget
    // brief. Cutting the judgement or dropping the last risk to fit is the
    // failure the rule exists to prevent, so the count must not move.
    const boundary = cases.find(
      (candidate) => candidate.name === "ordinary_exactly_at_budget",
    )!;
    const over: BriefBody = {
      ...boundary.body,
      judgement: `${boundary.body.judgement}。`,
    };
    expect(characterCount(over)).toBe(fixture.budget + 1);
  });

  it("keeps the safety-overflow limitation list exempt and intact", () => {
    const overflow = cases.find(
      (candidate) => candidate.name === "safety_overflow",
    )!;
    expect(characterCount(overflow.body)).toBeLessThanOrEqual(
      fixture.safety_overflow_budget,
    );
    expect(overflow.body.critical_limitations).toHaveLength(4);
    expect(overflow.body.critical_limitations.map((line) => line.text)).toEqual(
      [
        "必需事件来源不可用，覆盖完整性无法证明。",
        "复权价格链缺少因子快照，历史时点不可验证。",
        "反证阶段未完成，关键反证仍未解决。",
        "证券身份在一个来源上与其他身份冲突。",
      ],
    );
  });

  it("measures the same set of strings the backend measures", () => {
    // A regression guard on the counting rule itself: an ordinary brief
    // counts the judgement, the primary catalyst, one line per key-evidence
    // entry, the key question, the next check, and every critical limitation
    // -- six strings for this fixture. If either side dropped a row, the totals
    // would stop agreeing on the same payload.
    const ordinary = cases.find(
      (candidate) => candidate.name === "ordinary_with_limitations",
    )!;
    const texts = budgetedTexts(ordinary.body);
    expect(texts).toHaveLength(6);
    expect(texts[texts.length - 1]).toBe("资金面数据本次不可用。");
  });
});
