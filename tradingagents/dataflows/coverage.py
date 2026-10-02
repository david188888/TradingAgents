"""Public requested-versus-observed coverage contracts for data capabilities.

Coverage is provider-owned metadata.  Callers must not infer it later from a
rendered CSV or an analyst report, because a requested range does not prove
that a vendor returned the whole range.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CoverageCompleteness = Literal["complete", "partial", "unknown", "unavailable"]
PriceBasis = Literal["raw", "qfq", "split_dividend_adjusted"]


def _parse_date(value: str, field_name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD") from exc
    if value != parsed.isoformat():
        raise ValueError(f"{field_name} must use YYYY-MM-DD")
    return parsed


class SourceCoverageV1(BaseModel):
    """Coverage reported by one source for one normalized capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(min_length=1, max_length=120)
    source_id: str = Field(min_length=1, max_length=120)
    requested_start: str | None = None
    requested_end: str | None = None
    actual_start: str | None = None
    actual_end: str | None = None
    item_count: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=1)
    pagination_exhausted: bool | None = None
    completeness: CoverageCompleteness
    sources: tuple[str, ...] = Field(min_length=1)
    degradations: tuple[str, ...] = ()
    as_of: str

    @field_validator(
        "requested_start",
        "requested_end",
        "actual_start",
        "actual_end",
        "as_of",
    )
    @classmethod
    def validate_iso_date(cls, value: str | None, info):
        if value is not None:
            _parse_date(value, info.field_name)
        return value

    @model_validator(mode="after")
    def validate_coverage_semantics(self) -> SourceCoverageV1:
        if (self.requested_start is None) != (self.requested_end is None):
            raise ValueError("requested_start and requested_end must be supplied together")
        if (self.actual_start is None) != (self.actual_end is None):
            raise ValueError("actual_start and actual_end must be supplied together")

        if self.requested_start and self.requested_end:
            requested_start = _parse_date(self.requested_start, "requested_start")
            requested_end = _parse_date(self.requested_end, "requested_end")
            if requested_start > requested_end:
                raise ValueError("requested_start cannot be after requested_end")
        else:
            requested_start = requested_end = None

        if self.actual_start and self.actual_end:
            actual_start = _parse_date(self.actual_start, "actual_start")
            actual_end = _parse_date(self.actual_end, "actual_end")
            if actual_start > actual_end:
                raise ValueError("actual_start cannot be after actual_end")
            if requested_start and actual_start < requested_start:
                raise ValueError("actual_start cannot precede the retained requested window")
            if requested_end and actual_end > requested_end:
                raise ValueError("actual_end cannot exceed the retained requested window")

        if self.source_id not in self.sources:
            raise ValueError("sources must include source_id")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources must not contain duplicates")
        if self.page_count is None and self.pagination_exhausted is not None:
            raise ValueError("pagination_exhausted requires page_count")
        if self.completeness == "complete":
            # A payload capability and a screening capability mean different
            # things by "complete".  For a document/payload set, zero retained
            # items is not a usable result; for a screen, "the provider answered
            # the whole query and nothing matched" *is* the result.  Subclasses
            # opt in explicitly; the default keeps the payload rule.
            if self.item_count == 0:
                if not self._allows_complete_without_items():
                    raise ValueError("complete coverage requires at least one retained item")
            elif self._requires_observed_window_for_complete():
                if self.actual_start is None or self.actual_end is None:
                    raise ValueError("complete coverage requires an observed window")
                if self.requested_start and (
                    self.actual_start != self.requested_start
                    or self.actual_end != self.requested_end
                ):
                    raise ValueError("complete coverage must span the full requested window")
            if self.page_count is not None and self.pagination_exhausted is not True:
                raise ValueError("complete paginated coverage requires pagination_exhausted=true")
        elif self.completeness == "unavailable":
            if self.item_count != 0 or self.actual_start is not None:
                raise ValueError("unavailable coverage cannot contain items or an observed window")
            if not self.degradations:
                raise ValueError("unavailable coverage requires a public degradation code")
        elif self.item_count == 0 and not self._allows_zero_usable_items():
            raise ValueError(f"{self.completeness} coverage requires usable retained items")

        return self

    def _allows_zero_usable_items(self) -> bool:
        return False

    def _allows_complete_without_items(self) -> bool:
        """Whether ``complete`` may carry zero retained items.

        Payload capabilities return False: an empty payload is a degradation,
        not coverage.  Screening capabilities override this so that a query the
        provider provably completed with no match is reported as the *fact* it
        is, instead of being collapsed into the same state as a fetch failure.
        """
        return False

    def _requires_observed_window_for_complete(self) -> bool:
        """Whether ``complete`` must name the date window it observed.

        True for window-shaped payload queries.  A screening capability may
        override this: its completeness claim is about the *query*, and the
        adapter re-verifies each returned row against the requested filters,
        which is the stronger guarantee.
        """
        return True


