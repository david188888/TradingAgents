/**
 * T27 — hidden fields must not pollute the catalyst request.
 *
 * The catalyst form shows four inputs: company, research window, an optional
 * question, and start. The classic form's controls — role checkboxes, research
 * depth, horizon, holding quantity and average cost, portfolio, checkpoint —
 * are *not rendered* on the catalyst profile, but "not rendered" is not the
 * property that matters. The property is that their values cannot reach a
 * `catalyst_v1` request body, because the server rejects a request carrying
 * inputs for a flow it is not running, and a silently-ignored role list reads as
 * "my roles were applied" when they were not.
 *
 * These tests assert the request body, because that is the only place the
 * property is actually enforced.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConfigResponseDTO } from "../api/contracts";
import { getConfig } from "../api/client";
import { useConfig } from "./useConfig";

vi.mock("../api/client", () => ({ getConfig: vi.fn() }));

const mockedGetConfig = vi.mocked(getConfig);

function configResponse(): ConfigResponseDTO {
  return {
    providers: [
      {
        id: "openai",
        configured: true,
        requires_api_key: true,
        custom_model_allowed: true,
        models: {
          quick: [{ id: "gpt-4o-mini", label: "gpt-4o-mini" }],
          deep: [{ id: "gpt-4o", label: "gpt-4o" }],
        },
      },
    ],
    configured_keys: { openai: true },
    analysts: [
      { id: "fundamentals" },
      { id: "technical" },
      { id: "sentiment" },
      { id: "news" },
    ],
    presets: [],
    depths: [1, 3, 5],
    output_languages: ["zh", "en"],
    checkpoint_available: true,
    wind: { enabled: false, configured: false, capabilities: [] },
    defaults: {
      llm_provider: "openai",
      quick_think_llm: "gpt-4o-mini",
      deep_think_llm: "gpt-4o",
      output_language: "zh",
      research_depth: 3,
      checkpoint_enabled: false,
    },
  };
}

/** Wait for the config read, then hand the hook back to the test. */
async function mountConfig() {
  mockedGetConfig.mockResolvedValue(configResponse());
  const rendered = renderHook(() => useConfig());
  await waitFor(() => expect(rendered.result.current.config).not.toBeNull());
  return rendered;
}

