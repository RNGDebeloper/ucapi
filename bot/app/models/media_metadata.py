"""Top-level media metadata model for the scanner cache."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class MediaMetadata:
    id: str
    telegram_file_unique_id: Optional[str] = None
    container: Optional[str] = None
    duration: Optional[float] = None
    size: Optional[int] = None
    video: Dict[str, Any] = field(default_factory=dict)
    audio_tracks: List[Dict[str, Any]] = field(default_factory=list)
    subtitle_tracks: List[Dict[str, Any]] = field(default_factory=list)
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    thumbnail: Optional[str] = None
    hash: Optional[str] = None
    scanner_version: int = 1
    last_scanned: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "scanned"
    error: Optional[str] = None

    def to_document(self) -> Dict[str, Any]:
        data = asdict(self)
        data["_id"] = data.pop("id")
        return data
