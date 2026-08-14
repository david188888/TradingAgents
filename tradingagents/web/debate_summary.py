"""Post-completion debate summary projection.

After a run terminalizes as completed, a background pass reads the committed
turn output artifacts (the same business_delta payloads the frontend already
parses in responseExtractor.ts) and asks the *quick* LLM for a compact
index of the research/risk debates: per-round topics, one-line summaries,
keywords, per-lane summaries, and estimated bull/bear conviction.

The summary is an index, never a verdict substitute:
- it uses the run's configured ``quick_think_llm`` (cheap, fast), never a new
  hard-coded model name;
- every LLM failure is swallowed and logged — a missing summary only changes
  what the L2 cards show, while L3 always has the full turn text;
- conviction values for the research debate are LLM *estimates* and the
  schema/JSON mark them as such (risk debate conviction stays a real typed
  measurement surfaced via the reader brief).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Literal

from pydantic import BaseModel, Field

from tradingagents.observability.events import PersistedEvent
from tradingagents.web.run_models import RunSnapshot
from tradingagents.web.store import RunStore

LOGGER = logging.getLogger(__name__)

DEBATE_SUMMARY_LOCATOR = "projections/debate-summary-v1.json"
SCHEMA_VERSION = 1

_RESEARCH_LANES: tuple[tuple[str, str], ...] = (
    ("researcher.bull", "bull"),
    ("researcher.bear", "bear"),
)
_RISK_LANES: tuple[tuple[str, str], ...] = (
    ("risk.aggressive", "aggressive"),
    ("risk.neutral", "neutral"),
    ("risk.conservative", "conservative"),
)
_RESPONSE_PATHS: dict[str, tuple[str, ...]] = {
    "researcher.bull": ("investment_debate_state", "current_response"),
    "researcher.bear": ("investment_debate_state", "current_response"),
    "manager.research": ("investment_debate_state", "judge_decision"),
    "trader": ("trader_investment_plan",),
    "risk.aggressive": ("risk_debate_state", "current_aggressive_response"),
    "risk.neutral": ("risk_debate_state", "current_neutral_response"),
    "risk.conservative": ("risk_debate_state", "current_conservative_response"),
    "manager.portfolio": ("final_trade_decision",),
}

_generation_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


# ---------------------------------------------------------------------------
# Typed LLM output
# ---------------------------------------------------------------------------


class ResearchRoundSummary(BaseModel):
    round_index: int = Field(ge=1)
    topic: str = Field(max_length=40)
    summary: str = Field(max_length=240)
    keywords: list[str] = Field(default_factory=list)
    bull_summary: str = Field(default="", max_length=200)
    bear_summary: str = Field(default="", max_length=200)
    # LLM estimate only — bull/bear researchers emit free text, so this is not
    # a typed signal. Surfaced in the UI with an explicit "摘要估计" marker.
    bull_estimated_conviction: float | None = Field(default=None, ge=0.0, le=1.0)
    bear_estimated_conviction: float | None = Field(default=None, ge=0.0, le=1.0)


class RiskRoundSummary(BaseModel):
    round_index: int = Field(ge=1)
    topic: str = Field(max_length=40)
    summary: str = Field(max_length=240)
    keywords: list[str] = Field(default_factory=list)
    aggressive_summary: str = Field(default="", max_length=200)
    neutral_summary: str = Field(default="", max_length=200)
    conservative_summary: str = Field(default="", max_length=200)


class DebateSummaryArtifact(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    generated_at: str
    model: str
    global_summary: str = Field(max_length=160)
    research_debate: list[ResearchRoundSummary] = Field(default_factory=list)
    risk_debate: list[RiskRoundSummary] = Field(default_factory=list)


# Deterministic per-round source references, merged into the projection after
# the LLM call (never sent to the model): lane -> output artifact_id. These let
# L3 load the exact business_delta that was summarized.
ResearchSources = dict[str, dict[str, str]]
RiskSources = dict[str, dict[str, str]]


# ---------------------------------------------------------------------------
# Round reconstruction from committed turn output artifacts
# ---------------------------------------------------------------------------


def _read_path(payload: Any, path: tuple[str, ...]) -> str | None:
    cursor: Any = payload
    for part in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor if isinstance(cursor, str) and cursor.strip() else None


def _turn_texts(
    store: RunStore,
    run_id: str,
    events: list[PersistedEvent],
    actor_ids: set[str],
) -> dict[str, list[dict[str, str]]]:
    """Return ordered per-actor (text, artifact_id) from turn.output_ready events.

    The artifact id is recorded alongside the text so the L3 reader can load
    the exact same business_delta the LLM summarized, rather than re-parsing
    concatenated debate histories.
    """
    out: dict[str, list[dict[str, str]]] = {actor_id: [] for actor_id in actor_ids}
    for event in events:
        if event.type != "turn.output_ready" or event.actor_id not in actor_ids:
            continue
        artifact_id = event.payload.get("artifact_id")
        path = _RESPONSE_PATHS.get(event.actor_id)
        if not isinstance(artifact_id, str) or path is None:
            continue
        try:
            raw = store.read_artifact(run_id, artifact_id)
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError):
            continue
        text = _read_path(payload, path)
        if text:
            out[event.actor_id].append({"text": text, "artifact_id": artifact_id})
    return out


def _rounds_from_lanes(
    texts: dict[str, list[dict[str, str]]],
    lanes: tuple[tuple[str, str], ...],
) -> list[dict[str, dict[str, str]]]:
    """Pair the Nth occurrence of each lane into round N (same order as graph)."""
    round_count = max((len(texts.get(actor_id, ())) for actor_id, _ in lanes), default=0)
    rounds: list[dict[str, dict[str, str]]] = []
    for index in range(round_count):
        lane_entries: dict[str, dict[str, str]] = {}
        for actor_id, lane in lanes:
            sequence = texts.get(actor_id, ())
            if index < len(sequence):
                lane_entries[lane] = sequence[index]
        if lane_entries:
            lane_entries["round_index"] = str(index + 1)
            rounds.append(lane_entries)
    return rounds


def reconstruct_debate(
    store: RunStore, run_id: str, events: list[PersistedEvent]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], list[ResearchSources], list[RiskSources]]:
    """Rebuild research/risk rounds and verdict texts from committed artifacts.

    Mirrors the frontend's debateScript/responseExtractor pairing: events are
    already append-ordered, so the Nth bull text and Nth bear text form round N.
    Returns per-round lane entries ({"text", "artifact_id"}), verdicts, and
    source maps keyed by round_index for the L3 reader.
    """
    actors = {actor_id for actor_id, _ in _RESEARCH_LANES + _RISK_LANES}
    actors.update({"manager.research", "trader", "manager.portfolio"})
    texts = _turn_texts(store, run_id, events, actors)
    research_rounds = _rounds_from_lanes(texts, _RESEARCH_LANES)
    risk_rounds = _rounds_from_lanes(texts, _RISK_LANES)

    research_sources: list[ResearchSources] = []
    for item in research_rounds:
        idx = item["round_index"]
        sources: ResearchSources = {"round_index": idx}
        for lane in ("bull", "bear"):
            if lane in item:
                sources[lane] = item[lane]["artifact_id"]
        research_sources.append(sources)

    risk_sources: list[RiskSources] = []
    for item in risk_rounds:
        idx = item["round_index"]
        sources: RiskSources = {"round_index": idx}
        for lane in ("aggressive", "neutral", "conservative"):
            if lane in item:
                sources[lane] = item[lane]["artifact_id"]
        risk_sources.append(sources)

    verdicts = {
        "research_manager": texts["manager.research"][-1]["text"] if texts.get("manager.research") else "",
        "trader": texts["trader"][-1]["text"] if texts.get("trader") else "",
        "portfolio_manager": texts["manager.portfolio"][-1]["text"] if texts.get("manager.portfolio") else "",
    }
    return research_rounds, risk_rounds, verdicts, research_sources, risk_sources


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _build_prompt(
    snapshot: RunSnapshot,
    research_rounds: list[dict[str, Any]],
    risk_rounds: list[dict[str, Any]],
    verdicts: dict[str, str],
) -> str:
    lane_labels = {"bull": "多方", "bear": "空方", "aggressive": "激进",
                   "neutral": "中性", "conservative": "保守"}

    def render_rounds(rounds: list[dict[str, Any]], lanes: tuple[str, ...]) -> str:
        blocks = []
        for item in rounds:
            lines = [f"### 第 {item['round_index']} 轮"]
            for lane in lanes:
                entry = item.get(lane)
                if isinstance(entry, dict):
                    lines.append(f"{lane_labels[lane]}：{entry['text']}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) if blocks else "（无辩论轮次）"

    return f"""你是交易研究辩论的阅读索引编辑。请为下面的多空研究辩论和风险辩论生成结构化摘要。

