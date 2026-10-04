"""Language-independent role registry for the complete TradingAgents graph."""

from __future__ import annotations

from dataclasses import dataclass

from tradingagents.analysts import ANALYST_CONFIG


@dataclass(frozen=True)
class RoleDefinition:
    actor_id: str
    node_id: str
    team_id: str
    display_name: str
    icon_id: str
    analyst_key: str | None = None


ROLE_REGISTRY: tuple[RoleDefinition, ...] = (
    *(
        RoleDefinition(
            definition.actor_id,
            definition.node_id,
            "analysts",
            definition.display_name,
            definition.icon_id,
            definition.key,
        )
        for definition in ANALYST_CONFIG
    ),
    RoleDefinition(
        "evidence.steward",
        "Evidence Steward",
        "evidence",
        "Evidence Steward",
        "verified-magnifier",
    ),
    RoleDefinition(
        "researcher.bull",
        "Bull Researcher",
        "research",
        "Bull Researcher",
        "rising-horn",
    ),
    RoleDefinition(
        "researcher.bear",
        "Bear Researcher",
        "research",
        "Bear Researcher",
        "falling-paw",
    ),
    RoleDefinition(
        "manager.research",
        "Research Manager",
        "research",
        "Research Manager",
        "scales",
    ),
    RoleDefinition(
        "trader",
        "Trader",
        "trading",
        "Trader",
        "opposing-arrows",
    ),
    RoleDefinition(
        "risk.aggressive",
        "Aggressive Analyst",
        "risk",
        "Aggressive Risk Analyst",
        "lightning",
    ),
    RoleDefinition(
        "risk.neutral",
        "Neutral Analyst",
        "risk",
        "Neutral Risk Analyst",
        "centered-crosshair",
    ),
    RoleDefinition(
        "risk.conservative",
        "Conservative Analyst",
        "risk",
        "Conservative Risk Analyst",
        "shield",
    ),
    RoleDefinition(
        "manager.portfolio",
        "Portfolio Manager",
        "portfolio",
        "Portfolio Manager",
        "portfolio-compass",
    ),
)

ROLES_BY_ACTOR_ID = {role.actor_id: role for role in ROLE_REGISTRY}
ROLES_BY_NODE_ID = {role.node_id: role for role in ROLE_REGISTRY}

# The classic registry and its projections retain their exact membership.
CATALYST_ROLE_REGISTRY = tuple(
    RoleDefinition(f"catalyst.{key}", key, "catalyst", label, "verified-magnifier")
    for key, label in (
        ("evidence", "Evidence freeze"), ("catalyst_events", "Catalyst events"),
        ("operating_delivery", "Operating delivery"), ("market_reaction", "Market reaction"),
        ("refutation", "Independent refutation"), ("synthesis", "Synthesis"),
    )
)


NATIVE_ROLE_REGISTRY = tuple(
    RoleDefinition(f"native.{key}", key, "native", label, "verified-magnifier")
    for key, label in (("evidence", "Evidence freeze"), ("operating_quality", "Operating quality"),
        ("event_context", "Event context"), ("market_context", "Market context"),
        ("challenge", "Evidence challenge"), ("synthesis", "Research synthesis"))
)


def roles_for_profile(profile: str = "classic") -> tuple[RoleDefinition, ...]:
    if profile == "evidence_v1":
        return NATIVE_ROLE_REGISTRY
    return CATALYST_ROLE_REGISTRY if profile == "catalyst_v1" else ROLE_REGISTRY


def role_instance_id(run_id: str, actor_id: str) -> str:
    if actor_id not in ROLES_BY_ACTOR_ID and actor_id not in {role.actor_id for role in (*CATALYST_ROLE_REGISTRY, *NATIVE_ROLE_REGISTRY)}:
        raise KeyError(f"unknown TradingAgents actor_id: {actor_id}")
    if not run_id:
        raise ValueError("run_id is required")
    return f"{run_id}:{actor_id}"
