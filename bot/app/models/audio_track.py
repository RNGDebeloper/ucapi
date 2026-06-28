"""Audio track metadata models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class AudioTrack:
    index: int
    language: str = "Unknown"
    codec: Optional[str] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    bitrate: Optional[int] = None
    default: bool = False
    forced: bool = False
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
