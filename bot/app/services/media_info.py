"""Media intelligence service for Telegram-backed media."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bot.app.database.manager import DatabaseManager

LOGGER = logging.getLogger(__name__)


class MediaInfoService:
    """Extracts and caches media metadata.

    The first implementation is conservative and non-invasive: it stores known
    Telegram attributes and MIME-derived hints without downloading the whole
    file. A future ffprobe/range parser can be added behind ``_inspect_ranges``
    without changing route or repository callers.
    """

    def __init__(self) -> None:
        self.collection = DatabaseManager().collection("media_metadata", logical_db="media")

    def get_cached(self, media_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": media_id})

    def invalidate(self, media_id: str) -> None:
        self.collection.delete_one({"_id": media_id})

    async def scan_telegram_media(self, media_id: str, file_properties: Any | None = None, force: bool = False) -> Dict[str, Any]:
        """Return cached media info or scan minimal metadata for a Telegram file."""
        if not force and (cached := self.get_cached(media_id)):
            cached["cached"] = True
            return cached

        metadata: Dict[str, Any] = {
            "_id": media_id,
            "codec": None,
            "duration": getattr(file_properties, "duration", None),
            "bitrate": None,
            "hdr": False,
            "resolution": self._resolution(file_properties),
            "audio_tracks": [],
            "subtitle_tracks": [],
            "chapters": [],
            "mime_type": getattr(file_properties, "mime_type", None),
            "file_name": getattr(file_properties, "file_name", None),
            "file_size": getattr(file_properties, "file_size", None),
            "scanned_at": datetime.now(timezone.utc),
            "cached": False,
        }
        self.collection.replace_one({"_id": media_id}, metadata, upsert=True)
        return metadata

    @staticmethod
    def _resolution(file_properties: Any | None) -> Optional[Dict[str, int]]:
        width = getattr(file_properties, "width", None)
        height = getattr(file_properties, "height", None)
        if width and height:
            return {"width": width, "height": height}
        return None