规则：
1. 摘要只做信息压缩，不做价值判断；保留有争议的判断和关键数据，去掉修饰语。
2. 每条摘要 1-2 句；如果某轮双方分歧明显，写得稍详细；立场一致则一句话带过。
3. 关键词 3-5 个简短词组。
4. bull_estimated_conviction / bear_estimated_conviction 是你对该轮该方立场强度（0-1）的估计，
   不是类型化测量值；无法判断时填 null。
5. 输出必须符合指定的 JSON schema。

标的：{snapshot.ticker}
研究经理最终裁决：{verdicts['research_manager'] or '（缺失）'}
交易员计划：{verdicts['trader'] or '（缺失）'}
组合经理最终决策：{verdicts['portfolio_manager'] or '（缺失）'}

## 研究辩论
{render_rounds(research_rounds, ("bull", "bear"))}

## 风险辩论
{render_rounds(risk_rounds, ("aggressive", "neutral", "conservative"))}
"""


def _generate_llm_summary(
    snapshot: RunSnapshot,
    research_rounds: list[dict[str, str]],
    risk_rounds: list[dict[str, str]],
    verdicts: dict[str, str],
    *,
    generated_at: str,
) -> DebateSummaryArtifact | None:
    if not research_rounds and not risk_rounds:
        return None
    try:
        from tradingagents.llm_clients import create_llm_client
    except ImportError:
        LOGGER.warning("debate summary: LLM client factory unavailable")
        return None

    prompt = _build_prompt(snapshot, research_rounds, risk_rounds, verdicts)
    try:
        client = create_llm_client(
            provider=snapshot.llm_provider,
            model=snapshot.quick_think_llm,
        )
        llm = client.get_llm()
        structured_llm = llm.with_structured_output(DebateSummaryArtifact)
        result = structured_llm.invoke(prompt)
    except Exception as exc:  # noqa: BLE001 - summary must never change run outcome
        LOGGER.warning("debate summary generation failed for %s: %s", snapshot.run_id, exc)
        try:
            correction = (
                prompt
                + "\n\n上一次输出未通过 DebateSummaryArtifact schema，错误如下："
                + str(exc)
                + "\n请修正所有 validation error；同时确保 global_summary <=160，研究/风险每轮 summary <=240，lane summary <=200，关键词使用短词组。只返回完整合法对象。"
            )
            result = structured_llm.invoke(correction)
        except Exception as retry_exc:  # noqa: BLE001 - optional recovery path
            LOGGER.warning("debate summary correction failed for %s: %s", snapshot.run_id, retry_exc)
            return None

    if not isinstance(result, DebateSummaryArtifact):
        LOGGER.warning("debate summary: LLM returned %s, expected DebateSummaryArtifact", type(result))
        return None

    # The LLM cannot be trusted to echo run identity fields correctly; overwrite.
    return result.model_copy(
        update={
            "schema_version": SCHEMA_VERSION,
            "run_id": snapshot.run_id,
            "generated_at": generated_at,
            "model": snapshot.quick_think_llm,
        }
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _lock_for(run_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _generation_locks.get(run_id)
        if lock is None:
            lock = threading.Lock()
            _generation_locks[run_id] = lock
        return lock


def ensure_debate_summary(
    store: RunStore,
    run_id: str,
    *,
    snapshot: RunSnapshot | None = None,
    events: list[PersistedEvent] | None = None,
) -> dict[str, Any] | None:
    """Generate the debate summary if absent; never raises.

    Returns the materialized JSON dict, or None when unavailable. The LLM call
    runs without the store lock held; the file write takes the per-run lock so
    a background generation and a lazy read cannot write twice.
    """
    current = snapshot or store.read_snapshot(run_id)
    if current.status != "completed":
        return None
    try:
        existing = store.read_fixed_json(run_id, DEBATE_SUMMARY_LOCATOR)
    except Exception:  # noqa: BLE001
        existing = None
    if existing:
        return existing

    lock = _lock_for(run_id)
    if not lock.acquire(blocking=False):
        # Another thread/path is already generating this run's summary.
        return None
    try:
        try:
            existing = store.read_fixed_json(run_id, DEBATE_SUMMARY_LOCATOR)
        except Exception:  # noqa: BLE001
            existing = None
        if existing:
            return existing

        run_events = events if events is not None else store.read_events(run_id)
        research_rounds, risk_rounds, verdicts, research_sources, risk_sources = (
            reconstruct_debate(store, run_id, run_events)
        )
        from tradingagents.web.run_models import utc_timestamp

        artifact = _generate_llm_summary(
            current,
            research_rounds,
            risk_rounds,
            verdicts,
            generated_at=utc_timestamp(),
        )
        if artifact is None:
            return None
        value = artifact.model_dump(mode="json")
        # Merge deterministic source references (never produced by the LLM).
        # Pair by list position; a round the LLM omitted or hallucinated simply
        # has no source map rather than failing the whole projection.
        for item, sources in zip(value["research_debate"], research_sources, strict=False):
            item["sources"] = {k: v for k, v in sources.items() if k != "round_index"}
        for item, sources in zip(value["risk_debate"], risk_sources, strict=False):
            item["sources"] = {k: v for k, v in sources.items() if k != "round_index"}
        store.write_fixed_json(run_id, DEBATE_SUMMARY_LOCATOR, value)
        return value
    except Exception as exc:  # noqa: BLE001 - projection failure is never terminal
        LOGGER.warning("debate summary ensure failed for %s: %s", run_id, exc)
        return None
    finally:
        lock.release()


def schedule_debate_summary(store: RunStore, run_id: str) -> None:
    """Fire-and-forget daemon generation after run.completed.

    The terminal event must already be published before this is called, so the
    SSE stream is never blocked by an LLM round-trip. The view cache is
    republished once the summary lands so the next GET sees it inline; a
    missing summary still degrades silently.
    """

    def _work() -> None:
        try:
            value = ensure_debate_summary(store, run_id)
            if value is None:
                return
            from .projections import RunProjectionPublisher

            RunProjectionPublisher(store).publish_view(run_id)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("debate summary background task failed for %s: %s", run_id, exc)

    thread = threading.Thread(
        target=_work,
        name=f"debate-summary-{run_id}",
        daemon=True,
    )
    thread.start()
