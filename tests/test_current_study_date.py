"""A browser left open overnight cannot freeze yesterday's study date."""
from datetime import datetime, timezone

import pytest

from tradingagents.web import schemas


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 26, 16, 30, tzinfo=timezone.utc).astimezone(tz)


@pytest.mark.parametrize("model", [schemas.RunCreateRequest, schemas.BatchRunConfigRequest])
def test_omitted_date_uses_shanghai_day_at_request_creation(model, monkeypatch):
    monkeypatch.setattr(schemas, "datetime", Clock, raising=False)
    payload = {"llm_provider": "deepseek", "quick_think_llm": "deepseek-flash",
               "deep_think_llm": "deepseek-flash", "research_profile": "evidence_v1"}
    if model is schemas.RunCreateRequest:
        payload["ticker"] = "002130"
    assert model.model_validate(payload).analysis_date == "2026-10-27"
    assert model.model_validate({**payload, "analysis_date": "2026-10-25"}).analysis_date == "2026-10-25"
