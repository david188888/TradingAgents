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
    assert visible == {"news_search", "disclosure_search", "shareholder_count", "ir_qa",
        "longhubang", "holder_change", "consensus_eps"}
    assert "core_financials" not in visible
    assert "northbound_flow" not in visible


def test_role_filter_limits_visible_cards():
    assert ids(load_capability_catalog(role="market_context")) == {
        "news_search", "disclosure_search", "shareholder_count", "longhubang"}
    assert ids(load_capability_catalog(role="event_context")) == {
        "news_search", "disclosure_search", "ir_qa", "longhubang", "holder_change"}
    assert ids(load_capability_catalog(role="operating_quality")) == {
        "news_search", "disclosure_search", "shareholder_count", "ir_qa", "holder_change", "consensus_eps"}


def test_unmet_requirement_hides_card(monkeypatch):
    import tradingagents.dataflows.capability_catalog as module
    wind = next(card for card in CAPABILITY_CARDS if card.id == "wind_enrich")
    monkeypatch.setattr(module, "CAPABILITY_CARDS", (*CAPABILITY_CARDS[:-1],
        module.CapabilityCard(**{**wind.__dict__, "implemented": True})))
    assert "wind_enrich" not in ids(module.load_capability_catalog())
    assert "wind_enrich" in ids(module.load_capability_catalog(available_requirements={"wind_cli"}))


def test_compact_view_hides_backends_and_routing():
    compact = compact_capability_cards(load_capability_catalog())
    assert all(set(card) == {"id", "title", "solves", "not_for", "inputs", "cost"} for card in compact)


def test_identity_digest_is_order_independent_and_content_sensitive():
    cards = load_capability_catalog()
    assert catalog_identity_digest(cards) == catalog_identity_digest(tuple(reversed(cards)))
    assert catalog_identity_digest(cards) != catalog_identity_digest(cards[:-1])
