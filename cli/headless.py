"""Versioned JSONL presentation of durable CLI research events."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from tradingagents.observability.events import PersistedEvent


class HeadlessOutput:
    def __init__(self, stream: TextIO):
        self.stream = stream
        self.run_id: str | None = None
        self.failed = False
        self._finished = False

    def emit(self, type_: str, **fields) -> None:
        if self.failed:
            return
        line = json.dumps({"schema_version": 1, "type": type_, **fields}, ensure_ascii=True)
        try:
            if self.stream is sys.__stdout__:
                # Bypass its buffered wrapper so a broken pipe cannot fail a second time at Python shutdown.
                data = memoryview((line + "\n").encode("ascii"))
                while data:
                    written = os.write(self.stream.fileno(), data)
                    if not written:
                        raise OSError("could not write JSONL")
                    data = data[written:]
            else:
                self.stream.write(line + "\n")
                self.stream.flush()
        except OSError:
            # Presentation failure must not unwind an already persisted event or publication.
            self.failed = True

    def event(self, event: PersistedEvent) -> None:
        self.run_id = event.run_id
        # The event payload is not an external CLI contract and may carry research details.
        self.emit(event.type, run_id=event.run_id, sequence=event.sequence,
                  timestamp=event.timestamp, actor_id=event.actor_id, status=event.status)

    def result(self, status: str, **fields) -> None:
        if not self._finished:
            self._finished = True
            self.emit("command.result", status=status, run_id=self.run_id, **fields)
