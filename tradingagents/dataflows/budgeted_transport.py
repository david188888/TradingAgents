"""Explicit, retry-free HTTP transport for bounded research sources."""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests

from tradingagents.execution.budget import BudgetBucket

_DATA_SLOTS = threading.BoundedSemaphore(2)


class BudgetedSession(requests.Session):
    def __init__(self, ledger: Any, ensure_active: Any, remaining_seconds: Any):
        super().__init__()
        self.ledger = ledger
        self.ensure_active = ensure_active
        self.remaining_seconds = remaining_seconds
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        # requests' default adapter has retries=0; make this invariant explicit.
        self.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        self.mount("http://", requests.adapters.HTTPAdapter(max_retries=0))

    def send(self, request, **kwargs):
        self.ensure_active()
        while not _DATA_SLOTS.acquire(timeout=min(0.1, self.remaining_seconds())):
            self.ensure_active()
        grant = None
        started = time.monotonic()
        try:
            self.ensure_active()
            with self._sequence_lock:
                self._sequence += 1
                logical = f"http.{urlsplit(request.url).hostname}.{self._sequence}"
            grant = self.ledger.reserve_or_raise(
                BudgetBucket.DATA_HTTP_ATTEMPTS, stage="evidence", logical_call_id=logical,
            )
            self.ledger.mark_dispatched(grant)
            timeout = kwargs.get("timeout", 15)
            if isinstance(timeout, tuple):
                timeout = max(timeout)
            kwargs["timeout"] = min(float(timeout or 15), max(0.01, self.remaining_seconds()))
            # Sources pin their canonical endpoint. Nested redirect dispatch while
            # holding a global slot can deadlock; redirects are an unqualified
            # response here rather than an unobserved extra source attempt.
            kwargs["allow_redirects"] = False
            response = super().send(request, **kwargs)
            self.ledger.settle(grant, ok=response.ok, duration_ms=int((time.monotonic()-started)*1000), usage_available=False)
            self.ensure_active()
            return response
        except Exception:
            if grant is not None:
                self.ledger.settle(grant, ok=False, usage_available=False)
            raise
        finally:
            _DATA_SLOTS.release()
