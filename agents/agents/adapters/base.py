"""Интерфейс адаптера DAW для ядра."""

from __future__ import annotations

from typing import Protocol

from ..domain import ClipData, ClipSummary


class DawAdapter(Protocol):
    """Интерфейс источника клипов. Больше методов не добавлять."""

    def list_clips(self, query: str = "") -> list[ClipSummary]:
        """Перечислить клипы, опционально фильтруя по имени трека/клипа."""
        ...

    def read_clip(self, ref_id: str) -> ClipData:
        """Прочитать клип по ``ref_id``."""
        ...
