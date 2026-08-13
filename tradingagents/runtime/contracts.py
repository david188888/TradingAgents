"""Explicit run-scoped contract selection for staged runtime evolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RuntimePolicyVersion = Literal["horizon-policy-v2", "horizon-policy-v3"]


@dataclass(frozen=True)
class RuntimeContractSelection:
    """Select one coherent fingerprint/state/observation contract family."""

    policy_version: RuntimePolicyVersion = "horizon-policy-v2"

    def __post_init__(self) -> None:
        if self.policy_version not in {
            "horizon-policy-v2",
            "horizon-policy-v3",
        }:
            raise ValueError("unsupported runtime policy version")

    @classmethod
    def production_v2(cls) -> RuntimeContractSelection:
        return cls("horizon-policy-v2")

    @classmethod
    def v3_test(cls) -> RuntimeContractSelection:
        """Return the internal test gate; production activation belongs to S8b."""

        return cls("horizon-policy-v3")


PRODUCTION_RUNTIME_CONTRACT = RuntimeContractSelection.production_v2()
