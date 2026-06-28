"""FFprobe integration and metadata parser."""
from __future__ import annotations

import asyncio, json, shutil, tempfile
from pathlib import Path
from typing import Any, Dict

from bot.app.services.subtitle_detector import parse_subtitle_stream
from bot.app.services.video_detector import parse_video_stream
from bot.app.services.language_detector import detect_language

SUPPORTED_CONTAINERS = {"mkv","mp4","avi","mov","webm","ts","mpeg","mpg"}

class MediaProbe:
    """Runs ffprobe against a local path or a small ranged sample."""
    def __init__(self, ffprobe_path: str | None = None) -> None:
        self.ffprobe_path = ffprobe_path or shutil.which("ffprobe") or "ffprobe"

    async def probe_path(self, path: str) -> Dict[str, Any]:
        """Return raw ffprobe JSON for a media path."""
        proc = await asyncio.create_subprocess_exec(self.ffprobe_path, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(err.decode(errors="ignore") or "ffprobe failed")
        return json.loads(out.decode() or "{}")

    async def probe_bytes(self, data: bytes, suffix: str = ".bin") -> Dict[str, Any]:
        """Probe bytes already fetched by the smart byte reader."""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(data); name = handle.name
        try:
            return await self.probe_path(name)
        finally:
            Path(name).unlink(missing_ok=True)

    def parse(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize ffprobe JSON into the media_metadata schema."""
        fmt = raw.get("format") or {}; streams = raw.get("streams") or []
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
        chapters = raw.get("chapters") or []
        return {
            "container": (fmt.get("format_name") or "").split(",")[0] or None,
            "duration": float(fmt["duration"]) if fmt.get("duration") else None,
            "bitrate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
            "video": parse_video_stream(video_streams[0]) if video_streams else {},
            "audio_tracks": [self._audio(s) for s in audio_streams],
            "subtitle_tracks": [parse_subtitle_stream(s) for s in subtitle_streams],
            "chapters": [{"index": c.get("id", i), "start": float(c.get("start_time") or 0), "end": float(c.get("end_time") or 0), "title": (c.get("tags") or {}).get("title"), "tags": c.get("tags") or {}} for i, c in enumerate(chapters)],
            "audio_count": len(audio_streams), "subtitle_count": len(subtitle_streams), "chapter_count": len(chapters),
        }

    @staticmethod
    def _audio(stream: Dict[str, Any]) -> Dict[str, Any]:
        tags=stream.get("tags") or {}; disposition=stream.get("disposition") or {}
        return {"index": stream.get("index", 0), "language": detect_language(tags.get("language"), tags.get("title")), "codec": stream.get("codec_name"), "channels": stream.get("channels"), "sample_rate": int(stream["sample_rate"]) if str(stream.get("sample_rate", "")).isdigit() else None, "bitrate": int(stream["bit_rate"]) if str(stream.get("bit_rate", "")).isdigit() else None, "default": bool(disposition.get("default")), "forced": bool(disposition.get("forced")), "title": tags.get("title")}
