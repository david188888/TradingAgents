"""Durable append-only store for public research conversations.

The store is intentionally separate from :class:`RunStore`'s event log. It
reuses the run root and per-run lock, but cannot append events, mutate a run
snapshot, or persist private model context.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tradingagents.runtime.run_models import validate_run_id

if TYPE_CHECKING:
    from tradingagents.runtime.store import RunStore

from .conversation_models import THREAD_ID_PATTERN, ConversationMessageV1, ConversationThreadV1


def _canonical_record_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class ConversationStoreError(RuntimeError):
    pass


class ConversationStoreCorruption(ConversationStoreError):
    pass


class ThreadAlreadyExists(ConversationStoreError):
    pass


class ThreadNotFound(ConversationStoreError):
    pass


class ConversationConflict(ConversationStoreError):
    pass


class ConversationStore:
    """Store one validated thread per append-only JSONL file.

    Locks protect concurrent requests in one Python process. The existing
    filesystem protocol has no cross-process advisory lock, so deployments
    with multiple workers must provide a single writer or an external lock.
    """

    def __init__(self, root: str | Path | None = None, *, run_store: RunStore | None = None):
        if run_store is not None:
            self.run_store = run_store
            self.root = run_store.root
        else:
            self.root = Path(root or Path.home() / ".tradingagents" / "web" / "runs")
            self.root.mkdir(parents=True, exist_ok=True)
            from tradingagents.runtime.store import RunStore

            self.run_store = RunStore(self.root)
        self._locks_guard = threading.Lock()
        self._thread_locks: dict[tuple[str, str], threading.RLock] = {}

    def _lock_for(self, run_id: str, thread_id: str) -> threading.RLock:
        key = (run_id, thread_id)
        with self._locks_guard:
            return self._thread_locks.setdefault(key, threading.RLock())

    def _thread_path(self, run_id: str, thread_id: str, *, must_exist: bool = True) -> Path:
        try:
            validate_run_id(run_id)
        except ValueError as exc:
            raise ThreadNotFound(run_id) from exc
        if not isinstance(thread_id, str) or not THREAD_ID_PATTERN.fullmatch(thread_id):
            raise ThreadNotFound(thread_id)
        run_dir = self.root / run_id
        path = run_dir / "conversations" / f"{thread_id}.jsonl"
        if path.parent.parent.resolve() != run_dir.resolve():
            raise ConversationStoreError("conversation path escapes run directory")
        if must_exist and not path.is_file():
            raise ThreadNotFound(thread_id)
        return path

    def _assert_run(self, run_id: str) -> None:
        try:
            self.run_store.read_snapshot(run_id)
        except Exception as exc:
            raise ConversationStoreError(f"run is not readable: {run_id}") from exc

    def create_thread(self, thread: ConversationThreadV1) -> ConversationThreadV1:
        self._assert_run(thread.run_id)
        path = self._thread_path(thread.run_id, thread.thread_id, must_exist=False)
        if thread.messages:
            raise ConversationStoreError("new threads must start without messages")
        record = {"record_type": "thread", "thread": thread.model_dump(mode="json")}
        content = _canonical_record_bytes(record) + b"\n"
        lock = self._lock_for(thread.run_id, thread.thread_id)
        with self.run_store.lock_for(thread.run_id), lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("xb", buffering=0) as handle:
                    handle.write(content)
                    os.fsync(handle.fileno())
            except FileExistsError as exc:
                raise ThreadAlreadyExists(thread.thread_id) from exc
            self._fsync_directory(path.parent)
        return thread

    def append_message(
        self, run_id: str, thread_id: str, message: ConversationMessageV1
    ) -> ConversationMessageV1:
        path = self._thread_path(run_id, thread_id)
        if message.sequence < 1:
            raise ConversationConflict("message sequence must be positive")
        lock = self._lock_for(run_id, thread_id)
        with self.run_store.lock_for(run_id), lock:
            thread = self._read_thread_file(path)
            if message.request_id is not None:
                for existing in thread.messages:
                    if existing.request_id == message.request_id:
                        if existing.question == message.question:
                            return existing
                        raise ConversationConflict(
                            "request_id already contains a different question"
                        )
            expected = len(thread.messages) + 1
            if message.sequence < expected:
                existing = thread.messages[message.sequence - 1]
                if existing == message:
                    return existing
                raise ConversationConflict("message sequence already contains a different message")
            if message.sequence > expected:
                raise ConversationConflict(f"message sequence must be {expected}")
            record = {"record_type": "message", "message": message.model_dump(mode="json")}
            with path.open("ab", buffering=0) as handle:
                handle.write(_canonical_record_bytes(record) + b"\n")
                os.fsync(handle.fileno())
            self._fsync_directory(path.parent)
        return message

    def read_thread(self, run_id: str, thread_id: str) -> ConversationThreadV1:
        path = self._thread_path(run_id, thread_id)
        with self.run_store.lock_for(run_id), self._lock_for(run_id, thread_id):
            return self._read_thread_file(path)

    def list_threads(self, run_id: str) -> tuple[ConversationThreadV1, ...]:
        self._assert_run(run_id)
        directory = self.root / run_id / "conversations"
        if not directory.is_dir():
            return ()
        threads: list[ConversationThreadV1] = []
        for path in sorted(directory.glob("thread_*.jsonl")):
            threads.append(self._read_thread_file(path))
        return tuple(threads)

    def read_jsonl(self, run_id: str, thread_id: str) -> tuple[dict[str, Any], ...]:
        """Return the validated public records for portable export."""
        path = self._thread_path(run_id, thread_id)
        with self.run_store.lock_for(run_id), self._lock_for(run_id, thread_id):
            records = self._read_records(path)
        return tuple(records)

    def _read_thread_file(self, path: Path) -> ConversationThreadV1:
        records = self._read_records(path)
        if not records or records[0].get("record_type") != "thread":
            raise ConversationStoreCorruption(f"missing conversation header: {path.name}")
        try:
            base = ConversationThreadV1.model_validate(records[0].get("thread"))
            messages = tuple(
                ConversationMessageV1.model_validate(record.get("message"))
                for record in records[1:]
                if record.get("record_type") == "message"
            )
            if any(record.get("record_type") != "message" for record in records[1:]):
                raise ConversationStoreCorruption(f"invalid conversation record type: {path.name}")
            if len({message.request_id for message in messages if message.request_id is not None}) != len(
                [message.request_id for message in messages if message.request_id is not None]
            ):
                raise ConversationStoreCorruption(f"duplicate conversation request id: {path.name}")
            return ConversationThreadV1(
                **base.model_dump(exclude={"messages", "updated_at"}),
                updated_at=messages[-1].created_at if messages else base.updated_at,
                messages=messages,
            )
        except (TypeError, ValueError) as exc:
            raise ConversationStoreCorruption(f"invalid conversation records: {path.name}") from exc

    @staticmethod
    def _read_records(path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.endswith("\n"):
                        raise ConversationStoreCorruption(
                            f"unterminated conversation line {line_number}"
                        )
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ConversationStoreCorruption(
                            f"invalid conversation record {line_number}"
                        )
                    records.append(value)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            if isinstance(exc, ConversationStoreCorruption):
                raise
            raise ConversationStoreCorruption(f"invalid conversation log: {path.name}") from exc
        return records

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def new_thread_id() -> str:
    return f"thread_{uuid.uuid4().hex}"


__all__ = [
    "ConversationConflict",
    "ConversationStore",
    "ConversationStoreError",
    "ThreadAlreadyExists",
    "ThreadNotFound",
    "new_thread_id",
]
