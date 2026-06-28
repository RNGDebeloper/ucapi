"""Subtitle track metadata models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class SubtitleTrack:
    index: int
    language: str = "Unknown"
    codec: Optional[str] = None
    forced: bool = False
    default: bool = False
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
