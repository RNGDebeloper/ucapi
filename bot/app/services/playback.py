"""Playback state and preference services."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from bot.app.database.manager import DatabaseManager


class PlaybackService:
    """Stores watch history and user playback preferences."""

    def __init__(self) -> None:
        manager = DatabaseManager()
        self.history = manager.collection("watch_history", logical_db="user")
        self.preferences = manager.collection("user_preferences", logical_db="user")

    def get_history(self, user_id: str) -> list[Dict[str, Any]]:
        return list(self.history.find({"user_id": user_id}).sort("last_watched", -1).limit(100))

    def update_history(self, user_id: str, media_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = {**payload, "user_id": user_id, "media_id": media_id, "last_watched": datetime.now(timezone.utc)}
        self.history.update_one({"user_id": user_id, "media_id": media_id}, {"$set": data}, upsert=True)
        return data

    def get_preferences(self, user_id: str) -> Dict[str, Any]:
        return self.preferences.find_one({"_id": user_id}) or {"_id": user_id}

    def update_preferences(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = {**payload, "updated_at": datetime.now(timezone.utc)}
        self.preferences.update_one({"_id": user_id}, {"$set": data}, upsert=True)
        return self.get_preferences(user_id)
