"""Thumbnail cache service for poster/backdrop/preview assets."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class ThumbnailService:
    """Caches thumbnail paths and leaves extraction pluggable for future sprite support."""
    def __init__(self, cache_dir: str = "cache/thumbnails") -> None:
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cached_path(self, media_id: str, kind: str = "poster") -> Optional[str]:
        for ext in ("jpg", "png", "webp"):
            path = self.cache_dir / f"{media_id}_{kind}.{ext}"
            if path.exists():
                return str(path)
        return None

    async def ensure_thumbnail(self, media_id: str, source_path: str | None = None, kind: str = "poster") -> Optional[str]:
        """Return existing thumbnail; extraction can be added without changing callers."""
        return self.cached_path(media_id, kind=kind)
