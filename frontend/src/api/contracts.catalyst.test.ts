/**
 * T10/T11 — the catalyst wire contract, exercised against the *same* JSON files
 * the Python suite reads.
 *
 * Source of truth: `shared_fixtures/catalyst/*.json`, imported unchanged by
 * `tests/test_catalyst_fixtures.py`. Both suites enumerate the same names, so a
 * fixture or a field that exists on one side only fails on the other.
 *
 * The DTOs in ./contracts mirror
 *   tradingagents/agents/schemas/_catalyst_research.py  (the committed case)
 *   tradingagents/web/catalyst_projection.py           (the read body)
 * which are the authority. `tsconfig.app.json` sets `resolveJsonModule: true`,
 * so these are real imports of the committed JSON, not copies.
 */
import { describe, expect, it } from "vitest";

import catalystBlocked from "../../../shared_fixtures/catalyst/catalyst_blocked.json";
import catalystLegacyRecord from "../../../shared_fixtures/catalyst/catalyst_legacy_record.json";
import catalystMinimalComplete from "../../../shared_fixtures/catalyst/catalyst_minimal_complete.json";
import catalystPartial from "../../../shared_fixtures/catalyst/catalyst_partial.json";
import catalystUnavailable from "../../../shared_fixtures/catalyst/catalyst_unavailable.json";
import catalystUnsupported from "../../../shared_fixtures/catalyst/catalyst_unsupported.json";

import {
  BRIEF_CHARACTER_BUDGET,
  CATALYST_CASE_SCHEMA_VERSION,
  CATALYST_EVIDENCE_POLICY_VERSION,
  CATALYST_ENDPOINT_VERSION,
  CATALYST_REQUEST_ERROR_CODES,
  PRIORITY_BLOCKING_REASONS,
  PROFILE_POLICY_VERSIONS,
  RESEARCH_PROFILES,
  SAFETY_OVERFLOW_TEMPLATE_BUDGET,
  briefBudgetFor,
  isCatalystReady,
  isCatalystUnavailable,
  isCatalystUnsupported,
  isResearchSufficient,
  isVerifyFirstPermitted,
  type CatalystBriefDTO,
  type CatalystLegacyRecordDTO,
  type CatalystReadState,
  type CatalystResearchCaseDTO,
  type CatalystResearchPriority,
  type ResearchProfile,
} from "./contracts";

/**
 * Read the committed case out of a ready fixture.
 *
 * JSON round-trips Python tuples as plain arrays, so `stage_durations_ms`
 * arrives as `Array<Array<string | number>>` rather than the 2-tuple the
 * server emits. The tuple element type is therefore a widening the compiler
 * sees, not a wire mismatch; asserting the shape here keeps the DTO honest
 * without weakening it to `unknown[][]`.
 */
function readCase(fixture: unknown): CatalystResearchCaseDTO {
  const stageDurations = (
    fixture as { case: { budget_usage: { stage_durations_ms: unknown[] } } }
  ).case.budget_usage.stage_durations_ms;
  for (const entry of stageDurations) {
    if (!Array.isArray(entry) || entry.length !== 2) {
      throw new Error("stage_durations_ms entries must be [stage, ms] pairs");
    }
  }
  return (fixture as { case: CatalystResearchCaseDTO }).case;
}

/** The same names the Python loader requires. */
const FIXTURE_NAMES = [  "catalyst_minimal_complete",
  "catalyst_partial",
  "catalyst_blocked",
  "catalyst_unavailable",
  "catalyst_unsupported",
  "catalyst_legacy_record",
];

const READY_FIXTURES: Array<[string, CatalystReadState]> = [
  ["catalyst_minimal_complete", catalystMinimalComplete as CatalystReadState],
  ["catalyst_partial", catalystPartial as CatalystReadState],
  ["catalyst_blocked", catalystBlocked as CatalystReadState],
];

const CASES: Array<[string, CatalystResearchCaseDTO]> = [
  ["catalyst_minimal_complete", readCase(catalystMinimalComplete)],
  ["catalyst_partial", readCase(catalystPartial)],
  ["catalyst_blocked", readCase(catalystBlocked)],
];

