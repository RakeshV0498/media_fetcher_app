from __future__ import annotations

import itertools
import time
from dataclasses import dataclass

from .client import Progress

DURATION = 20.0  # seconds for a simulated download


@dataclass
class _Job:
    started: float
    paused_at: float | None = None
    paused_total: float = 0.0


class MockClient:
    is_mock = True

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._ids = itertools.count(1)

    def add(self, uri: str, category: str, save_path: str) -> str:
        cid = f"mock-{next(self._ids)}"
        self._jobs[cid] = _Job(started=time.monotonic())
        return cid

    def _elapsed(self, j: _Job) -> float:
        end = j.paused_at if j.paused_at is not None else time.monotonic()
        return end - j.started - j.paused_total

    def status(self, client_id: str) -> Progress | None:
        j = self._jobs.get(client_id)
        if j is None:
            return None
        frac = min(self._elapsed(j) / DURATION, 1.0)
        if j.paused_at is not None:
            return Progress(client_id, "paused", frac, 0, None)
        if frac >= 1.0:
            return Progress(client_id, "done", 1.0, 0, 0)
        return Progress(client_id, "downloading", frac, 5_000_000, int(DURATION * (1 - frac)))

    def pause(self, client_id: str) -> None:
        j = self._jobs[client_id]
        if j.paused_at is None:
            j.paused_at = time.monotonic()

    def resume(self, client_id: str) -> None:
        j = self._jobs[client_id]
        if j.paused_at is not None:
            j.paused_total += time.monotonic() - j.paused_at
            j.paused_at = None

    def remove(self, client_id: str, delete_files: bool = False) -> None:
        self._jobs.pop(client_id, None)
