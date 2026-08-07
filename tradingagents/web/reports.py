"""Compatibility facade: implementation moved to tradingagents.runtime.reports."""

from tradingagents.runtime.reports import (  # noqa: F401  - facade re-export
    REPORT_KIND_PATTERN,
    REVISION_PATTERN,
    Any,
    ArtifactRef,
    FinalReportPublication,
    Path,
    ReportArtifactWriter,
    ReportPublicationError,
    ReportRevision,
    RunStore,
    RunStoreError,
    annotations,
    dataclass,
    utc_timestamp,
    write_report_tree,
)
