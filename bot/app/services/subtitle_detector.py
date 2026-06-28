"""Subtitle stream parsing helpers."""
from __future__ import annotations

from typing import Any, Dict

from bot.app.services.language_detector import detect_language


def parse_subtitle_stream(stream: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ffprobe subtitle stream into tgstr subtitle metadata."""
    tags = stream.get("tags") or {}
    disposition = stream.get("disposition") or {}
    return {"index": stream.get("index", 0), "language": detect_language(tags.get("language"), tags.get("title")), "codec": stream.get("codec_name"), "forced": bool(disposition.get("forced")), "default": bool(disposition.get("default")), "title": tags.get("title")}
