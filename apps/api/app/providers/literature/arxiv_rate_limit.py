"""One connection and a three-second interval for this host's arXiv API calls."""

import asyncio
import importlib
import os
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import BinaryIO

from app.errors import DomainError


def _try_lock(handle: BinaryIO) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            msvcrt = importlib.import_module("msvcrt")

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl = importlib.import_module("fcntl")

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt = importlib.import_module("msvcrt")

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl = importlib.import_module("fcntl")

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ArxivRateGate:
    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or Path(tempfile.gettempdir()) / "researchos-arxiv-api.rate"

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        locked = False
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with self.state_path.open("a+b") as handle:
                if self.state_path.stat().st_size == 0:
                    handle.write(b"\x00")
                    handle.flush()
                started_wait = time.monotonic()
                while not _try_lock(handle):
                    if time.monotonic() - started_wait > 45:
                        raise DomainError(
                            "PROVIDER_RATE_LIMITED",
                            "arXiv request is busy; retry later",
                            429,
                            details={"retry_after_seconds": 3},
                        )
                    await asyncio.sleep(0.1)
                locked = True
                try:
                    handle.seek(1)
                    try:
                        last_started = float(handle.read(64).decode("ascii"))
                    except (ValueError, UnicodeDecodeError):
                        last_started = 0.0
                    wait = min(3.0, max(0.0, last_started + 3.0 - time.time()))
                    if wait:
                        await asyncio.sleep(wait)
                    # a+b is append-only: use a second descriptor while the lock is held.
                    with self.state_path.open("r+b") as state:
                        state.seek(1)
                        state.write(str(time.time()).encode("ascii"))
                        state.truncate()
                        state.flush()
                    yield
                finally:
                    if locked:
                        _unlock(handle)
        except OSError as exc:
            raise DomainError(
                "CONFIGURATION_ERROR", "arXiv rate limiter storage is unavailable", 503
            ) from exc