describe("T27 — the catalyst request carries no classic-only fields", () => {
  beforeEach(() => {
    mockedGetConfig.mockReset();
  });

  it("omits every hidden classic control even after they are set", async () => {
    const { result } = await mountConfig();

    // Every classic-only control the catalyst form does not show, set to a
    // value that would be visible on the wire if the builder read it.
    act(() => {
      result.current.setSelectedAnalysts(["fundamentals", "technical", "sentiment", "news"]);
      result.current.setResearchDepth(5);
      result.current.setMode("holding_review");
      result.current.setHorizon("long");
      result.current.setHoldingQuantity("1000");
      result.current.setHoldingAverageCost("12.5");
      result.current.setCheckpointEnabled(true);
      result.current.setTicker("  600519  ");
    });

    // Read through the live result, not the pre-`act` snapshot: these setters
    // are state, and the builder closes over the current render's values.
    const body = result.current.buildCatalystRequest();
    expect(body).not.toBeNull();

    // The four fields the form actually shows, plus the profile.
    expect(body?.ticker).toBe("600519");
    expect(body?.research_profile).toBe("catalyst_v1");
    // `research_question` is case-side on this wire, never a request field.
    expect(body).not.toHaveProperty("research_question");

    /*
      The hidden classic controls.

      Design 7.1 is explicit that `selected_analysts`, `research_depth` and
      `max_debate_rounds` carry no scheduling authority in this profile, that
      compatibility fields keep *default* values so the server can normalize
      them, and that a non-default explicit combination of old scheduling
      parameters is a readable validation error. So the rule is not "omit the
      field" — it is "never send the hidden form's value". The classic depth of
      5 must not travel, and the compatibility default must be what arrives.
    */
    expect(body?.selected_analysts).toEqual([]);
    expect(body?.research_depth).not.toBe(5);
    expect(body?.research_depth).toBe(3);
    expect(body?.mode).toBe("company_research");
    // Design 7.1: the new entry point sends `horizon=medium` for compatibility.
    expect(body?.horizon).toBe("medium");
    expect(body).not.toHaveProperty("holding");
    expect(body).not.toHaveProperty("portfolio");
    expect(body?.checkpoint_enabled).toBe(false);
  });

  it("names no classic-only key at all, so a new one cannot slip in", async () => {
    const { result } = await mountConfig();
    act(() => {
      result.current.setTicker("600519");
    });
    const body = result.current.buildCatalystRequest();
    expect(body).not.toBeNull();
    /*
      A per-key allowlist, rather than a list of forbidden keys. This is the
      assertion that survives someone adding a classic control to the builder
      later: a new key fails here without anyone remembering to extend a
      denylist.
    */
    expect(Object.keys(body ?? {}).sort()).toEqual([
      "analysis_date",
      "asset_type",
      "checkpoint_enabled",
      "deep_think_llm",
      "horizon",
      "llm_provider",
      "mode",
      "output_language",
      "quick_think_llm",
      "research_depth",
      "research_profile",
      "selected_analysts",
      "ticker",
    ]);
  });

  it("returns null for an empty ticker rather than sending a blank one", async () => {
    const { result } = await mountConfig();
    act(() => {
      result.current.setTicker("   ");
    });
    expect(result.current.buildCatalystRequest()).toBeNull();
  });

  it("keeps the classic request builder on the role selection", async () => {
    const { result } = await mountConfig();
    act(() => {
      result.current.setTicker("600519");
      result.current.setSelectedAnalysts(["fundamentals", "news"]);
      result.current.setResearchDepth(5);
      result.current.setMode("company_research");
    });
    const body = result.current.buildRequest();
    expect(body?.selected_analysts).toEqual(["fundamentals", "news"]);
    expect(body?.research_depth).toBe(5);
    // The classic request does not carry a profile field; omission means
    // classic on the server.
    expect(body?.research_profile).toBeUndefined();
  });

  it("keeps the classic role selection across a round trip through catalyst_v1", async () => {
    /*
      T27's last clause: "旧模式切换保留原角色选择" — switching to the new
      profile and back must not reset what the classic form had selected.
      `setResearchProfile` only ever touches `researchProfile`; there is no
      code path from it to `selectedAnalysts`, so this is a property of the
      hook's state shape, not of any explicit reset-guard — which is exactly
      what makes it worth asserting: a future edit that adds one would break
      it silently.
    */
    const { result } = await mountConfig();
    act(() => {
      result.current.setTicker("600519");
      result.current.setSelectedAnalysts(["fundamentals", "news"]);
      result.current.setResearchDepth(5);
    });
    act(() => {
      result.current.setResearchProfile("catalyst_v1");
    });
    expect(result.current.research_profile).toBe("catalyst_v1");
    // Still there while catalyst_v1 is selected...
    expect(result.current.selected_analysts).toEqual(["fundamentals", "news"]);
    expect(result.current.research_depth).toBe(5);

    act(() => {
      result.current.setResearchProfile("classic");
    });
    // ...and unchanged on the way back, so the classic form reappears exactly
    // as the reader left it.
    expect(result.current.selected_analysts).toEqual(["fundamentals", "news"]);
    expect(result.current.research_depth).toBe(5);
    const body = result.current.buildRequest();
    expect(body?.selected_analysts).toEqual(["fundamentals", "news"]);
    expect(body?.research_depth).toBe(5);
  });
});

describe("T27 — the effective config describes the catalyst flow", () => {
  beforeEach(() => {
    mockedGetConfig.mockReset();
  });

  it("lists the four bounded stages, not the classic role set", async () => {
    const { result } = await mountConfig();
    act(() => {
      result.current.setResearchProfile("catalyst_v1");
    });
    const effective = result.current.effectiveCatalystConfig;
    expect(effective.profile).toBe("catalyst_v1");
    expect(effective.stages).toEqual(["准备证据", "专项分析", "反证核验", "综合发布"]);
  });

  it("reports deployment support as unconfirmed when the server omits it", async () => {
    const { result } = await mountConfig();
    act(() => {
      result.current.setResearchProfile("catalyst_v1");
    });
    // `ConfigResponseDTO` has no profile-support field on this wire yet, so the
    // honest answer is "unknown" — not `true`, which would read as a promise
    // the deployment never made.
    expect(result.current.effectiveCatalystConfig.supported).toBeNull();
  });
});
