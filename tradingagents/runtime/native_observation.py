"""Observation coverage, independent of research/recovery identity and budgets."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SDK_OBSERVATION_KEY = "native_sdk_observation"


class NativeSDKObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["native-sdk-authorization-observation-v1"] = (
        "native-sdk-authorization-observation-v1"
    )
    start_sequence: int = Field(ge=0)
    prior_main_authorizations: int = Field(ge=0)
    prior_repair_authorizations: int = Field(ge=0)
    prior_focus_authorizations: int | None = Field(default=None, ge=0)

    @property
    def complete(self) -> bool:
        return self.prior_main_authorizations == self.prior_repair_authorizations == 0 and self.prior_focus_authorizations in (None, 0)


def establish_sdk_observation(ledger) -> None:
    """Called by the SDK adapter before the kernel can dispatch MAIN work.

    A resumed legacy run is only partially covered. Never retroactively certify
    its previous calls, and never write from a Reader/Audit projection.
    """
    journal = ledger.journal
    with journal.lock:
        if SDK_OBSERVATION_KEY in journal.state:
            NativeSDKObservationV1.model_validate(journal.state[SDK_OBSERVATION_KEY])
            return
        from tradingagents.execution.budget import BudgetBucket

        records = [r for r in ledger.records() if r.dispatched_at is not None]
        from tradingagents.research.native_versions import FOCUS_WORKFLOW_VERSION
        marker = NativeSDKObservationV1(
            start_sequence=journal.last_event.sequence,
            prior_main_authorizations=sum(r.bucket == BudgetBucket.MAIN_ANALYSIS for r in records),
            prior_repair_authorizations=sum(
                r.bucket == BudgetBucket.STRUCTURED_REPAIR for r in records
            ),
            **({"prior_focus_authorizations": sum(r.bucket == BudgetBucket.FOCUS_RESPONSE for r in records)}
               if journal.state["identity"].get("workflow_version") == FOCUS_WORKFLOW_VERSION else {}),
        )
        journal.put(SDK_OBSERVATION_KEY, marker.model_dump(mode="json", exclude_none=True))
