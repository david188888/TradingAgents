"""Code-owned mapping between research claim lenses and data capabilities."""

from __future__ import annotations

from collections.abc import Iterable

LENS_CAPABILITIES: dict[str, frozenset[str]] = {
    "market": frozenset(
        {
            "verified_identity",
            "verified_market_snapshot",
            "adjusted_price_history",
        }
    ),
    "fundamentals": frozenset(
        {"fundamentals_quarterly", "fundamentals_annual"}
    ),
    "news": frozenset({"company_event_window", "official_disclosures"}),
    # Supplement capabilities are discovered from the current registry.  They
    # belong to sentiment only when they are not owned by another fixed lens.
    "sentiment": frozenset(),
}

FIXED_LENS_CAPABILITIES = frozenset().union(*LENS_CAPABILITIES.values())


def capabilities_for_lens(
    lens: str,
    observed_capabilities: Iterable[str],
) -> frozenset[str]:
    """Return the capabilities that may support facts for ``lens``."""

    if lens != "sentiment":
        return LENS_CAPABILITIES.get(lens, frozenset())
    return frozenset(observed_capabilities) - FIXED_LENS_CAPABILITIES
