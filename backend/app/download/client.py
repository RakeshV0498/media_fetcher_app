from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Progress:
    client_id: str
    state: str  # downloading | paused | done | failed
    progress: float  # 0..1
    speed: int  # bytes/s
    eta: int | None  # seconds
    content_path: str | None = None  # where finished files live (real clients)


class DownloadClient(Protocol):
    is_mock: bool

    def add(self, uri: str, category: str, save_path: str) -> str: ...
    def status(self, client_id: str) -> Progress | None: ...
    def pause(self, client_id: str) -> None: ...
    def resume(self, client_id: str) -> None: ...
    def remove(self, client_id: str, delete_files: bool = False) -> None: ...
