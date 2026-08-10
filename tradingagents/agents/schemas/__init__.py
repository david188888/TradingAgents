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

from ._common import (  # noqa: F401  - facade re-export
    _NULLISH_FLOAT,
    ModelClaimInput,
    PortfolioRating,
    TraderAction,
    _coerce_optional_float,
)
from ._learning_research import (
    HoldingThesisAssessment,
    LearningResearchSummary,
    render_learning_research_summary,
)
from ._portfolio import (  # noqa: F401  - facade re-export
    DecisionDriver,
    PortfolioDecision,
    PortfolioReaderFields,
    render_pm_decision,
)
from ._research import (  # noqa: F401  - facade re-export
    ResearchDelegationTask,
    ResearchPlan,
    ResearchPublicDigest,
    ResearchStrategySignal,
    render_research_plan,
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
from ._risk import (  # noqa: F401  - facade re-export
    RiskDebateSignal,
)
from ._sentiment import (  # noqa: F401  - facade re-export
    SentimentBand,
    SentimentReport,
    render_sentiment_report,
)
from ._trader import (  # noqa: F401  - facade re-export
    TraderProposal,
    render_trader_proposal,
)
