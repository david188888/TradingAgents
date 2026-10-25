"""The server environment can disable independent Search/Fetch for new runs."""

from dataclasses import replace

import pytest

from tradingagents.default_config import DEFAULT_CONFIG, _apply_env_overrides
from tradingagents.execution.models import AnalysisRequest
from tradingagents.web.manager import _complete_request

pytestmark = pytest.mark.unit


def test_server_search_disable_is_boolean_and_flows_into_new_request(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_SEARCH_ENABLED", "false")
    server_config = _apply_env_overrides(dict(DEFAULT_CONFIG))
    assert server_config["evidence_search_enabled"] is False
    monkeypatch.setitem(DEFAULT_CONFIG, "evidence_search_enabled", server_config["evidence_search_enabled"])
    request = AnalysisRequest(ticker="600803.SS", analysis_date="2026-10-25", research_profile="evidence_v1")
    assert _complete_request(request).effective_config["evidence_search_enabled"] is False
    # A frozen request must retain its identity when the server default changes.
    frozen = replace(request, effective_config={"evidence_search_enabled": True})
    assert _complete_request(frozen).effective_config["evidence_search_enabled"] is True


def test_invalid_search_disable_environment_fails_explicitly(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_EVIDENCE_SEARCH_ENABLED", "maybe")
    with pytest.raises(ValueError, match="TRADINGAGENTS_EVIDENCE_SEARCH_ENABLED"):
        _apply_env_overrides(dict(DEFAULT_CONFIG))
