"""Capability-scoped circuit breaker for data providers.

The registry intentionally has no knowledge of provider implementations. The
router records outcomes under a ``(vendor, market, capability)`` key so an
unhealthy quote endpoint cannot suppress an otherwise healthy news or
fundamentals endpoint from the same provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

RATE_LIMIT_COOLDOWN_SECONDS = 60.0
TRANSIENT_FAILURE_COOLDOWN_SECONDS = 20.0

# Long cooldowns for conditions that require human intervention or quota reset.
MANUAL_RECOVERY_COOLDOWN_SECONDS = 86400.0  # 24h; cleared by record_success/clear
DAILY_QUOTA_COOLDOWN_SECONDS = 86400.0  # 24h; cleared by record_success/clear

RecoveryType = str  # "timed" | "manual" | "quota"


@dataclass(frozen=True)
class VendorHealthKey:
    vendor: str
    market: str
    capability: str


@dataclass(frozen=True)
class Cooldown:
    key: VendorHealthKey
    reason: str
    retry_at: float
    recovery: RecoveryType = "timed"

    def remaining_seconds(self, now: float) -> float:
        if self.recovery in ("manual", "quota"):
            return float("inf")
        return max(0.0, self.retry_at - now)


class VendorHealthRegistry:
    """In-process provider cooldown state with an injectable monotonic clock."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._cooldowns: dict[VendorHealthKey, Cooldown] = {}

    def cooldown_for(
        self,
        *,
        vendor: str,
        market: str,
        capability: str,
    ) -> Cooldown | None:
        key = VendorHealthKey(vendor, market, capability)
        cooldown = self._cooldowns.get(key)
        if cooldown is None:
            return None
        # Manual/quota locks never auto-expire; only record_success/clear clears them.
        if cooldown.recovery in ("manual", "quota"):
            return cooldown
        if cooldown.retry_at <= self._clock():
            self._cooldowns.pop(key, None)
            return None
        return cooldown

    def record_failure(
        self,
        *,
        vendor: str,
        market: str,
        capability: str,
        cooldown_seconds: float,
        reason: str,
        recovery: str = "timed",
    ) -> None:
        if cooldown_seconds <= 0 and recovery == "timed":
            return
        key = VendorHealthKey(vendor, market, capability)
        if recovery in ("manual", "quota"):
            retry_at = float("inf")
        else:
            retry_at = self._clock() + cooldown_seconds
        self._cooldowns[key] = Cooldown(
            key=key,
            reason=reason,
            retry_at=retry_at,
            recovery=recovery,
        )

    def record_lock(
        self,
        *,
        vendor: str,
        market: str,
        capability: str,
        reason: str,
        recovery: str = "manual",
    ) -> None:
        """Lock a vendor capability until explicit record_success/clear.

        Used for AUTH_ERROR (manual key rotation), BALANCE_ERROR (manual top-up),
        and DAILY_LIMIT_ERROR (quota reset) where short retries are pointless.
        """
        self.record_failure(
            vendor=vendor,
            market=market,
            capability=capability,
            cooldown_seconds=0,
            reason=reason,
            recovery=recovery,
        )

    def record_success(self, *, vendor: str, market: str, capability: str) -> None:
        self._cooldowns.pop(VendorHealthKey(vendor, market, capability), None)

    def clear(self) -> None:
        self._cooldowns.clear()


# Process-global health registry instance (cooldown state shared by the router
# and the vendor-error recording helpers). Kept here so vendor_errors.py can
# import it without depending on the routing core.
_vendor_health = VendorHealthRegistry()


def set_vendor_health_registry(registry: VendorHealthRegistry) -> None:
    """Replace health state (dependency injection for deterministic tests)."""
    global _vendor_health
    _vendor_health = registry


def clear_vendor_health() -> None:
    """Clear in-process cooldowns without changing provider configuration."""
    _vendor_health.clear()
