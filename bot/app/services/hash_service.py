"""Hashing and Telegram fingerprint helpers."""
from __future__ import annotations

import hashlib, zlib
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def crc32_bytes(data: bytes) -> str:
    return format(zlib.crc32(data) & 0xFFFFFFFF, "08x")

def telegram_fingerprint(message_id: str, file_properties: Any | None = None) -> str:
    """Build a stable fingerprint without downloading the whole Telegram file."""
    unique = getattr(file_properties, "unique_id", None) or getattr(file_properties, "file_unique_id", None) or ""
    size = getattr(file_properties, "file_size", None) or ""
    name = getattr(file_properties, "file_name", None) or ""
    return sha256_bytes(f"{message_id}:{unique}:{size}:{name}".encode())
