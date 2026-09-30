"""T25: classic routes must not be replaced by the catalyst_v1 workflow.

The full pytest suite's failure set staying at its 14-item baseline
(``docs/superpowers/plans/baseline-pytest-failures.md``) is necessary but not
sufficient for T25: it would stay green even if ``catalyst_v1`` quietly
replaced the classic bull/bear debate, the holding-review route, or the
long-horizon route, as long as nothing *broke* and no existing test happened
to exercise the old path. This file is the behavioural half the plan also
requires (``2026-09-29-catalyst-research-task-plan.md``, T25's acceptance
line): it pins the classic route's actual names and wiring, in the modules
that route requests, so a change that retargets a classic run at catalyst_v1
code -- or quietly drops a role, a mode, or a lens -- fails here even if the
rest of the suite stays green.

Every assertion below was written after reading the real implementation
(``tradingagents/graph/setup.py``, ``tradingagents/observability/roles.py``,
``tradingagents/research/horizon_policy.py``, ``tradingagents/execution/
models.py``, ``tradingagents/execution/runner.py``); none of the names here
are invented. As of this worktree's HEAD, ``catalyst_workflow.py`` is not
imported by any of these modules -- ``run_catalyst_research`` is reachable
only from its own tests -- so today these checks hold trivially. Their job is
to keep holding once that stops being true.
"""

from __future__ import annotations

import inspect
from typing import get_args

from tradingagents.execution.models import (
    LEARNING_MODES,
    AnalysisRequest,
    ResearchMode,
    ResearchProfile,
)
from tradingagents.graph.setup import GraphSetup
from tradingagents.observability.roles import ROLES_BY_ACTOR_ID, ROLES_BY_NODE_ID
from tradingagents.research.horizon_policy import LensId

# ---------------------------------------------------------------------------
# The classic bull/bear debate route
# ---------------------------------------------------------------------------


def _compiled_classic_graph():
    """Compile the classic graph the way ``test_evidence_steward.py`` does.

    ``GraphSetup`` takes no ``research_profile`` argument at all -- it is the
    classic graph, unconditionally. A future change that made it profile-aware
    would itself be visible here as a constructor signature change; until
    then, compiling it is compiling the classic route.
    """

    class _DummyConditional:
        def should_continue_news(self, state):
            return "Msg Clear News"

        def should_continue_debate(self, state):
            return "Research Manager"

        def should_continue_risk_analysis(self, state):
            return "Portfolio Manager"

    graph_setup = GraphSetup(
        None,
        None,
        {"news": lambda state: state},
        _DummyConditional(),
    )
    workflow = graph_setup.setup_graph(["news"])
    return workflow.compile()


def test_the_classic_bull_bear_debate_nodes_are_still_wired() -> None:
    graph = _compiled_classic_graph()
    assert {"Bull Researcher", "Bear Researcher", "Research Manager"} <= set(
        graph.nodes
    )
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    # The debate loop: both researchers route back into themselves/each other
    # and into the manager, and the manager hands off to the portfolio
    # manager -- not to anything catalyst_v1 owns.
    assert ("Research Manager", "Portfolio Manager") in edges


def test_the_classic_graph_setup_module_never_imports_the_catalyst_workflow() -> None:
    """A retargeting would show up as a new import before it shows up as a
    behavioural difference; catching it here is cheaper than catching it
    after a run silently starts calling different code.
    """
    from tradingagents.graph import setup as setup_module

    source = inspect.getsource(setup_module)
    assert "catalyst_workflow" not in source
    assert "run_catalyst_research" not in source


def test_the_executor_does_not_yet_reference_the_catalyst_workflow() -> None:
    """Pins the current, intentionally narrow scope (engineering handoff
    §3's "T24 takes the narrow range" decision): the production executor
    must not silently start routing classic requests at ``catalyst_workflow``
    behind this worktree's back before that wiring is a deliberate, reviewed
    change in its own right.
    """
    from tradingagents.execution import runner as runner_module

    source = inspect.getsource(runner_module)
    assert "catalyst_workflow" not in source
    assert "run_catalyst_research" not in source


# ---------------------------------------------------------------------------
# Holding review and the long-horizon route
# ---------------------------------------------------------------------------


def test_research_mode_still_offers_holding_review_alongside_company_research() -> None:
    assert set(get_args(ResearchMode)) == {"company_research", "holding_review"}
    assert frozenset({"company_research", "holding_review"}) == LEARNING_MODES


def test_research_profile_still_offers_exactly_classic_and_catalyst_v1() -> None:
    assert set(get_args(ResearchProfile)) == {"classic", "catalyst_v1"}


def test_the_long_horizon_value_still_exists_on_the_request() -> None:
    """``horizon`` is an inline ``Literal`` on the dataclass field (postponed
    annotations mean it cannot be resolved through the whole class -- see the
    comment at ``execution/models.py`` on why ``get_type_hints`` is unsafe
    there), so this reads the field's own source rather than guessing at an
    importable alias that does not exist.
    """
    source = inspect.getsource(AnalysisRequest)
    assert 'horizon: Literal["short", "medium", "long"]' in source


def test_the_runner_still_gates_case_assembly_on_the_two_learning_modes() -> None:
    """The holding-review and long-horizon routes do not get a separate
    graph; they share the classic graph and are told apart by ``mode`` at the
    case-assembly boundary (``execution/runner.py``). This is the concrete
    site design routes both through -- if a future change dropped
    ``holding_review`` from that gate, holding-review runs would stop
    producing a research case while every other test stayed green.
    """
    from tradingagents.execution import runner as runner_module

    source = inspect.getsource(runner_module)
    assert '{"company_research", "holding_review"}' in source


# ---------------------------------------------------------------------------
# Old role keys and the lens enum still serve the old profile
# ---------------------------------------------------------------------------


def test_the_classic_role_registry_keys_are_unchanged() -> None:
    for actor_id, node_id in (
        ("researcher.bull", "Bull Researcher"),
        ("researcher.bear", "Bear Researcher"),
        ("manager.research", "Research Manager"),
        ("manager.portfolio", "Portfolio Manager"),
        ("evidence.steward", "Evidence Steward"),
    ):
        assert actor_id in ROLES_BY_ACTOR_ID
        assert ROLES_BY_ACTOR_ID[actor_id].node_id == node_id
        assert node_id in ROLES_BY_NODE_ID


def test_the_horizon_lens_enum_is_unchanged() -> None:
    assert set(get_args(LensId)) == {"market", "fundamentals", "news", "sentiment"}


# ---------------------------------------------------------------------------
# Self-proof that this file's assertions are load-bearing
# ---------------------------------------------------------------------------
#
# ``test_the_classic_role_registry_keys_are_unchanged`` was verified to go red
# by temporarily editing ``tradingagents/observability/roles.py`` (renaming
# the ``"researcher.bull"`` actor_id to ``"researcher.bull_renamed"``),
# re-running this file, observing:
#
#   AssertionError: assert 'researcher.bull' in {'analyst.fundamentals': ...}
#   FAILED tests/test_catalyst_classic_regression.py::
#     test_the_classic_role_registry_keys_are_unchanged
#
# then reverting the edit and confirming ``git status --short`` printed
# nothing for that file. See the T25 section of the delivery report for the
# full command transcript.
