"""Video stream parsing helpers."""
from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def _fps(rate: str | None) -> float | None:
    if not rate or rate == "0/0":
        return None
    try:
        return round(float(Fraction(rate)), 3)
    except Exception:
        return None


def parse_video_stream(stream: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an ffprobe video stream into tgstr video metadata."""
    field_order = stream.get("field_order")
    transfer = stream.get("color_transfer")
    pix_fmt = stream.get("pix_fmt")
    hdr = transfer in HDR_TRANSFERS or (pix_fmt and "10" in pix_fmt and stream.get("color_primaries") == "bt2020")
    return {
        "index": stream.get("index", 0),
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "hdr": bool(hdr),
        "sdr": not bool(hdr),
        "bitrate": int(stream["bit_rate"]) if str(stream.get("bit_rate", "")).isdigit() else None,
        "fps": _fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
        "pixel_format": pix_fmt,
        "aspect_ratio": stream.get("display_aspect_ratio") or stream.get("sample_aspect_ratio"),
        "interlaced": field_order not in (None, "progressive", "unknown"),
        "progressive": field_order in (None, "progressive", "unknown"),
        "color_space": stream.get("color_space"),
    }
