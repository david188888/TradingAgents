"""Model-visible capability cards: role scope, credentials and stable identity."""

from tradingagents.dataflows.capability_catalog import (
    CAPABILITY_CARDS,
    catalog_identity_digest,
    compact_capability_cards,
    load_capability_catalog,
)
from tradingagents.research.native_policy import ROLE_ORDER


def ids(cards):
    return {card.id for card in cards}


def test_card_ids_are_unique_and_roles_match_specialists():
    assert len(ids(CAPABILITY_CARDS)) == len(CAPABILITY_CARDS)
    assert all(set(card.roles) <= set(ROLE_ORDER) for card in CAPABILITY_CARDS)


def test_prefetch_only_and_unimplemented_cards_are_not_requestable():
    visible = ids(load_capability_catalog())
    assert visible == {"disclosure_search", "shareholder_count", "ir_qa",
        "longhubang", "holder_change", "consensus_eps", "valuation_history", "northbound_flow"}
    assert "core_financials" not in visible
    assert {"financials_detail", "industry_peers", "wind_enrich"} & visible == set()


def test_role_filter_limits_visible_cards():
    assert ids(load_capability_catalog(role="market_context")) == {
        "disclosure_search", "shareholder_count", "longhubang",
        "valuation_history", "northbound_flow"}
    assert ids(load_capability_catalog(role="event_context")) == {
        "disclosure_search", "ir_qa", "longhubang", "holder_change"}
    assert ids(load_capability_catalog(role="operating_quality")) == {
        "disclosure_search", "shareholder_count", "ir_qa", "holder_change",
        "consensus_eps", "valuation_history"}


def test_unmet_requirement_hides_card():
    assert "wind_enrich" not in ids(load_capability_catalog())
    assert "wind_enrich" in ids(load_capability_catalog(available_requirements={"wind_cli"}))
    assert "wind_enrich" in ids(load_capability_catalog(role="market_context",
        available_requirements={"wind_cli"}))


def test_compact_view_hides_backends_and_routing():
    compact = compact_capability_cards(load_capability_catalog())
    assert all(set(card) == {"id", "title", "solves", "not_for", "inputs", "cost"} for card in compact)


def test_identity_digest_is_order_independent_and_content_sensitive():
    cards = load_capability_catalog()
    assert catalog_identity_digest(cards) == catalog_identity_digest(tuple(reversed(cards)))
    assert catalog_identity_digest(cards) != catalog_identity_digest(cards[:-1])
