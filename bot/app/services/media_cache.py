"""Media metadata cache service backed by MongoDB."""
from __future__ import annotations

from typing import Any, Dict, Optional

from bot.app.database.repositories import MediaMetadataRepository


class MediaCache:
    """Thin cache facade so scanner callers do not depend on Mongo details."""
    def __init__(self, repository: MediaMetadataRepository | None = None) -> None:
        self.repository = repository or MediaMetadataRepository()

    def get(self, media_id: str) -> Optional[Dict[str, Any]]:
        return self.repository.get_metadata(media_id)

    def set(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        self.repository.save_metadata(metadata)
        return metadata

    def delete(self, media_id: str) -> None:
        self.repository.delete_metadata(media_id)
