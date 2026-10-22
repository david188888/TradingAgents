"""Explicit development-only capture of rejected synthesis final text.

Nothing here enters a checkpoint, event, public diagnostic or provider config.
The fixed output/ directory is ignored by Git. Never serialize response objects:
they may carry credentials, request metadata or model reasoning blocks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

DEBUG_DIRECTORY = Path(__file__).resolve().parents[2] / "output" / "v8-synthesis-debug"
_RUN_ID = re.compile(r"run_[A-Za-z0-9_]+\Z")


def capture_synthesis_failure(run_id: str, stage: str, phase: str, response) -> Path | None:
    if os.environ.get("TRADINGAGENTS_DEBUG_SYNTHESIS_RESPONSES") != "1" or stage != "synthesis":
        return None
    if not _RUN_ID.fullmatch(run_id) or phase not in {"main", "repair"}:
        return None
    content = getattr(response, "content", None)
    if isinstance(content, list):
        content = "\n".join(item if isinstance(item, str) else item.get("text", "")
                            for item in content if isinstance(item, str)
                            or isinstance(item, dict) and item.get("type") == "text"
                            and isinstance(item.get("text"), str))
    if not isinstance(content, str):
        return None
    try:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        payload = {"schema_version": "synthesis-debug-response-v1", "run_id": run_id,
                   "stage": stage, "phase": phase, "response_sha256": digest, "response_text": content}
        directory = DEBUG_DIRECTORY / run_id
        if DEBUG_DIRECTORY.is_symlink() or directory.is_symlink():
            return None
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        destination = directory / (phase + "-" + digest + ".json")
        try:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return destination
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return destination
    except (OSError, UnicodeError):
        # Debugging must never change a research outcome or expose raw errors.
        logging.getLogger(__name__).warning("native synthesis debug capture unavailable")
        return None