class PriceSeriesCoverageV1(SourceCoverageV1):
    """Coverage plus an explicit, provider-verified adjustment convention."""

    price_basis: PriceBasis
    adjustment_source: str = Field(min_length=1, max_length=160)
    adjustment_verified: bool
    granularity: Literal["daily", "weekly", "monthly"] = "daily"

    @model_validator(mode="after")
    def validate_adjustment(self) -> PriceSeriesCoverageV1:
        if self.price_basis != "raw" and not self.adjustment_verified:
            raise ValueError("adjusted price coverage must verify its adjustment convention")
        return self


class SecDisclosureCoverageV1(SourceCoverageV1):
    """SEC search and document closure without weakening generic coverage."""

    coverage_kind: Literal["sec-disclosure-coverage-v1"] = (
        "sec-disclosure-coverage-v1"
    )
    observed_unit_count: int = Field(ge=0)
    search_complete: bool
    target_filing_count: int = Field(ge=0)
    rejected_target_count: int = Field(ge=0)
    required_document_count: int = Field(ge=0)
    completed_document_count: int = Field(ge=0)

    def _allows_zero_usable_items(self) -> bool:
        return (
            self.item_count == 0
            and (
                (
                    not self.search_complete
                    and self.observed_unit_count > 0
                    and self.completeness == "unknown"
                )
                or (
                    self.search_complete
                    and self.rejected_target_count > 0
                    and self.completeness == "partial"
                )
            )
        )

    @model_validator(mode="after")
    def validate_sec_semantics(self) -> SecDisclosureCoverageV1:
        if self.capability != "official_disclosures":
            raise ValueError("SEC coverage is only valid for official_disclosures")
        if self.completed_document_count > self.required_document_count:
            raise ValueError("completed documents cannot exceed required documents")
        if self.rejected_target_count > self.target_filing_count:
            raise ValueError("rejected targets cannot exceed target filings")
        usable_targets = self.target_filing_count - self.rejected_target_count
        if self.item_count > usable_targets:
            raise ValueError("usable items cannot exceed retained target filings")
        if self.required_document_count > usable_targets:
            raise ValueError("required documents cannot exceed retained target filings")
        if self.target_filing_count > self.observed_unit_count:
            raise ValueError("target filings cannot exceed observed index units")
        if self.search_complete != (self.pagination_exhausted is True):
            raise ValueError("search_complete must match pagination exhaustion")

        if not self.search_complete:
            expected = "partial" if self.item_count else "unknown"
        elif self.rejected_target_count > 0:
            expected = "partial"
        elif self.target_filing_count == 0:
            expected = "unavailable"
        elif (
            self.item_count == usable_targets
            and self.completed_document_count == self.required_document_count
        ):
            expected = "complete"
        else:
            expected = "partial"
        if self.completeness != expected:
            raise ValueError("SEC completeness does not match search and document closure")
        return self


class ScreeningCoverageV1(SourceCoverageV1):
    """Coverage for a provider query whose honest answer may be "nothing matched".

    A screener is not a payload capability.  "This company filed a performance
    forecast inside the window" and "the provider answered the whole window and
    no forecast exists" are *different facts*, and a caller that cannot tell
    them apart will read a throttled vendor as a negative finding.  This
    subclass makes the second fact expressible as ``complete`` with zero items,
    which the base contract deliberately reserves for payload capabilities.

    ``query_complete`` is the load-bearing field: it may only be true when the
    provider's own pagination was exhausted and its self-reported totals were
    reconciled against the rows actually read.  A partial scan, an unknown page
    count, or a truncated result set is ``partial``/``unknown`` and must carry a
    degradation code -- never ``complete``.
    """

    coverage_kind: Literal["screening-coverage-v1"] = "screening-coverage-v1"
    # True only when the provider's pagination was exhausted and its
    # self-reported totals reconciled with the rows actually read.
    query_complete: bool
    # What was screened, in the provider's own terms (ticker, report period,
    # market-wide snapshot, ...).  Recorded because "nothing matched" is only
    # meaningful next to the scope that was searched.
    requested_scope: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_screening_semantics(self) -> ScreeningCoverageV1:
        if self.query_complete != (self.pagination_exhausted is True):
            raise ValueError(
                "query_complete must match proven pagination exhaustion"
            )
        if self.completeness == "complete":
            if not self.query_complete:
                raise ValueError("complete screening coverage requires a completed query")
            if self.degradations:
                raise ValueError(
                    "complete screening coverage cannot carry a degradation; "
                    "a completed query with no match is a fact, not a degradation"
                )
        if self.completeness == "unavailable" and self.query_complete:
            raise ValueError("an unavailable source cannot have completed the query")
        return self

    def _allows_complete_without_items(self) -> bool:
        # Only ``query_complete`` gates the base contract here; the
        # "complete carries no degradation" rule lives in this class's own
        # validator so the failure names the real reason.
        return self.query_complete

    def _requires_observed_window_for_complete(self) -> bool:
        # A screen's completeness is a claim about the query, not about a date
        # window: "the provider answered every page and nothing matched" is
        # complete even though no row exists to bound a window.  Window-shaped
        # screens still record the requested window; adapters additionally
        # re-verify each returned row against the requested filters, which is a
        # stronger guarantee than a window comparison.
        return False

    def _allows_zero_usable_items(self) -> bool:
        # A screen can legitimately match nothing before its pagination budget
        # is spent.  That is not coverage -- the degradation code recorded by
        # the caller is what stops it reading as one.
        return self.item_count == 0 and bool(self.degradations)


