"""High-level metadata orchestration helpers."""
from __future__ import annotations

from typing import Any, Dict

from bot.app.services.media_scanner import MediaScanner


class MetadataService:
    """Public service used by routes that need cached-or-background metadata."""
    def __init__(self, scanner: MediaScanner | None = None) -> None:
        self.scanner = scanner or MediaScanner()

    async def get_or_schedule(self, media_id: str, file_properties: Any | None = None) -> Dict[str, Any]:
        return await self.scanner.get_or_schedule(media_id, file_properties=file_properties)