describe("shared fixtures", () => {
  it("covers every declared class", () => {
    expect(FIXTURE_NAMES).toHaveLength(6);
    expect([...FIXTURE_NAMES].sort()).toEqual(
      [
        "catalyst_blocked",
        "catalyst_legacy_record",
        "catalyst_minimal_complete",
        "catalyst_partial",
        "catalyst_unavailable",
        "catalyst_unsupported",
      ].sort(),
    );
  });

  it("carries a schema version on every fixture", () => {
    for (const fixture of [
      catalystMinimalComplete,
      catalystPartial,
      catalystBlocked,
      catalystUnavailable,
      catalystUnsupported,
      catalystLegacyRecord,
    ] as Array<{ schema_version: number; fixture_id: string; description: string }>) {
      expect(fixture.schema_version).toBe(1);
      expect(fixture.fixture_id).toBeTruthy();
      expect(fixture.description).toBeTruthy();
    }
  });
});

describe("ready — a committed catalyst artifact", () => {
  it.each(READY_FIXTURES)("%s satisfies the read contract", (_name, state) => {
    expect(state.state).toBe("ready");
    expect(isCatalystReady(state)).toBe(true);
    if (!isCatalystReady(state)) throw new Error("unreachable");
    expect(state.schema_version).toBe(CATALYST_ENDPOINT_VERSION);
    expect(state.case_schema_version).toBe(CATALYST_CASE_SCHEMA_VERSION);
    expect(state.case_schema_number).toBe(1);
    expect(typeof state.run_status).toBe("string");
  });

  it("covers all three completeness states", () => {
    const states = READY_FIXTURES.map(([, s]) =>
      isCatalystReady(s) ? s.completeness : "n/a",
    );
    expect([...new Set(states)].sort()).toEqual(["blocked", "complete", "partial"]);
  });

  it("separates a readable artifact from a sufficient result", () => {
    // ready means the artifact parses — it does not mean the research passed.
    expect(READY_FIXTURES.every(([, s]) => isCatalystReady(s))).toBe(true);
    expect(isResearchSufficient(catalystMinimalComplete as CatalystReadState)).toBe(true);
    expect(isResearchSufficient(catalystPartial as CatalystReadState)).toBe(false);
    expect(isResearchSufficient(catalystBlocked as CatalystReadState)).toBe(false);
    expect(isResearchSufficient(null)).toBe(false);
  });

  it("caps a non-complete case at insufficient_information", () => {
    for (const [name, state] of READY_FIXTURES) {
      if (!isCatalystReady(state)) throw new Error("unreachable");
      if (state.completeness === "complete") continue;
      expect(state.priority, name).toBe("insufficient_information");
      expect(state.quality, name).not.toBe("PASS");
      expect(state.limitations.length, name).toBeGreaterThan(0);
    }
  });
});

