"""Typed source admission for the initial bounded A-share profile.

Only explicit transports are admitted here: an opaque SDK or subprocess with
unobservable retries cannot satisfy the profile's HTTP-attempt ceiling.
Failure is recorded as a missing capability, never as a proved empty window.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas._source_evidence import CapturedSourceEvidence
from tradingagents.research.evidence_freeze import (
    FreezeInputs,
)


def _iso_api_date(value: str) -> str:
    return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}").isoformat()


class SourceTransport:
    def __init__(self, request: Any, run_id: str, session: Any, fetch: Any):
        self.request, self.run_id, self.session, self.fetch = request, run_id, session, fetch
        self.context: dict[str, Any] = {}

    def tushare(self, api_name: str, fields: str, **params) -> list[dict[str, Any]]:
        token = os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_API_KEY")
        if not token:
            raise ValueError("tushare_not_configured")
        response = self.session.post("https://api.tushare.pro", json={
            "api_name": api_name, "token": token, "params": params, "fields": fields,
        }, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            # Vendor messages can echo request fields. Persist only a code.
            raise ValueError(f"tushare_rejected_{payload.get('code')}")
        data = payload.get("data") or {}
        columns, rows = data.get("fields"), data.get("items")
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ValueError("tushare_invalid_shape")
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def evidence(self, inputs: FreezeInputs, capability: str, source: str, content: Any,
                 *, published: str | None = None, public_url: str | None = None) -> None:
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        evidence_id = f"e.{capability}.d{digest[:16]}"
        observed = min(datetime.now(timezone.utc), datetime.combine(
            date.fromisoformat(inputs.cutoff), time.max, ZoneInfo("Asia/Shanghai")))
        record = CapturedSourceEvidence(
            evidence_id=evidence_id, run_id=self.run_id, ticker=inputs.ticker,
            capability=capability, source_tier="official" if source == "cninfo" else "vendor",
            source_name=source, source_family_id=f"{source}:{digest}", public_url=public_url,
            captured_at=datetime.now(timezone.utc), observed_at=observed,
            published_at=datetime.fromisoformat(published+"T00:00:00+08:00") if published else None,
            usable_as_of=observed, time_basis="known by research cutoff; publication date checked",
            value_basis="source-reported values; monetary fields CNY, prices CNY/share",
        )
        inputs.evidence.append(record.model_dump(mode="json"))
        self.context[evidence_id] = content

