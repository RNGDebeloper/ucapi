"""Repository abstractions for tgstr persistence."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from pymongo import DESCENDING

from bot.app.database.manager import DatabaseManager


class MongoRepository:
    """Base repository with shared Mongo collection access."""

    def __init__(self, collection_name: str, logical_db: str = "media") -> None:
        self.collection = DatabaseManager().collection(collection_name, logical_db=logical_db)

    @staticmethod
    def _regex_query(text: str) -> Dict[str, str]:
        words = re.findall(r"\w+", (text or "").lower())
        regex_pattern = ".*".join(f"(?=.*{re.escape(word)})" for word in words)
        return {"$regex": f".*{regex_pattern}.*", "$options": "i"}


class PlaylistRepository(MongoRepository):
    """Repository for folders and playlist file documents."""

    def __init__(self) -> None:
        super().__init__("playlist", logical_db="media")

    def create_folder(self, parent_id: str, folder_name: str, thumbnail: str) -> None:
        self.collection.insert_one({"parent_folder": parent_id, "name": folder_name, "thumbnail": thumbnail, "type": "folder"})

    def insert_many(self, data: Iterable[Dict[str, Any]]) -> None:
        items = list(data)
        if items:
            self.collection.insert_many(items)

    def delete(self, document_id: str) -> bool:
        if self.collection.count_documents({"parent_folder": document_id}) > 0:
            self.collection.delete_many({"parent_folder": document_id})
        result = self.collection.delete_one({"_id": ObjectId(document_id)})
        return result.deleted_count > 0

    def update(self, document_id: str, name: str, thumbnail: str) -> bool:
        result = self.collection.update_one({"_id": ObjectId(document_id)}, {"$set": {"name": name, "thumbnail": thumbnail}})
        return result.modified_count > 0

    def folders(self, parent_id: str = "root", page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        query = {"parent_folder": parent_id, "type": "folder"}
        cursor = self.collection.find(query)
        if parent_id != "root":
            cursor = cursor.skip((int(page) - 1) * per_page).limit(per_page)
        return list(cursor)

    def files(self, parent_id: Optional[str], page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        return list(self.collection.find({"parent_folder": parent_id, "type": "file"}).sort("file_id", DESCENDING).skip((int(page) - 1) * per_page).limit(per_page))

    def get(self, document_id: str) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": ObjectId(document_id)})

    def search_folders(self, query: str) -> List[Dict[str, str]]:
        cursor = self.collection.find({"type": "folder", "name": self._regex_query(query)}).sort("_id", DESCENDING)
        return [{"_id": str(item["_id"]), "name": item["name"]} for item in cursor]

    def search_files(self, parent_id: str, query: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"type": "file", "parent_folder": parent_id, "name": self._regex_query(query)}).sort("file_id", DESCENDING).skip((int(page) - 1) * per_page).limit(per_page)
        return list(cursor)


class ConfigRepository(MongoRepository):
    """Repository for bot configuration."""

    def __init__(self) -> None:
        super().__init__("config", logical_db="user")

    def upsert(self, bot_id: str, theme: str, auth_channel: str) -> bool:
        result = self.collection.update_one({"_id": bot_id}, {"$set": {"theme": theme, "auth_channel": auth_channel}}, upsert=True)
        return result.modified_count > 0 or result.upserted_id is not None

    def get_variable(self, bot_id: str, key: str) -> Any:
        config = self.collection.find_one({"_id": bot_id})
        return config.get(key) if config is not None else None


class TelegramFileRepository(MongoRepository):
    """Repository for indexed Telegram files."""

    def __init__(self) -> None:
        super().__init__("files", logical_db="media")

    def list(self, chat_id: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        return list(self.collection.find({"chat_id": chat_id}).sort("msg_id", DESCENDING).skip((int(page) - 1) * per_page).limit(per_page))

    def add(self, chat_id: str, file_id: int, hash: str, name: str, size: int, file_type: str) -> None:
        if self.collection.find_one({"chat_id": chat_id, "hash": hash}):
            return
        self.collection.insert_one({"chat_id": chat_id, "msg_id": file_id, "hash": hash, "title": name, "size": size, "type": file_type})

    def search(self, chat_id: str, query: str, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        cursor = self.collection.find({"chat_id": chat_id, "title": self._regex_query(query)}).sort("msg_id", DESCENDING).skip((int(page) - 1) * per_page).limit(per_page)
        return list(cursor)

    def insert_many(self, data: Iterable[Dict[str, Any]]) -> None:
        items = list(data)
        if items:
            self.collection.insert_many(items)


class MetadataRepository(MongoRepository):
    """Repository for media metadata, watch history, and preferences."""

    def __init__(self, collection_name: str = "media_metadata", logical_db: str = "media") -> None:
        super().__init__(collection_name, logical_db=logical_db)


class MediaMetadataRepository(MongoRepository):
    """Repository for the Media Intelligence Engine cache."""

    def __init__(self) -> None:
        super().__init__("media_metadata", logical_db="media")
        self.collection.create_index("telegram_file_unique_id")
        self.collection.create_index("status")
        self.collection.create_index("last_scanned")

    def save_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a complete metadata document."""
        media_id = str(metadata.get("_id"))
        self.collection.replace_one({"_id": media_id}, {**metadata, "_id": media_id}, upsert=True)
        return {**metadata, "_id": media_id}

    def get_metadata(self, media_id: str) -> Optional[Dict[str, Any]]:
        """Return cached metadata for a message id, if present."""
        return self.collection.find_one({"_id": str(media_id)})

    def delete_metadata(self, media_id: str) -> bool:
        """Delete cached metadata so a manual rescan can rebuild it."""
        return self.collection.delete_one({"_id": str(media_id)}).deleted_count > 0

    def update_metadata(self, media_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Patch selected metadata fields and return the updated document."""
        self.collection.update_one({"_id": str(media_id)}, {"$set": updates}, upsert=True)
        return self.get_metadata(media_id)

    def mark_scanned(self, media_id: str) -> None:
        """Mark a metadata document as successfully scanned."""
        from datetime import datetime, timezone
        self.collection.update_one({"_id": str(media_id)}, {"$set": {"status": "scanned", "last_scanned": datetime.now(timezone.utc)}, "$unset": {"error": ""}}, upsert=True)

    def mark_failed(self, media_id: str, error: str) -> None:
        """Persist a scanner failure without crashing callers."""
        from datetime import datetime, timezone
        self.collection.update_one({"_id": str(media_id)}, {"$set": {"status": "failed", "error": error, "last_scanned": datetime.now(timezone.utc)}}, upsert=True)

    def count_since(self, iso_date: str, status: str) -> int:
        """Count scanner documents for a UTC date and status."""
        from datetime import datetime, time, timezone
        day = datetime.fromisoformat(iso_date).date()
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = datetime.combine(day, time.max, tzinfo=timezone.utc)
        return self.collection.count_documents({"status": status, "last_scanned": {"$gte": start, "$lte": end}})
