"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from tradingagents.research.claim_registry import (  # noqa: F401 - facade re-export
    ALL_EVIDENCE_KEYS,
    BUNDLE_EVIDENCE_KEYS,
    CLAIM_LENSES,
    CLAIM_PREDICATES,
    CLAIM_TOPICS,
    REPORT_EVIDENCE_KEYS,
    available_candidate_keys,
    validate_claim_key,
)

from ._catalyst_research import (  # noqa: F401  - facade re-export
    BRIEF_CHARACTER_BUDGET,
    BRIEF_CHARACTER_TARGET_MAX,
    BRIEF_CHARACTER_TARGET_MIN,
    CATALYST_CASE_SCHEMA_NUMBER,
    CATALYST_CASE_SCHEMA_VERSION,
    PRIORITY_BLOCKING_REASONS,
    SAFETY_OVERFLOW_PRIORITY,
    SAFETY_OVERFLOW_REASON,
    SAFETY_OVERFLOW_TEMPLATE_BUDGET,
    BriefLine,
    BudgetUsage,
    CatalystBrief,
    CatalystEvent,
    CatalystEvidence,
    CatalystResearchCase,
    Challenge,
    ChallengeDisposition,
    ClaimKind,
    NumericFact,
    ResearchPriority,
    ResearchPriorityDecision,
    SpecialistFinding,
    brief_character_count,
)
from ._common import (  # noqa: F401  - facade re-export
    ModelClaimInput,
    PortfolioRating,
)
from ._learning_research import (
    HoldingThesisAssessment,
    LearningResearchSummary,
    render_learning_research_summary,
)
from ._research import (  # noqa: F401  - facade re-export
    ResearchDelegationTask,
    ResearchPlan,
    ResearchPublicDigest,
    ResearchStrategySignal,
    render_research_plan,
)
from ._research_assessment import (  # noqa: F401 - facade re-export
    ChallengeAssessmentV1,
    DimensionAssessmentV1,
    ResearchAssessmentV1,
)
from ._research_case import (  # noqa: F401 - facade re-export
    AnalystCard,
    CapabilityStatus,
    ConflictRecord,
    CoverageRefV1,
    DataQuality,
    DebateDigest,
    EvidenceRefV2,
    PublicClaim,
    ResearchCaseV2,
    ResearchScenario,
    ReviewItem,
    ReviewPlan,
    ScenarioSet,
)
from ._research_case_draft import (
    ClaimDraft,
    LearningResearchCaseDraft,
    ReviewItemDraft,
    ScenarioDraft,
    render_learning_case_draft,
)
from ._research_focus import (  # noqa: F401 - facade re-export
    FOCUS_RESPONSE_CONTRACT,
    FocusProposalV1,
    ResearchFocusResponseV1,
)
from ._research_record import (  # noqa: F401 - facade re-export
    RESEARCH_RECORD_CONTRACT,
    EvidenceSnapshotV1,
    NativeValuationV1,
    QuantitativeMetricV1,
    RecordClaimV1,
    ResearchChallengeV1,
    ResearchHypothesisV1,
    ResearchRecordV1,
    SourceContentV1,
    SourceEvidenceV1,
    VerificationRecordV1,
)
from ._sentiment import (  # noqa: F401  - facade re-export
    SentimentBand,
    SentimentReport,
    render_sentiment_report,
)
from ._verification_plan import (  # noqa: F401 - facade re-export
    FinancialConditionV1,
    FinancialOperandV1,
    MetricConditionV1,
    NumericPredicateV1,
    VerificationPlanV1,
    VerificationTaskV1,
)