describe("the committed case", () => {
  it.each(CASES)("%s matches the canonical case schema", (_name, kase) => {
    expect(kase.schema_version).toBe(CATALYST_CASE_SCHEMA_VERSION);
    expect(kase.schema_number).toBe(1);
    expect(kase.research_profile).toBe("catalyst_v1");
    expect(kase.evidence_policy).toBe(CATALYST_EVIDENCE_POLICY_VERSION);
    expect(kase.budget_usage.model_usage_available).toBe(
      kase.budget_usage.input_tokens !== null,
    );
  });

  it("never couples a recorded priority to an unknown token count", () => {
    // Counting an unmeasurable token cost as zero is what makes a cost
    // regression invisible, so the contract forbids it.
    const partial = readCase(catalystPartial);
    expect(partial.budget_usage.model_usage_available).toBe(false);
    expect(partial.budget_usage.input_tokens).toBeNull();
    expect(partial.budget_usage.output_tokens).toBeNull();
  });

  it("applies the priority ceiling to the recorded decision", () => {
    for (const [name, kase] of CASES) {
      const decision = kase.priority_decision;
      for (const reason of decision.blocking_reasons) {
        expect(PRIORITY_BLOCKING_REASONS, `${name}:${reason}`).toContain(reason);
      }
      if (decision.priority !== decision.candidate_priority) {
        expect(decision.blocking_reasons.length, name).toBeGreaterThan(0);
      }
      if (decision.priority === "verify_first") {
        expect(isVerifyFirstPermitted(decision.blocking_reasons), name).toBe(true);
      }
    }
  });

  it("forbids verify_first whenever a blocking reason is present", () => {
    for (const reason of PRIORITY_BLOCKING_REASONS) {
      expect(isVerifyFirstPermitted([reason])).toBe(false);
    }
    expect(isVerifyFirstPermitted([])).toBe(true);
  });

  it("keeps a fact or inference bound to evidence and an unknown bare", () => {
    for (const [name, kase] of CASES) {
      for (const finding of kase.findings) {
        if (finding.kind === "unknown") {
          expect(finding.evidence_ids, `${name}:${finding.finding_id}`).toHaveLength(0);
          expect(finding.confidence, name).toBeNull();
          expect(finding.next_checks.length, name).toBeGreaterThan(0);
        } else {
          expect(finding.evidence_ids.length, `${name}:${finding.finding_id}`).toBeGreaterThan(0);
          expect(finding.confidence, name).not.toBeNull();
        }
        if (finding.kind === "inference") {
          expect(finding.supporting_finding_ids.length, name).toBeGreaterThan(0);
        }
      }
    }
  });

  it("gives every challenge exactly one disposition", () => {
    for (const [name, kase] of CASES) {
      const ids = kase.challenges.map((c) => c.challenge_id);
      const disposed = kase.dispositions.map((d) => d.challenge_id);
      expect([...disposed].sort(), name).toEqual([...ids].sort());
      for (const challenge of kase.challenges) {
        if (challenge.kind === "counter_evidence") {
          expect(challenge.evidence_ids.length, name).toBeGreaterThan(0);
        } else {
          expect(challenge.evidence_ids, name).toHaveLength(0);
        }
        if (challenge.is_key) expect(challenge.severity, name).toBe("critical");
      }
      for (const disposition of kase.dispositions) {
        if (disposition.outcome === "unresolved") {
          expect(disposition.retained_limitations.length, name).toBeGreaterThan(0);
        }
      }
    }
  });

  it("leaves an unsourced event date unknown", () => {
    for (const [name, kase] of CASES) {
      for (const event of kase.events) {
        if (event.date_precision === "unknown") {
          expect(event.occurred_on, `${name}:${event.event_id}`).toBeNull();
          expect(event.occurred_period_end, name).toBeNull();
        } else {
          expect(event.date_evidence_ids.length, name).toBeGreaterThan(0);
        }
      }
    }
  });
});

describe("brief budgets", () => {
  it("keeps each brief inside the budget its kind is measured against", () => {
    for (const [name, state] of READY_FIXTURES) {
      if (!isCatalystReady(state)) throw new Error("unreachable");
      const brief = state.brief as unknown as CatalystBriefDTO;
      expect(briefBudgetFor(brief.kind), name).toBe(BRIEF_CHARACTER_BUDGET);
    }
    expect(briefBudgetFor("ordinary")).toBe(BRIEF_CHARACTER_BUDGET);
    expect(briefBudgetFor("safety_overflow")).toBe(SAFETY_OVERFLOW_TEMPLATE_BUDGET);
  });

  it("carries the count on the read state, not on the brief", () => {
    // CatalystBrief has a derived `character_count` property in Python, which
    // model_dump does not emit — a producer could only lie accurately about
    // its own length. The endpoint reports it, from the text, once.
    for (const [name, state] of READY_FIXTURES) {
      if (!isCatalystReady(state)) throw new Error("unreachable");
      const brief = state.brief as unknown as Record<string, unknown>;
      expect("character_count" in brief, name).toBe(false);
      expect(state.brief_character_count, name).toBeGreaterThan(0);
      expect(state.brief_character_count, name).toBeLessThanOrEqual(BRIEF_CHARACTER_BUDGET);
    }
  });

  it("makes a safety-overflow brief information-insufficient and non-empty", () => {
    for (const [name, kase] of CASES) {
      const brief = kase.brief;
      if (brief.kind !== "safety_overflow") continue;
      expect(brief.priority, name).toBe("insufficient_information");
      expect(brief.critical_limitations.length, name).toBeGreaterThan(0);
      expect(brief.overflow_reason, name).toBe("brief_safety_overflow");
    }
  });
});

