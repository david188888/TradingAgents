"""Deterministic valuation-position decision chain for learning research.

This module owns the arithmetic behind the reader's ``估值定位`` card.  It is
pure: bundles in state are parsed by the assembly layer into the typed inputs
below, and every published number traces back to those inputs plus an explicit
method rule.  No LLM turn may create or mutate any number here; the model may
only narrate a rendered summary (see agents/managers/research_manager.py).

Decision-chain layers and their deterministic rules:

1. inputs      -- verified market snapshot, latest annual earnings base,
                  own multiple history, optional peer valuations.
2. positioning -- current PE/PB percentile inside the ticker's own history
                  (1y and 3y windows), premium/discount vs the peer median,
                  and the price position inside its trailing 52-week range.
3. anchoring   -- each anchor multiplies one disclosed earnings base by one
                  independent multiple band (own-history p25-p75, or peer
                  p25-p75).  Anchors fail closed with reason codes.
4. synthesis   -- available anchors combine into one reference interval;
                  overlapping bands intersect, disjoint bands fall back to the
                  union span plus an explicit disagreement note.
5. verdict     -- last price versus the reference interval produces a
                  below/within/above label with deviation percent.

All ratio observations must carry the same currency and be point-in-time
consistent; values that cannot be validated stay ``unavailable`` instead of
being guessed, mirroring the rest of the research layer.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AssessmentStatus = Literal["available", "partial", "unavailable"]
AnchorStatus = Literal["available", "partial", "unavailable"]
RangePosition = Literal["below_range", "within_range", "above_range", "unavailable"]
BandLabel = Literal[
    "undervalued_band",
    "lower_mid_band",
    "upper_mid_band",
    "elevated_band",
    "not_assessable",
]


def _finite(value: float | int | None) -> bool:
    return value is not None and isinstance(value, (int, float)) and math.isfinite(float(value))


def quantile(values: tuple[float, ...], q: float) -> float | None:
    """Linear-interpolated quantile on pre-cleaned positive multiples."""
    if not values or not 0.0 <= q <= 1.0:
        return None
    ordered = sorted(float(item) for item in values)
    position = q * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def percentile_rank(values: tuple[float, ...], current: float) -> float | None:
    """Midpoint percentile rank (0..100) of ``current`` within clean values."""
    if not values:
        return None
    below = sum(1 for item in values if item < current)
    equal = sum(1 for item in values if item == current)
    return 100.0 * (below + 0.5 * equal) / len(values)


def _clean_positive(values: tuple[float, ...]) -> tuple[tuple[float, ...], int]:
    """Keep finite positive multiples; return them plus the dropped count."""
    kept: list[float] = []
    dropped = 0
    for raw in values:
        if raw is None or not _finite(raw) or float(raw) <= 0.0:
            dropped += 1
            continue
        kept.append(float(raw))
    return tuple(kept), dropped


# ---------------------------------------------------------------------------
# Typed inputs (assembly-layer concern to parse these out of state bundles)
# ---------------------------------------------------------------------------


class ValuationSnapshotInputV1(BaseModel):
    """Verified realtime quote row (Tencent)."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    as_of: date
    price: float | None = None
    pe_ttm: float | None = Field(default=None, ge=0)
    pb: float | None = Field(default=None, ge=0)
    total_market_cap_yi: float | None = Field(default=None, gt=0)


