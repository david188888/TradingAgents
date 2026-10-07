import { describe, expect, it } from "vitest";
import type { PersistedEventDTO, RunSnapshotDTO } from "../api/contracts";
import { NATIVE_ROLE_REGISTRY, ROLE_REGISTRY } from "./model";
import { createInitialState, runReducer } from "./runReducer";
import { roleList } from "./selectors";

const RUN_ID = "run-native";
const snapshot: RunSnapshotDTO = {
  run_id: RUN_ID, status: "running", ticker: "600519.SS", asset_type: "stock",
  analysis_date: "2026-10-02", selected_analysts: ["market", "social", "news", "fundamentals"],
  max_debate_rounds: 1, max_risk_discuss_rounds: 1, output_language: "Chinese",
  llm_provider: "deepseek", quick_think_llm: "quick", deep_think_llm: "deep", configured_keys: {},
  created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:01Z", latest_sequence: 0,
  artifacts: [], redaction_manifest: [], event_schema_version: 1, metadata: { research_profile: "evidence_v1" },
};
function event(sequence: number, type: string, payload: Record<string, unknown>): PersistedEventDTO {
  return { run_id: RUN_ID, event_id: `${RUN_ID}:${sequence}`, sequence, type, payload,
    timestamp: "2026-10-02T00:00:00Z", schema_version: 1 };
}

describe("native reducer and role projections", () => {
  it("selects the supplemental role only for requested V6 focus and replays its state", () => {
    const metadata = {research_profile:"evidence_v1",native_workflow_version:"evidence-production-v6",research_question:"AI 关系"};
    let state = createInitialState({...snapshot,metadata});
    expect(roleList(state)).toHaveLength(7);
    state = runReducer(state,{type:"event",event:event(1,"run.started",{research_profile:"evidence_v1",native_workflow_version:"evidence-production-v6",focus_requested:true})});
    state = runReducer(state,{type:"event",event:event(2,"role.status_changed",{role_instance_id:`${RUN_ID}:native.focus_response`,previous_status:"pending",new_status:"completed"})});
    expect(roleList(state).at(-1)?.status).toBe("completed");
    expect(roleList(createInitialState({...snapshot,metadata:{...metadata,native_workflow_version:"evidence-production-v5"}}))).toHaveLength(6);
    expect(roleList(createInitialState({...snapshot,metadata:{...metadata,research_question:null}}))).toHaveLength(6);
  });
  it("seeds six native roles from the snapshot while retaining the exact classic registry", () => {
    const native = createInitialState(snapshot);
    expect(native.meta.research_profile).toBe("evidence_v1");
    expect(roleList(native).map((item) => item.actor_id)).toEqual(NATIVE_ROLE_REGISTRY.map((item) => item.actor_id));
    expect(Object.keys(native.roles)).toHaveLength(6);
    expect(native.roles["researcher.bull"]).toBeUndefined();
    expect(ROLE_REGISTRY).toHaveLength(13);
    const classic = createInitialState({ ...snapshot, metadata: {} });
    expect(classic.meta.research_profile).toBe("classic");
    expect(Object.keys(classic.roles)).toHaveLength(13);
  });

  it("retains native run identity and accepts native role events in live and batch replay", () => {
    const events = [event(1, "run.started", { research_profile: "evidence_v1", ticker: "600519.SS" }),
      event(2, "role.status_changed", { role_instance_id: `${RUN_ID}:native.evidence`, previous_status: "pending", new_status: "completed" }),
      event(3, "role.status_changed", { role_instance_id: `${RUN_ID}:native.operating_quality`, previous_status: "pending", new_status: "running" })];
    const live = events.reduce((state, item) => runReducer(state, { type: "event", event: item }), createInitialState());
    let replay = createInitialState();
    for (const item of [...events]) replay = runReducer(replay, { type: "event", event: item });
    expect(live).toEqual(replay);
    expect(live.meta.research_profile).toBe("evidence_v1");
    expect(live.roles["native.evidence"].status).toBe("completed");
    expect(roleList(live).find((item) => item.actor_id === "native.operating_quality")?.status).toBe("running");
  });

  it("does not let an older run.started payload erase the snapshot profile", () => {
    const state = runReducer(createInitialState(snapshot), { type: "event", event: event(1, "run.started", { ticker: "600519.SS" }) });
    expect(state.meta.research_profile).toBe("evidence_v1");
    expect(Object.keys(state.roles)).toHaveLength(6);
  });
});
