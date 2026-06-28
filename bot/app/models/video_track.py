"""Video track metadata models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class VideoTrack:
    index: int = 0
    codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    hdr: bool = False
    sdr: bool = True
    bitrate: Optional[int] = None
    fps: Optional[float] = None
    pixel_format: Optional[str] = None
    aspect_ratio: Optional[str] = None
    interlaced: bool = False
    progressive: bool = True
    color_space: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