class CoveredText(str):
    """A rendered legacy-compatible report carrying typed source coverage."""

    coverage: SourceCoverageV1

    def __new__(cls, value: str, coverage: SourceCoverageV1) -> CoveredText:
        instance = super().__new__(cls, value)
        instance.coverage = coverage
        return instance


class SourceGroupRequirementV1(BaseModel):
    """An explicit any-of source requirement; source IDs remain provider-real."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    minimum_usable: int = Field(gt=0)
    source_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_group(self) -> SourceGroupRequirementV1:
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source group IDs must be unique")
        if self.minimum_usable > len(self.source_ids):
            raise ValueError("minimum_usable cannot exceed source group size")
        return self


def _group_completeness(
    group: SourceGroupRequirementV1,
    by_id: dict[str, SourceCoverageV1],
) -> CoverageCompleteness:
    statuses = [by_id[source_id].completeness for source_id in group.source_ids]
    if sum(status == "complete" for status in statuses) >= group.minimum_usable:
        return "complete"
    usable = [status for status in statuses if status != "unavailable"]
    if len(usable) < group.minimum_usable:
        return "unavailable"
    if "partial" in usable:
        return "partial"
    return "unknown"


def aggregate_bundle_completeness(
    records: Sequence[SourceCoverageV1],
    *,
    required_source_ids: Sequence[str],
    optional_source_ids: Sequence[str],
    required_source_groups: Sequence[SourceGroupRequirementV1] = (),
) -> CoverageCompleteness:
    """Apply the product's deterministic required/optional aggregation rules."""

    by_id = {record.source_id: record for record in records}
    if len(by_id) != len(records):
        raise ValueError("coverage records must have unique source_id values")

    required = tuple(required_source_ids)
    optional = tuple(optional_source_ids)
    grouped = tuple(
        source_id for group in required_source_groups for source_id in group.source_ids
    )
    if len(set(grouped)) != len(grouped):
        raise ValueError("a source ID cannot belong to multiple required groups")
    if set(required) & (set(optional) | set(grouped)) or set(optional) & set(grouped):
        raise ValueError("required, grouped, and optional source IDs must be disjoint")
    declared = set(required) | set(optional) | set(grouped)
    if not declared:
        raise ValueError("a coverage bundle must declare at least one source")
    if declared != set(by_id):
        raise ValueError("coverage records must exactly match declared source IDs")

    required_statuses = [by_id[source_id].completeness for source_id in required]
    required_statuses.extend(
        _group_completeness(group, by_id) for group in required_source_groups
    )
    if required_statuses:
        statuses = required_statuses
        if all(status == "complete" for status in statuses):
            return "complete"
        if all(status == "unavailable" for status in statuses):
            return "unavailable"
        if any(status in {"partial", "unavailable"} for status in statuses):
            return "partial"
        return "unknown"

    statuses = [by_id[source_id].completeness for source_id in optional]
    for status in ("complete", "partial", "unknown", "unavailable"):
        if status in statuses:
            return cast(CoverageCompleteness, status)
    return "unavailable"


CoverageRecordV1 = (
    SecDisclosureCoverageV1 | PriceSeriesCoverageV1 | SourceCoverageV1
)


class BundleCoverageV1(BaseModel):
    """Stable bundle-level coverage retaining every source record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str = Field(min_length=1, max_length=120)
    required_source_ids: tuple[str, ...]
    required_source_groups: tuple[SourceGroupRequirementV1, ...] = ()
    optional_source_ids: tuple[str, ...]
    records: tuple[CoverageRecordV1, ...]
    bundle_completeness: CoverageCompleteness

    @classmethod
    def build(
        cls,
        *,
        capability: str,
        records: Sequence[SourceCoverageV1],
        required_source_ids: Sequence[str],
        optional_source_ids: Sequence[str],
        required_source_groups: Sequence[SourceGroupRequirementV1] = (),
    ) -> BundleCoverageV1:
        completeness = aggregate_bundle_completeness(
            records,
            required_source_ids=required_source_ids,
            optional_source_ids=optional_source_ids,
            required_source_groups=required_source_groups,
        )
        return cls(
            capability=capability,
            required_source_ids=tuple(required_source_ids),
            required_source_groups=tuple(required_source_groups),
            optional_source_ids=tuple(optional_source_ids),
            records=tuple(records),
            bundle_completeness=completeness,
        )

    @model_validator(mode="after")
    def validate_aggregate(self) -> BundleCoverageV1:
        for record in self.records:
            if record.capability != self.capability:
                raise ValueError("all source records must use the bundle capability")
        expected = aggregate_bundle_completeness(
            self.records,
            required_source_ids=self.required_source_ids,
            optional_source_ids=self.optional_source_ids,
            required_source_groups=self.required_source_groups,
        )
        if self.bundle_completeness != expected:
            raise ValueError("bundle_completeness does not match source records")
        return self
