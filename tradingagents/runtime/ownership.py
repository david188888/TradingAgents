"""Fail fast when a second launcher tries to own the same run store."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def own_run_store(root: str | Path | None = None):
    store_root = Path(root or Path.home() / ".tradingagents" / "web" / "runs")
    store_root.mkdir(parents=True, exist_ok=True)
    # Never unlink this file: replacing a locked inode would admit two owners.
    descriptor = os.open(store_root / ".writer.lock", os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)

            def acquire():
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

            def release():
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(descriptor, fcntl.LOCK_UN)

        try:
            acquire()
        except (BlockingIOError, OSError) as exc:
            raise RuntimeError(
                f"Run store is already owned by another Web launcher: {store_root}"
            ) from exc
        acquired = True
        yield
    finally:
        if acquired:
            release()
        os.close(descriptor)
