"""Evidence Steward node: gate weak or contradictory evidence before debate."""

from __future__ import annotations

import logging

from tradingagents.dataflows.evidence import (
    EvidenceGateError,
    EvidenceStatus,
    evaluate_and_enrich_evidence,
)
from tradingagents.research import build_research_dossier

logger = logging.getLogger(__name__)


def create_evidence_steward():
    def evidence_steward_node(state):
        try:
            result = evaluate_and_enrich_evidence(state)
            result["research_dossier"] = build_research_dossier({**state, **result})
            return result
        except EvidenceGateError:
            # A verdict-level hard stop is a research decision, not a system
            # fault. Preserve its terminal semantics for the graph runner.
            raise
        except Exception as exc:
            # Unexpected failures are distinct from evidence verdicts. Keep the
            # public fault category only; never leak vendor URLs or exception text.
            fault_category = type(exc).__name__
            logger.exception(
                "Evidence steward failed unexpectedly (fault category: %s)",
                fault_category,
            )
            report = "\n".join([
                "## Evidence Steward Report",
                "Status: gate error",
                f"Evidence status: {EvidenceStatus.GATE_ERROR.value}",
                f"Fault category: {fault_category}",
                "Evidence gate could not complete; no investment verdict is executable.",
            ])
            return {
                "evidence_status": EvidenceStatus.GATE_ERROR.value,
                "evidence_gate_fault": fault_category,
                "evidence_report": report,
                "evidence_ledger": None,
                "evidence_ledger_artifact_id": None,
                "research_dossier": build_research_dossier(state),
            }
    return evidence_steward_node