describe("unavailable and unsupported are not the same state", () => {
  const unavailable = catalystUnavailable as CatalystReadState;
  const unsupported = catalystUnsupported as CatalystReadState;

  it("routes by the `state` discriminator", () => {
    expect(isCatalystUnavailable(unavailable)).toBe(true);
    expect(isCatalystUnsupported(unavailable)).toBe(false);
    expect(isCatalystUnsupported(unsupported)).toBe(true);
    expect(isCatalystUnavailable(unsupported)).toBe(false);
    expect(isCatalystReady(unavailable)).toBe(false);
    expect(isCatalystReady(unsupported)).toBe(false);
  });

  it("keeps the run lifecycle only on the transient arm", () => {
    // A client polls again only when it can see whether the run is still going.
    expect((unavailable as { run_status: string }).run_status).toBe("running");
    expect((unavailable as { reason_code: string }).reason_code).toBe("run_running");
    expect((unsupported as { reason_code: string }).reason_code).toBe("classic_profile");
  });

  it("gives a classic run no case payload at all", () => {
    // `unsupported` must not smuggle empty `brief` / `case` arms into the
    // union: that is how a classic run starts rendering as a failed catalyst
    // research instead of "not applicable".
    const keys = Object.keys(unsupported as unknown as Record<string, unknown>);
    for (const caseOnly of [
      "completeness",
      "quality",
      "priority",
      "brief",
      "case",
      "limitations",
      "run_status",
    ]) {
      expect(keys).not.toContain(caseOnly);
    }
  });
});

describe("legacy records survive a reader upgrade without synthesis", () => {
  const legacy = catalystLegacyRecord as unknown as CatalystLegacyRecordDTO;

  it("is not a catalyst case at all", () => {
    expect(legacy.kind).toBe("legacy");
    const keys = Object.keys(legacy as unknown as Record<string, unknown>);
    for (const catalystOnly of ["completeness", "quality", "priority", "brief", "case"]) {
      expect(keys).not.toContain(catalystOnly);
    }
  });

  it("carries a null research_priority and must never gain one", () => {
    expect(legacy.research_priority).toBeNull();
    // isResearchSufficient only accepts a ready read state, so a legacy
    // record cannot be laundered into a verdict by the new reader.
    expect(isResearchSufficient(legacy as unknown as CatalystReadState)).toBe(false);
  });
});

describe("profile and policy versioning", () => {
  it("keeps the catalyst policy out of the horizon runtime enum", () => {
    // horizon-policy-v3 is an already-active test gate. Widening that Literal
    // to include the evidence policy would silently switch it on.
    expect(CATALYST_EVIDENCE_POLICY_VERSION).toBe("catalyst-evidence-policy-v1");
    expect(PROFILE_POLICY_VERSIONS.catalyst_v1).toBe(CATALYST_EVIDENCE_POLICY_VERSION);
    expect(PROFILE_POLICY_VERSIONS.classic).not.toBe(CATALYST_EVIDENCE_POLICY_VERSION);
    expect(PROFILE_POLICY_VERSIONS.classic).not.toBe("horizon-policy-v3");
  });

  it("separates the case contract from the endpoint contract", () => {
    expect(CATALYST_CASE_SCHEMA_VERSION).toBe("catalyst-research-case-v1");
    expect(CATALYST_ENDPOINT_VERSION).toBe(1);
    expect(CATALYST_CASE_SCHEMA_VERSION).not.toBe(String(CATALYST_ENDPOINT_VERSION));
  });

  it("exposes both profiles, classic first", () => {
    const profiles: readonly ResearchProfile[] = RESEARCH_PROFILES;
    expect(profiles).toEqual(["classic", "catalyst_v1"]);
  });

  it("publishes the frozen request error codes", () => {
    expect(CATALYST_REQUEST_ERROR_CODES).toContain("catalyst_profile_unavailable");
    expect(CATALYST_REQUEST_ERROR_CODES).toContain("catalyst_mode_unsupported");
    expect(CATALYST_REQUEST_ERROR_CODES).toContain("catalyst_market_unsupported");
    expect(CATALYST_REQUEST_ERROR_CODES).toContain(
      "catalyst_legacy_scheduling_params_not_applicable",
    );
    // None of them may claim a horizon runtime version.
    for (const code of CATALYST_REQUEST_ERROR_CODES) {
      expect(code.startsWith("horizon-policy-")).toBe(false);
    }
  });

  it("never publishes a priority outside the four registered values", () => {
    const allowed: CatalystResearchPriority[] = [
      "verify_first",
      "keep_watching",
      "defer_research",
      "insufficient_information",
    ];
    for (const [, kase] of CASES) {
      expect(allowed).toContain(kase.priority_decision.priority);
      expect(allowed).toContain(kase.priority_decision.candidate_priority);
      expect(allowed).toContain(kase.brief.priority);
    }
  });
});