class EarningsBaseV1(BaseModel):
    """One disclosed annual figure used as an anchor's earnings base."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    metric_id: Literal["net_income", "equity"]
    value_yi: float
    period: str = Field(min_length=4, max_length=80)


class DailyMultipleV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    value: float


class PeerValuationsV1(BaseModel):
    """Current peer multiples observed under the same TTM convention."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    entity_ids: tuple[str, ...] = ()
    pe_ttm_values: tuple[float, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> PeerValuationsV1:
        if len(self.entity_ids) != len(self.pe_ttm_values):
            raise ValueError("peer ids and values must align")
        return self


class ValuationInputsV1(BaseModel):
    """Everything the decision chain is allowed to read."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    as_of: date
    snapshot: ValuationSnapshotInputV1 | None = None
    net_income_annual: EarningsBaseV1 | None = None
    equity_annual: EarningsBaseV1 | None = None
    closing_prices: tuple[tuple[date, float], ...] = ()
    pe_history: tuple[DailyMultipleV1, ...] = ()
    pb_history: tuple[DailyMultipleV1, ...] = ()
    peers: PeerValuationsV1 | None = None


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class PercentilePointV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_label: str = Field(min_length=1, max_length=40)
    percentile: float = Field(ge=0, le=100)
    sample_size: int = Field(ge=1)
    excluded_nonpositive: int = Field(default=0, ge=0)
    bucket: BandLabel


def _band(percentile: float) -> BandLabel:
    if percentile < 25.0:
        return "undervalued_band"
    if percentile < 50.0:
        return "lower_mid_band"
    if percentile < 75.0:
        return "upper_mid_band"
    return "elevated_band"


def _history_percentile(
    series: tuple[DailyMultipleV1, ...], current: float | None, days: int
) -> PercentilePointV1 | None:
    if series and current is not None and _finite(current) and float(current) <= 0.0:
        # A nonpositive realtime multiple (loss-making) has no band semantics.
        return None
    if not series or current is None or not _finite(current):
        return None
    cutoff = series[-1].day.toordinal() - days
    window = tuple(item.value for item in series if item.day.toordinal() >= cutoff)
    cleaned, dropped = _clean_positive(window)
    if not cleaned:
        return None
    rank = percentile_rank(cleaned, float(current))
    if rank is None:
        return None
    return PercentilePointV1(
        window_label=f"{days}d",
        percentile=round(rank, 1),
        sample_size=len(cleaned),
        excluded_nonpositive=dropped,
        bucket=_band(rank),
    )


class AnchorOutputV1(BaseModel):
    """One independent multiple-band anchor with full provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    anchor_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    method_label_zh: str = Field(min_length=1, max_length=160)
    multiple_kind: Literal["pe_ttm", "pb_mrq"]
    status: AnchorStatus
    reason_code: str | None = None
    earnings_base: EarningsBaseV1 | None = None
    multiple_low: float | None = Field(default=None, ge=0)
    multiple_high: float | None = Field(default=None, ge=0)
    implied_value_low_yi: float | None = None
    implied_value_high_yi: float | None = None
    per_share_low: float | None = None
    per_share_high: float | None = None
    assumptions: tuple[str, ...] = ()
    invalidation: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _arithmetic(self) -> AnchorOutputV1:
        has_numbers = any(
            item is not None
            for item in (
                self.multiple_low,
                self.implied_value_low_yi,
                self.per_share_low,
            )
        )
        if self.status == "unavailable":
            if has_numbers:
                raise ValueError(f"anchor {self.anchor_id}: unavailable anchors cannot carry numbers")
            return self
        required = (
            self.earnings_base,
            self.multiple_low,
            self.multiple_high,
            self.implied_value_low_yi,
            self.implied_value_high_yi,
        )
        if any(item is None for item in required):
            raise ValueError(f"anchor {self.anchor_id}: {self.status} requires full inputs")
        if not self.multiple_low <= self.multiple_high:
            raise ValueError(f"anchor {self.anchor_id}: multiple band inverted")
        tolerance = max(0.01, abs(self.implied_value_high_yi) * 0.02)
        if not (
            math.isclose(
                self.implied_value_low_yi,
                self.multiple_low * self.earnings_base.value_yi,
                abs_tol=tolerance,
            )
            and math.isclose(
                self.implied_value_high_yi,
                self.multiple_high * self.earnings_base.value_yi,
                abs_tol=tolerance,
            )
        ):
            raise ValueError(f"anchor {self.anchor_id}: implied value != base * band")
        if (
            self.per_share_low is not None
            and self.per_share_high is not None
            and self.per_share_low > self.per_share_high
        ):
            raise ValueError(f"anchor {self.anchor_id}: per-share band inverted")
        return self


class RangeSynthesisV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    status: AssessmentStatus
    reference_low_yi: float | None = None
    reference_high_yi: float | None = None
    per_share_low: float | None = None
    per_share_high: float | None = None
    contributing_anchor_ids: tuple[str, ...] = ()
    disagreement_note_zh: str | None = Field(default=None, max_length=500)
    method_note_zh: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def _interval_shape(self) -> RangeSynthesisV1:
        if self.status != "unavailable":
            if self.reference_low_yi is None or self.reference_high_yi is None:
                raise ValueError("non-unavailable synthesis requires a reference interval")
            if self.reference_low_yi > self.reference_high_yi:
                raise ValueError("synthesis interval inverted")
            if (
                self.per_share_low is not None
                and self.per_share_high is not None
                and self.per_share_low > self.per_share_high
            ):
                raise ValueError("synthesis per-share interval inverted")
        else:
            if not self.contributing_anchor_ids:
                raise ValueError("unavailable synthesis must explain via contributing/absent anchors")
        return self


class PositionVerdictV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    range_position: RangePosition
    deviation_pct: float | None = None
    overall_label_zh: str = Field(min_length=1, max_length=300)
    fact_notes_zh: tuple[str, ...] = ()


class ValuationAssessmentV1(BaseModel):
    """Public, replayable valuation-position artifact for one research run."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["valuation-assessment-v1"] = "valuation-assessment-v1"
    assessment_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$", max_length=200)
    run_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    as_of: date
    created_at_note: str = Field(default="", max_length=80)
    # Echoes of the verified market inputs so the reader card can draw the
    # price cursor without re-parsing bundles.
    current_price: float | None = Field(default=None, gt=0)
    total_market_cap_yi: float | None = Field(default=None, gt=0)
    positions: tuple[PercentilePointV1, ...] = ()
    week52_position: PercentilePointV1 | None = None
    peer_relation: Literal["discount_to_peers", "in_line_with_peers", "premium_to_peers", "not_assessable"] = (
        "not_assessable"
    )
    anchor_outputs: tuple[AnchorOutputV1, ...] = ()
    synthesis: RangeSynthesisV1
    verdict: PositionVerdictV1
    input_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _global_shape(self) -> ValuationAssessmentV1:
        if not self.anchor_outputs and self.synthesis.status != "unavailable":
            raise ValueError("no anchors implies unavailable synthesis")
        return self


# ---------------------------------------------------------------------------
# The decision chain itself
# ---------------------------------------------------------------------------

_MIN_ANCHOR_SAMPLES = 120
_PARTIAL_ANCHOR_SAMPLES = 60


def build_history_anchor(
    anchor_id: str,
    *,
    history: tuple[DailyMultipleV1, ...],
    base: EarningsBaseV1 | None,
    kind: Literal["pe_ttm", "pb_mrq"],
    method_label_zh: str,
    negative_guard_reason: str | None,
    shares_yi: float | None,
    reference_price: float | None,
) -> AnchorOutputV1:
    """Multiply one disclosed annual base by the own-history p25-p75 band."""
    if negative_guard_reason is not None:
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label_zh,
            multiple_kind=kind,
            status="unavailable",
            reason_code=negative_guard_reason,
            assumptions=_assumptions_for(kind),
            invalidation=f"盈利基础变化或市场重估会使该锚失效：{kind} 口径不再适用。",
        )
    cleaned, _dropped = _clean_positive(tuple(item.value for item in history))
    if base is None:
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label_zh,
            multiple_kind=kind,
            status="unavailable",
            reason_code="annual_base_missing",
            assumptions=_assumptions_for(kind),
            invalidation="披露新的年报或修正财务数据后需重算。",
        )
    if len(cleaned) < _MIN_ANCHOR_SAMPLES:
        reason = "insufficient_multiple_history"
        status: AnchorStatus = "unavailable"
        if len(cleaned) >= _PARTIAL_ANCHOR_SAMPLES:
            status = "partial"
            reason = None
    else:
        status = "available"
        reason = None
    if status == "unavailable":
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label_zh,
            multiple_kind=kind,
            status=status,
            reason_code=reason,
            assumptions=_assumptions_for(kind),
            invalidation="补足历史行情或等待新披露后可恢复。",
        )
    low = quantile(cleaned, 0.25)
    high = quantile(cleaned, 0.75)
    assert low is not None and high is not None  # cleaned is non-empty here
    output = AnchorOutputV1(
        anchor_id=anchor_id,
        method_label_zh=method_label_zh,
        multiple_kind=kind,
        status=status,
        earnings_base=base,
        multiple_low=round(low, 2),
        multiple_high=round(high, 2),
        implied_value_low_yi=round(low * base.value_yi, 2),
        implied_value_high_yi=round(high * base.value_yi, 2),
        assumptions=_assumptions_for(kind),
        invalidation=(
            f"若{base.period}之后的年报出现重大变化，或市场长期脱离自身历史分布，该锚失效。"
        ),
    )
    return _with_per_share(output, shares_yi, reference_price)


def build_peer_anchor(
    *,
    peers: PeerValuationsV1 | None,
    base: EarningsBaseV1 | None,
    negative_guard_reason: str | None,
    shares_yi: float | None,
    reference_price: float | None,
) -> AnchorOutputV1:
    """Multiply the disclosed base by the current peer PE-TTM p25-p75 band."""
    anchor_id = "peer_pe_band"
    method_label = "同行市盈率区间（可比公司当前 PE-TTM 分布 × 最新年报净利润）"
    if negative_guard_reason is not None:
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label,
            multiple_kind="pe_ttm",
            status="unavailable",
            reason_code=negative_guard_reason,
            assumptions=("以最新已披露年度净利润为基数，不做预测。",),
            invalidation="扭亏或资产重组后需重新评估。",
        )
    if base is None:
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label,
            multiple_kind="pe_ttm",
            status="unavailable",
            reason_code="annual_base_missing",
            assumptions=("以最新已披露年度净利润为基数。",),
            invalidation="披露新的年报后可重算。",
        )
    if peers is None or not peers.pe_ttm_values:
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label,
            multiple_kind="pe_ttm",
            status="unavailable",
            reason_code="verified_peer_valuations_unavailable",
            assumptions=("要求同行集合与目标公司同口径的实时估值证据。",),
            invalidation="建立经过验证的同行估值观测后可启用。",
        )
    cleaned, _dropped = _clean_positive(peers.pe_ttm_values)
    if len(cleaned) < 3:
        return AnchorOutputV1(
            anchor_id=anchor_id,
            method_label_zh=method_label,
            multiple_kind="pe_ttm",
            status="unavailable",
            reason_code="insufficient_comparable_peers",
            assumptions=("至少需要 3 家同行的当前 PE-TTM 观测。",),
            invalidation="补充同行覆盖后可启用。",
        )
    low = quantile(cleaned, 0.25)
    high = quantile(cleaned, 0.75)
    assert low is not None and high is not None
    output = AnchorOutputV1(
        anchor_id=anchor_id,
        method_label_zh=method_label,
        multiple_kind="pe_ttm",
        status="available" if len(cleaned) >= 5 else "partial",
        earnings_base=base,
        multiple_low=round(low, 2),
        multiple_high=round(high, 2),
        implied_value_low_yi=round(low * base.value_yi, 2),
        implied_value_high_yi=round(high * base.value_yi, 2),
        assumptions=(
            "假设目标公司应获得同行的中位定价水平；未调整个体增速与质量差异。",
            "以最新已披露年度净利润为基数，不做预测。",
        ),
        invalidation="同行集体重估或目标公司基本面相对同行变化时失效。",
    )
    return _with_per_share(output, shares_yi, reference_price)


def _with_per_share(
    output: AnchorOutputV1, shares_yi: float | None, reference_price: float | None
) -> AnchorOutputV1:
    """Attach per-share prices when share count is derivable."""
    if output.implied_value_low_yi is None or output.implied_value_high_yi is None:
        return output
    if shares_yi is None or shares_yi <= 0 or reference_price is None or reference_price <= 0:
        return output
    return output.model_copy(
        update={
            "per_share_low": round(output.implied_value_low_yi / shares_yi, 2),
            "per_share_high": round(output.implied_value_high_yi / shares_yi, 2),
        }
    )


def _assumptions_for(kind: Literal["pe_ttm", "pb_mrq"]) -> tuple[str, ...]:
    if kind == "pe_ttm":
        return (
            "以最新已披露年度净利润为基数，不预测未来增长；市场维持对该公司的历史定价习惯。",
        )
    return (
        "以最新已披露年度净资产为基数（适用于亏损期公司），忽略轻资产业务与账面价值的偏差。",
    )


def synthesize(
    anchors: tuple[AnchorOutputV1, ...],
    *,
    shares_yi: float | None,
    reference_price: float | None,
) -> RangeSynthesisV1:
    """Combine anchor intervals deterministically; fail closed when empty."""
    usable = [item for item in anchors if item.status in {"available", "partial"}]
    usable = [item for item in usable if item.implied_value_low_yi is not None]
    if not usable:
        reasons = ", ".join(
            f"{item.anchor_id}:{item.reason_code or 'n/a'}"
            for item in anchors
        ) or "no_anchor_inputs"
        return RangeSynthesisV1(
            status="unavailable",
            contributing_anchor_ids=tuple(item.anchor_id for item in anchors),
            disagreement_note_zh=f"没有可用锚点（{reasons}），无法给出参考区间。",
            method_note_zh=(
                "合成规则：可用锚点的隐含价值区间取交集；不相交时给出联合跨度并标注分歧。"
                "所有锚均不可用时整体降级为 unavailable，不做任何猜测。"
            ),
        )

    def _sorted_intervals() -> list[tuple[float, float]]:
        return sorted((float(item.implied_value_low_yi), float(item.implied_value_high_yi)) for item in usable)

    intervals = _sorted_intervals()
    union_low = min(interval[0] for interval in intervals)
    union_high = max(interval[1] for interval in intervals)
    intersect_low = max(interval[0] for interval in intervals)
    intersect_high = min(interval[1] for interval in intervals)
    note: str | None = None
    disagreement: str | None = None
    degraded_synthesis = False
    if intersect_low <= intersect_high:
        ref_low, ref_high = intersect_low, intersect_high
        note = f"{len(intervals)} 个锚点存在共同区间。" if len(intervals) > 1 else None
    else:
        ref_low, ref_high = union_low, union_high
        degraded_synthesis = True
        disagreement = (
            f"锚点区间不相交（交集为空），参考区间改用联合跨度 [{union_low:.0f}, {union_high:.0f}] 亿元；"
            "这提示不同方法对该公司适用定价分歧较大，请阅读锚点明细后再使用。"
        )
    note = note or disagreement

    per_low = per_high = None
    if shares_yi is not None and shares_yi > 0 and reference_price is not None and reference_price > 0:
        per_low = round(ref_low / shares_yi, 2)
        per_high = round(ref_high / shares_yi, 2)

    anchor_ids = tuple(item.anchor_id for item in usable)
    method = (
        f"{'+'.join(anchor_ids)}；规则：多锚取交集，空交集回退联合跨度并标注分歧。"
        if len(intervals) > 1
        else f"{anchor_ids[0]}（单锚，未做交叉验证）。"
    )
    all_available = all(item.status == "available" for item in usable)
    synthesis = RangeSynthesisV1(
        status=("available" if all_available and not degraded_synthesis else "partial"),
        reference_low_yi=round(ref_low, 2),
        reference_high_yi=round(ref_high, 2),
        per_share_low=per_low,
        per_share_high=per_high,
        contributing_anchor_ids=anchor_ids,
        disagreement_note_zh=note,
        method_note_zh=(
            f"合成规则：{method} "
            "单锚结果只是单一方法的反推，不是充分估值；所有数值由本 run 的已验证输入确定性推导。"
        ),
    )
    if disagreement is not None:
        synthesis = synthesis.model_copy(update={"disagreement_note_zh": disagreement})
    return synthesis


def judge(
    *,
    synthesis: RangeSynthesisV1,
    positions: tuple[PercentilePointV1, ...],
    week52: PercentilePointV1 | None,
    peer_relation: str,
    current_price: float | None,
    total_market_cap_yi: float | None,
) -> PositionVerdictV1:
    """Compare the last price against the synthesized interval; label buckets."""
    notes: list[str] = []
    cap_ok = total_market_cap_yi is not None and _finite(total_market_cap_yi) and float(total_market_cap_yi) > 0
    price_ok = current_price is not None and _finite(current_price) and float(current_price) > 0
    if (
        synthesis.status == "unavailable"
        or not price_ok
        or not cap_ok
        or synthesis.per_share_low is None
        or synthesis.per_share_high is None
    ):
        reason = ("缺少已验证的总市值或现价，无法把参考区间换算到现价比较。" if synthesis.status != "unavailable" else "")
        return PositionVerdictV1(
            range_position="unavailable",
            overall_label_zh=(reason + "参考区间不可用，暂不能判断价格相对位置。") .strip() or "参考区间不可用，暂不能判断价格相对位置（输入不足，宁缺毋假）。",
            fact_notes_zh=tuple(notes),
        )
    per_low = float(synthesis.per_share_low)
    per_high = float(synthesis.per_share_high)
    price = float(current_price)
    # Rely on the synthesis per-share band; it was derived from the same cap.
    if price < per_low:
        position: RangePosition = "below_range"
        deviation = 100.0 * (price - per_low) / per_low
        headline = f"现价低于参考区间下沿（较下沿低约 {abs(deviation):.1f}%）。"
    elif price > per_high:
        position = "above_range"
        deviation = 100.0 * (price - per_high) / per_high
        headline = f"现价高于参考区间上沿（较上沿高约 {deviation:.1f}%）。"
    else:
        position = "within_range"
        span_mid = (per_low + per_high) / 2.0
        deviation = 100.0 * (price - span_mid) / span_mid
        headline = f"现价处于参考区间之内（位于区间中位附近 {deviation:+.1f}%）。"
    if week52 is not None:
        third = (
            "52周低位段"
            if week52.percentile < 33.3
            else "52周高位段" if week52.percentile >= 66.7 else "52周中段"
        )
        notes.append(
            f"现价位于自身 52 周收盘分布的第 {week52.percentile:.0f} 百分位（{third}）。"
        )
    label_parts = [headline.strip()]
    if peer_relation != "not_assessable":
        mapping = {
            "discount_to_peers": "显著低于同行估值水平",
            "in_line_with_peers": "与同行估值大体一致",
            "premium_to_peers": "显著高于同行估值水平",
        }
        if peer_relation in mapping:
            label_parts.append(mapping[peer_relation])
    return PositionVerdictV1(
        range_position=position,
        deviation_pct=round(deviation, 1),
        overall_label_zh="；".join(label_parts),
        fact_notes_zh=tuple(notes),
    )


def shares_from_cap(*, cap: float, price: float) -> float:
    """Derive share count in 亿股 from 总市值(亿元)/股价(元)."""
    if cap <= 0 or price <= 0:
        raise ValueError("cap and price must be positive")
    return cap / price


def assess_valuation(inputs: ValuationInputsV1) -> ValuationAssessmentV1:
    """Run the full deterministic chain; never raises on sparse evidence."""
    pe_series = tuple(sorted(inputs.pe_history, key=lambda item: item.day))
    pb_series = tuple(sorted(inputs.pb_history, key=lambda item: item.day))
    prices = tuple(sorted(inputs.closing_prices, key=lambda item: item[0]))
    input_reasons: list[str] = []
    if inputs.snapshot is None:
        input_reasons.append("market_snapshot_unavailable")
    if inputs.net_income_annual is None:
        input_reasons.append("annual_net_income_unavailable")

    snapshot = inputs.snapshot
    price = snapshot.price if snapshot is not None and _finite(snapshot.price) and snapshot.price and snapshot.price > 0 else None
    cap = snapshot.total_market_cap_yi if snapshot is not None else None
    shares_yi = None
    if price is not None and cap is not None and cap > 0:
        shares_yi = shares_from_cap(cap=cap, price=price)

    net_income = inputs.net_income_annual
    equity = inputs.equity_annual
    pe_guard = None
    if net_income is not None and net_income.value_yi <= 0:
        pe_guard = "negative_or_zero_net_income"
    pb_guard = None
    if equity is not None and equity.value_yi <= 0:
        pb_guard = "negative_or_zero_equity"

    history_pe_anchor = build_history_anchor(
        "history_pe_band",
        history=pe_series,
        base=net_income,
        kind="pe_ttm",
        method_label_zh="自身历史市盈率区间（近 3 年 PE-TTM 分布 × 最新年报净利润）",
        negative_guard_reason=pe_guard,
        shares_yi=shares_yi,
        reference_price=price,
    )
    fallback_pb: AnchorOutputV1 | None = None
    if history_pe_anchor.status == "unavailable" and pe_guard is not None:
        fallback_pb = build_history_anchor(
            "history_pb_band",
            history=pb_series,
            base=equity,
            kind="pb_mrq",
            method_label_zh="自身历史市净率区间（近 3 年 PB-MRQ 分布 × 最新年报净资产；亏损期兜底）",
            negative_guard_reason=pb_guard,
            shares_yi=shares_yi,
            reference_price=price,
        )
    peer_anchor = build_peer_anchor(
        peers=inputs.peers,
        base=net_income,
        negative_guard_reason=pe_guard,
        shares_yi=shares_yi,
        reference_price=price,
    )

    anchors: list[AnchorOutputV1] = [history_pe_anchor]
    if fallback_pb is not None:
        anchors.append(fallback_pb)
    anchors.append(peer_anchor)

    synthesis = synthesize(tuple(anchors), shares_yi=shares_yi, reference_price=price)

    positions: list[PercentilePointV1] = []
    if snapshot is not None:
        # Calendar-day windows: ~1 year (365d) and ~3 years (1095d).  Labels
        # carry the calendar meaning so the brief/UI never claim trading years.
        for series, current, label in (
            (pe_series, snapshot.pe_ttm, "pe"),
            (pb_series, snapshot.pb, "pb"),
        ):
            point = _history_percentile(series, current, days=1095)
            if point is not None:
                positions.append(point.model_copy(update={"window_label": f"{label}_3y"}))
                one_year = _history_percentile(series, current, days=365)
                if one_year is not None:
                    positions.append(one_year.model_copy(update={"window_label": f"{label}_1y"}))

    week52 = _week52_position(prices, price)

    peer_relation = "not_assessable"
    if snapshot is not None and inputs.peers is not None:
        cleaned_peers, _ = _clean_positive(inputs.peers.pe_ttm_values)
        if cleaned_peers and snapshot.pe_ttm and snapshot.pe_ttm > 0:
            median_peer = quantile(cleaned_peers, 0.5)
            if median_peer is not None and median_peer > 0:
                premium_pct = 100.0 * (snapshot.pe_ttm - median_peer) / median_peer
                if premium_pct <= -10.0:
                    peer_relation = "discount_to_peers"
                elif premium_pct >= 10.0:
                    peer_relation = "premium_to_peers"
                else:
                    peer_relation = "in_line_with_peers"

    verdict = judge(
        synthesis=synthesis,
        positions=tuple(positions),
        week52=week52,
        peer_relation=peer_relation,
        current_price=price,
        total_market_cap_yi=cap,
    )

    has_usable = synthesis.status != "unavailable"
    status: AssessmentStatus = synthesis.status
    if has_usable and (snapshot is None or week52 is None):
        status = "partial" if status == "available" else status

    return ValuationAssessmentV1(
        assessment_id=f"valuation:{inputs.run_id.casefold()}:{inputs.as_of.isoformat()}",
        run_id=inputs.run_id,
        ticker=inputs.ticker,
        as_of=inputs.as_of,
        current_price=price,
        total_market_cap_yi=cap,
        positions=tuple(positions),
        week52_position=week52,
        peer_relation=peer_relation,
        anchor_outputs=tuple(anchors),
        synthesis=synthesis,
        verdict=verdict,
        input_reasons=tuple(input_reasons),
    )


def _week52_position(
    closing_prices: tuple[tuple[date, float], ...], current_price: float | None
) -> PercentilePointV1 | None:
    if not closing_prices or current_price is None or not _finite(current_price) or current_price <= 0:
        return None
    ordered = sorted(closing_prices, key=lambda item: item[0])
    cutoff = ordered[-1][0].toordinal() - 366
    window = [float(value) for day, value in ordered if day.toordinal() >= cutoff and _finite(value) and value > 0]
    if not window:
        return None
    rank = percentile_rank(tuple(window), float(current_price))
    if rank is None:
        return None
    return PercentilePointV1(
        window_label="52w_price",
        percentile=round(rank, 1),
        sample_size=len(window),
        excluded_nonpositive=0,
        bucket=_band(rank),
    )


_BAND_ZH = {
    "undervalued_band": "低位带",
    "lower_mid_band": "中低带",
    "upper_mid_band": "中高带",
    "elevated_band": "高位带",
}

_ANCHOR_STATUS_ZH = {"available": "可用", "partial": "部分可用", "unavailable": "不可用"}


def render_valuation_brief(assessment: ValuationAssessmentV1) -> str:
    """Render the assessment as a read-only Chinese brief for LLM prompts.

    The brief carries computed numbers with their method labels so downstream
    agents can narrate consistently; it explicitly forbids rewriting values.
    """
    lines: list[str] = []
    verdict = assessment.verdict
    lines.append(f"综合判断：{verdict.overall_label_zh}")
    positions_by_label = {item.window_label: item for item in assessment.positions}
    label_zh = {"pe_1y": "PE 近1年", "pe_3y": "PE 近3年", "pb_1y": "PB 近1年", "pb_3y": "PB 近3年"}
    for key in ("pe_3y", "pe_1y", "pb_3y", "pb_1y"):
        point = positions_by_label.get(key)
        if point is not None:
            zh = label_zh.get(key, key)
            lines.append(
                f"{zh}分位：第 {point.percentile:.0f} 百分位（{_BAND_ZH[point.bucket]}，样本 {point.sample_size} 日）。"
            )
    if assessment.week52_position is not None:
        week = assessment.week52_position
        lines.append(
            f"价格位置：现价位于 52 周收盘分布第 {week.percentile:.0f} 百分位（{_BAND_ZH[week.bucket]}）。"
        )
    relation_zh = {
        "discount_to_peers": "较同行显著折价",
        "in_line_with_peers": "与同行大体一致",
        "premium_to_peers": "较同行显著溢价",
    }
    if assessment.peer_relation != "not_assessable":
        lines.append(f"同行相对关系：{relation_zh[assessment.peer_relation]}。")
    for anchor in assessment.anchor_outputs:
        status = _ANCHOR_STATUS_ZH[anchor.status]
        head = f"锚点[{anchor.anchor_id}]（{status}）：{anchor.method_label_zh}"
        if anchor.status == "unavailable":
            lines.append(f"{head}；原因：{anchor.reason_code or 'unknown'}。")
            continue
        base = anchor.earnings_base
        band = f"倍数带 {anchor.multiple_low}-{anchor.multiple_high} × 基数 {base.value_yi:g} 亿元（{base.period}" + (
            f"，{base.metric_id}" if base.metric_id != "net_income" else "，最新年报净利"
        ) + "）"
        implied = f"隐含市值 {anchor.implied_value_low_yi}-{anchor.implied_value_high_yi} 亿元"
        per_share = (
            f"（约 {anchor.per_share_low}-{anchor.per_share_high} 元/股）"
            if anchor.per_share_low is not None and anchor.per_share_high is not None
            else ""
        )
        lines.append(f"{head}：{band} → {implied}{per_share}。")
    synth = assessment.synthesis
    if synth.status == "unavailable":
        lines.append(f"参考区间：不可用。{synth.disagreement_note_zh or ''}")
    else:
        interval = f"参考区间：{synthesis_per_share_text(synth)}"
        lines.append(interval)
        if synth.disagreement_note_zh:
            lines.append(synth.disagreement_note_zh)
        lines.append(f"合成方法：{synth.method_note_zh}")
    return "\n".join(lines)


def synthesis_per_share_text(synthesis: RangeSynthesisV1) -> str:
    """One-line Chinese description of the synthesized reference interval."""
    cap_range = f"市值 {synthesis.reference_low_yi:g}-{synthesis.reference_high_yi:g} 亿元"
    if synthesis.per_share_low is not None and synthesis.per_share_high is not None:
        return (
            f"每股约 {synthesis.per_share_low:g}-{synthesis.per_share_high:g} 元"
            f"（{cap_range}）；现价相对位置：见综合判断。"
        )
    return f"{cap_range}（缺少已验证股本换算，未折算每股）。"
