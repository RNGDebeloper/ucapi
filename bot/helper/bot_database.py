from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

from bot.config import Telegram


class BotDatabase:
    """Async MongoDB helper for bot runtime data."""

    def __init__(self) -> None:
        if not Telegram.MONGO_URI:
            raise ValueError("MONGO_URI/DATABASE_URL is required")
        self.client = AsyncIOMotorClient(Telegram.MONGO_URI)
        self.db = self.client["surftg_bot"]
        self.users = self.db["users"]
        self.content = self.db["content"]
        self.broadcast_logs = self.db["broadcast_logs"]
        self.metrics = self.db["metrics"]

    async def ensure_indexes(self) -> None:
        await self.users.create_indexes(
            [
                IndexModel([("user_id", DESCENDING)], unique=True),
                IndexModel([("last_seen", DESCENDING)]),
            ]
        )
        await self.content.create_indexes(
            [
                IndexModel([("chat_id", DESCENDING), ("msg_id", DESCENDING)], unique=True),
                IndexModel([("title", "text"), ("tags", "text")]),
                IndexModel([("search_title", ASCENDING)]),
                IndexModel([("created_at", DESCENDING)]),
            ]
        )
        await self.broadcast_logs.create_index([("created_at", DESCENDING)])

    async def upsert_user(self, user_id: int, username: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        await self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username,
                    "last_seen": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "join_verified": False,
                    "requests_total": 0,
                    "success_total": 0,
                    "failure_total": 0,
                },
            },
            upsert=True,
        )

    async def set_join_status(self, user_id: int, join_verified: bool) -> None:
        await self.users.update_one({"user_id": user_id}, {"$set": {"join_verified": join_verified}})

    async def set_pending_request(self, user_id: int, payload: str | None) -> None:
        await self.users.update_one({"user_id": user_id}, {"$set": {"pending_request": payload}})

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.users.find_one({"user_id": user_id})

    async def add_content(
        self,
        chat_id: int,
        msg_id: int,
        file_id: str,
        file_unique_id: str,
        title: str,
        tags: list[str],
        mime_type: str | None,
        file_size: int | None,
    ) -> None:
        now = datetime.now(timezone.utc)
        searchable_title = title.lower().strip()
        await self.content.update_one(
            {"chat_id": chat_id, "msg_id": msg_id},
            {
                "$set": {
                    "file_id": file_id,
                    "file_unique_id": file_unique_id,
                    "title": title,
                    "search_title": searchable_title,
                    "tags": tags,
                    "mime_type": mime_type,
                    "file_size": file_size,
                    "created_at": now,
                }
            },
            upsert=True,
        )

    async def search_content(self, query: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        safe_page = max(page, 1)
        words = re.findall(r"\w+", query.lower())
        filters: dict[str, Any] = {}

        if Telegram.AUTH_CHANNEL:
            allowed_ids = [int(chat_id) for chat_id in Telegram.AUTH_CHANNEL if str(chat_id).lstrip("-").isdigit()]
            if allowed_ids:
                filters["chat_id"] = {"$in": allowed_ids}

        if words:
            regex_parts = [f"(?=.*{re.escape(word)})" for word in words]
            pattern = "".join(regex_parts)
            search_filter = {
                "$or": [
                    {"search_title": {"$regex": pattern, "$options": "i"}},
                    {"tags": {"$elemMatch": {"$regex": pattern, "$options": "i"}}},
                ]
            }
            if filters:
                filters = {"$and": [filters, search_filter]}
            else:
                filters = search_filter

        total = await self.content.count_documents(filters)
        cursor = (
            self.content.find(filters, {"_id": 0})
            .sort("created_at", DESCENDING)
            .skip((safe_page - 1) * page_size)
            .limit(page_size)
        )
        docs = await cursor.to_list(length=page_size)
        return docs, total

    async def log_request(self, user_id: int, success: bool) -> None:
        await self.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "requests_total": 1,
                    "success_total": 1 if success else 0,
                    "failure_total": 0 if success else 1,
                }
            },
        )
        await self.metrics.update_one(
            {"_id": "global"},
            {
                "$inc": {
                    "total_requests": 1,
                    "success_total": 1 if success else 0,
                    "failure_total": 0 if success else 1,
                }
            },
            upsert=True,
        )

    async def create_broadcast_log(self, admin_id: int, source_message_id: int, total: int) -> str:
        now = datetime.now(timezone.utc)
        doc = {
            "admin_id": admin_id,
            "source_message_id": source_message_id,
            "total": total,
            "sent": 0,
            "failed": 0,
            "pending": total,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "failures": [],
        }
        result = await self.broadcast_logs.insert_one(doc)
        return str(result.inserted_id)

    async def update_broadcast_log(self, log_id: str, sent: int, failed: int, pending: int, failures: list[dict[str, Any]]) -> None:
        await self.broadcast_logs.update_one(
            {"_id": self._oid(log_id)},
            {
                "$set": {
                    "sent": sent,
                    "failed": failed,
                    "pending": pending,
                    "failures": failures,
                    "status": "completed" if pending == 0 else "running",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def get_stats(self) -> dict[str, int]:
        total_users = await self.users.count_documents({})
        active_users = await self.users.count_documents({"join_verified": True})
        global_metrics = await self.metrics.find_one({"_id": "global"}) or {}
        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_requests": global_metrics.get("total_requests", 0),
            "success_total": global_metrics.get("success_total", 0),
            "failure_total": global_metrics.get("failure_total", 0),
        }

    async def list_user_ids(self) -> list[int]:
        return [doc["user_id"] async for doc in self.users.find({}, {"user_id": 1, "_id": 0})]

    @staticmethod
    def _oid(value: str):
        from bson import ObjectId

        return ObjectId(value)


bot_db = BotDatabase()
