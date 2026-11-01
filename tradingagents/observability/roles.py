"""Current Insight process role registry."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RoleDefinition:
    actor_id: str
    node_id: str
    team_id: str
    display_name: str
    icon_id: str
    analyst_key: str | None = None

NATIVE_ROLE_REGISTRY = tuple(
    RoleDefinition(f"native.{key}", key, "native", label, "verified-magnifier")
    for key, label in (("evidence", "Evidence freeze"), ("operating_quality", "Operating quality"),
        ("event_context", "Event context"), ("market_context", "Market context"),
        ("challenge", "Evidence challenge"), ("synthesis", "Research synthesis"))
)
UNIFIED_RESPONSE_REGISTRY = tuple(RoleDefinition(f"native.response_{key}", f"response_{key}", "native", label, "verified-magnifier")
    for key, label in (("operating_quality", "Operating reply"), ("event_context", "Event reply"), ("market_context", "Market reply")))
UNIFIED_ROLE_REGISTRY = (*NATIVE_ROLE_REGISTRY[:-1], *UNIFIED_RESPONSE_REGISTRY, NATIVE_ROLE_REGISTRY[-1])
FOCUS_ROLE = RoleDefinition("native.focus_response", "focus_response", "native", "Focus response", "verified-magnifier")



def roles_for_profile(profile="evidence_v1", *, workflow_version=None, focus_requested=False):
    from tradingagents.research.native_versions import INSIGHT_WORKFLOW_VERSION
    if profile != "evidence_v1" or workflow_version not in {None, INSIGHT_WORKFLOW_VERSION}:
        raise ValueError("unsupported research version")
    return (*UNIFIED_ROLE_REGISTRY, FOCUS_ROLE) if focus_requested else UNIFIED_ROLE_REGISTRY


def role_instance_id(run_id, actor_id):
    if not run_id or actor_id not in {r.actor_id for r in (*UNIFIED_ROLE_REGISTRY, FOCUS_ROLE)}:
        raise ValueError("unknown research role")
    return f"{run_id}:{actor_id}"

ROLE_REGISTRY = (*UNIFIED_ROLE_REGISTRY, FOCUS_ROLE)
ROLES_BY_ACTOR_ID = {role.actor_id: role for role in ROLE_REGISTRY}
ROLES_BY_NODE_ID = {role.node_id: role for role in ROLE_REGISTRY}
