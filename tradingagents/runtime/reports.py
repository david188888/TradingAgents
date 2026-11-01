"""Immutable partial reports and atomic canonical final report publication."""

from __future__ import annotations

import hashlib
import html
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingagents.observability.events import ArtifactRef

from .run_models import utc_timestamp
from .store import RunStore, RunStoreError


class ReportPublicationError(RunStoreError):
    pass




@dataclass(frozen=True)
class FinalReportPublication:
    reports_directory: Path
    complete_report: Path
    artifacts: tuple[ArtifactRef, ...]
    published_at: str


class ReportArtifactWriter:
    def __init__(self, store: RunStore):
        self.store = store



    @staticmethod
    def _revision_artifact(
        run_dir: Path,
        destination: Path,
        digest: str,
    ) -> ArtifactRef:
        content = destination.read_bytes()
        return ArtifactRef(
            artifact_id=f"report-revision:{digest}",
            kind="report-revision",
            media_type="text/markdown",
            content_sha256=digest,
            byte_size=len(content),
            locator=destination.relative_to(run_dir).as_posix(),
        )

    def publish_final(self, run_id: str, final_state: dict[str, Any], ticker: str) -> FinalReportPublication:
        value = final_state.get("native_research_record")
        if not isinstance(value, dict) or value.get("schema_version") != "insight-research-v1":
            raise ReportPublicationError("unsupported research report version")
        from tradingagents.runtime.insight_artifacts import read_insight_publication
        record = read_insight_publication(self.store, run_id)
        if record.ticker != ticker or record.model_dump(mode="json") != value:
            raise ReportPublicationError("insight report publication mismatch")
        return self._write_native_content(run_id, build_markdown_from_native_record(record))


    def _write_native_content(self, run_id: str, content: str) -> FinalReportPublication:
        run_dir = self.store._run_dir(run_id)
        reports_dir = run_dir / "reports"
        with self.store.lock_for(run_id):
            if reports_dir.exists():
                existing = reports_dir / "complete_report.md"
                if not existing.is_file() or existing.read_text(encoding="utf-8") != content:
                    raise ReportPublicationError("native report content conflict")
            else:
                temporary = run_dir / f".reports.{uuid.uuid4().hex}.tmp"
                try:
                    temporary.mkdir()
                    (temporary / "complete_report.md").write_text(content, encoding="utf-8")
                    self._fsync_tree(temporary)
                    os.replace(temporary, reports_dir)
                    self.store._fsync_directory(run_dir)
                except Exception:
                    shutil.rmtree(temporary, ignore_errors=True)
                    raise
        return FinalReportPublication(reports_directory=reports_dir,
            complete_report=reports_dir / "complete_report.md",
            artifacts=tuple(self._final_artifacts(run_dir, reports_dir)), published_at=utc_timestamp())



    @staticmethod
    def _fsync_tree(root: Path) -> None:
        directories = []
        for current, _dirnames, filenames in os.walk(root):
            current_path = Path(current)
            directories.append(current_path)
            for filename in filenames:
                with (current_path / filename).open("rb") as handle:
                    os.fsync(handle.fileno())
        for directory in reversed(directories):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    @staticmethod
    def _final_artifacts(run_dir: Path, reports_dir: Path):
        for path in sorted(reports_dir.rglob("*")):
            if not path.is_file():
                continue
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            yield ArtifactRef(
                artifact_id=f"report-final:{digest}",
                kind="report-final",
                media_type="text/markdown",
                content_sha256=digest,
                byte_size=len(content),
                locator=path.relative_to(run_dir).as_posix(),
            )






def build_markdown_from_native_record(record: Any) -> str:
    from tradingagents.research.insight_report import insight_markdown
    return insight_markdown(record)






def _markdown_text(value: str) -> str:
    """Render saved text as inert prose, not executable HTML/Markdown links."""
    value = html.escape(value, quote=False)
    for character in ("\\", "`", "*", "_", "[", "]", "#", "|"):
        value = value.replace(character, "\\" + character)
    return value.replace("\r", " ").replace("\n", " ")
