"""Language normalization for media tracks."""
from __future__ import annotations

LANGUAGE_MAP = {"hin":"Hindi","hi":"Hindi","hindi":"Hindi","eng":"English","en":"English","english":"English","jpn":"Japanese","ja":"Japanese","japanese":"Japanese","tam":"Tamil","ta":"Tamil","tel":"Telugu","te":"Telugu","kor":"Korean","ko":"Korean","chi":"Chinese","zho":"Chinese","zh":"Chinese","und":"Unknown","unknown":"Unknown"}


def detect_language(value: str | None, title: str | None = None) -> str:
    """Return a supported display language from ffprobe tags or track title."""
    for candidate in (value, title):
        text = (candidate or "").strip().lower()
        if not text:
            continue
        if text in LANGUAGE_MAP:
            return LANGUAGE_MAP[text]
        for key, name in LANGUAGE_MAP.items():
            if key not in {"und", "unknown"} and key in text:
                return name
    return "Unknown"
