"""Asynchronous Media Intelligence scanner."""
from __future__ import annotations

import asyncio, logging, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from bot.app.database.repositories import MediaMetadataRepository
from bot.app.services.hash_service import telegram_fingerprint
from bot.app.services.media_probe import MediaProbe
from bot.app.services.thumbnail_service import ThumbnailService

Path("logs").mkdir(exist_ok=True)
LOGGER = logging.getLogger("media_scanner")
if not LOGGER.handlers:
    handler = logging.FileHandler("logs/media_scanner.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler); LOGGER.setLevel(logging.INFO)

class SmartByteReader:
    """Deduplicates byte ranges fetched from Telegram ByteStreamer."""
    def __init__(self) -> None:
        self.ranges: dict[tuple[int, int], bytes] = {}
        self.bytes_read = 0

    async def read_range(self, streamer: Any, file_id: Any, offset: int, length: int, client_index: int = 0) -> bytes:
        key = (offset, length)
        if key in self.ranges:
            return self.ranges[key]
        chunks=[]
        async for chunk in streamer.yield_file(file_id, client_index, offset, 0, length, 1, length):
            chunks.append(chunk)
        data=b"".join(chunks)[:length]
        self.ranges[key]=data; self.bytes_read += len(data)
        return data

class MediaScanner:
    """Coordinates cache lookup, duplicate-scan suppression, probing, and failure handling."""
    scanner_version = 1

    def __init__(self, repository: MediaMetadataRepository | None = None, probe: MediaProbe | None = None) -> None:
        self.repository = repository or MediaMetadataRepository()
        self.probe = probe or MediaProbe()
        self.thumbnails = ThumbnailService()
        self._tasks: dict[str, asyncio.Task] = {}
        self._scan_times: list[float] = []
        self._cache_hits = 0; self._requests = 0

    async def get_or_schedule(self, media_id: str, file_properties: Any | None = None) -> Dict[str, Any]:
        """Return cached metadata immediately or start a non-blocking background scan."""
        self._requests += 1
        cached = self.repository.get_metadata(media_id)
        if cached and cached.get("status") == "scanned":
            self._cache_hits += 1; cached["cached"] = True; return cached
        if media_id not in self._tasks or self._tasks[media_id].done():
            self._tasks[media_id] = asyncio.create_task(self.scan(media_id, file_properties=file_properties))
        return {"_id": media_id, "status": "scanning", "cached": False}

    async def scan(self, media_id: str, file_properties: Any | None = None, sample: bytes | None = None) -> Dict[str, Any]:
        """Scan media once, cache the result, and never raise into the web server."""
        start = time.perf_counter()
        try:
            parsed: Dict[str, Any] = {}
            if sample:
                raw = await self.probe.probe_bytes(sample)
                parsed = self.probe.parse(raw)
            metadata = {"_id": media_id, "telegram_file_unique_id": getattr(file_properties, "unique_id", None), "size": getattr(file_properties, "file_size", None), "thumbnail": await self.thumbnails.ensure_thumbnail(media_id), "hash": telegram_fingerprint(media_id, file_properties), "scanner_version": self.scanner_version, "last_scanned": datetime.now(timezone.utc), "status": "scanned", **parsed}
            self.repository.save_metadata(metadata); self.repository.mark_scanned(media_id)
            elapsed = time.perf_counter() - start; self._scan_times.append(elapsed)
            LOGGER.info("scan ok media_id=%s duration=%.3fs bytes_read=%s", media_id, elapsed, len(sample or b""))
            return metadata
        except Exception as exc:
            elapsed = time.perf_counter() - start
            LOGGER.exception("scan failed media_id=%s duration=%.3fs", media_id, elapsed)
            self.repository.mark_failed(media_id, str(exc))
            return {"_id": media_id, "status": "failed", "error": str(exc)}

    async def rescan(self, media_id: str, file_properties: Any | None = None) -> Dict[str, Any]:
        """Delete old metadata and run a fresh scan for admin-initiated rescans."""
        self.repository.delete_metadata(media_id)
        return await self.scan(media_id, file_properties=file_properties)

    def health(self) -> Dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        scanned = self.repository.count_since(today, "scanned")
        failed = self.repository.count_since(today, "failed")
        total = scanned + failed
        return {"queue_size": sum(not t.done() for t in self._tasks.values()), "scanned_today": scanned, "failed_today": failed, "success_rate": (scanned / total) if total else 1.0, "average_scan_time": (sum(self._scan_times) / len(self._scan_times)) if self._scan_times else 0, "cache_hit_rate": (self._cache_hits / self._requests) if self._requests else 0}
