from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DESCENDING, IndexModel
from pymongo.errors import OperationFailure, PyMongoError

from bot import LOGGER
from bot.config import Telegram


class BotDatabase:
    """Async MongoDB helper for bot runtime data."""

    CONTENT_TEXT_INDEX_NAME = "content_text_search"

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
        """Create all required indexes with conflict-safe text index migration."""
        try:
            await self.users.create_indexes(
                [
                    IndexModel([("user_id", DESCENDING)], unique=True, name="users_user_id_unique"),
                    IndexModel([("last_seen", DESCENDING)], name="users_last_seen_desc"),
                ]
            )

            await self._ensure_content_indexes()
            await self.broadcast_logs.create_index([("created_at", DESCENDING)], name="broadcast_created_desc")
            LOGGER.info("MongoDB indexes ensured successfully")
        except Exception as err:
            # Startup must continue even if index setup fails.
            LOGGER.error("Index setup failed (continuing startup): %s", err, exc_info=True)

    async def _ensure_content_indexes(self) -> None:
        desired_text_keys = [("title", "text"), ("tags", "text"), ("search_blob", "text")]
        desired_weights = {"title": 1, "tags": 1, "search_blob": 1}

        try:
            info = await self.content.index_information()
        except PyMongoError as err:
            LOGGER.error("Unable to fetch existing index information: %s", err, exc_info=True)
            info = {}

        has_desired_text_index = False
        conflicting_text_indexes: list[str] = []

        for index_name, meta in info.items():
            keys = meta.get("key", [])
            if not any(kind == "text" for _, kind in keys):
                continue

            weights = {k: int(v) for k, v in (meta.get("weights") or {}).items()}
            keys_match = keys == desired_text_keys
            weights_match = all(weights.get(k, 1) == w for k, w in desired_weights.items()) and set(weights) == set(desired_weights)

            if keys_match and weights_match:
                has_desired_text_index = True
            else:
                conflicting_text_indexes.append(index_name)

        if conflicting_text_indexes:
            for index_name in conflicting_text_indexes:
                try:
                    await self.content.drop_index(index_name)
                    LOGGER.info("Dropped conflicting text index: %s", index_name)
                except PyMongoError as err:
                    LOGGER.error("Failed to drop conflicting index %s: %s", index_name, err, exc_info=True)

        if not has_desired_text_index:
            try:
                await self.content.create_index(
                    desired_text_keys,
                    name=self.CONTENT_TEXT_INDEX_NAME,
                    weights=desired_weights,
                    default_language="none",
                )
                LOGGER.info("Created text index: %s", self.CONTENT_TEXT_INDEX_NAME)
            except OperationFailure as err:
                LOGGER.error("Text index creation failed: %s", err, exc_info=True)
            except PyMongoError as err:
                LOGGER.error("Unexpected error during text index creation: %s", err, exc_info=True)
        else:
            LOGGER.info("Desired text index already present; skipping creation")

        # Non-text indexes are idempotent and safe to call repeatedly.
        await self.content.create_indexes(
            [
                IndexModel([("chat_id", DESCENDING), ("msg_id", DESCENDING)], unique=True, name="content_chat_msg_unique"),
                IndexModel([("search_blob", DESCENDING)], name="content_search_blob_desc"),
                IndexModel([("created_at", DESCENDING)], name="content_created_desc"),
            ]
        )

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
        search_blob = f"{title} {' '.join(tags)}".lower()
        await self.content.update_one(
            {"chat_id": chat_id, "msg_id": msg_id},
            {
                "$set": {
                    "file_id": file_id,
                    "file_unique_id": file_unique_id,
                    "title": title,
                    "tags": tags,
                    "search_blob": search_blob,
                    "mime_type": mime_type,
                    "file_size": file_size,
                    "created_at": now,
                }
            },
            upsert=True,
        )

    async def search_content(self, query: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        words = re.findall(r"\w+", query.lower())
        offset = (max(page, 1) - 1) * page_size

        if not words:
            total = await self.content.count_documents({})
            cursor = self.content.find({}, {"_id": 0}).sort("created_at", DESCENDING).skip(offset).limit(page_size)
            return await cursor.to_list(length=page_size), total

        regex_parts = [f"(?=.*{re.escape(word)})" for word in words]
        pattern = "".join(regex_parts)
        regex_filter = {"search_blob": {"$regex": pattern, "$options": "i"}}
        text_filter = {"$text": {"$search": " ".join(words)}}

        # Try text-first query for speed/relevance, fallback to regex-only when needed.
        try:
            combined_filter: dict[str, Any] = {"$or": [text_filter, regex_filter]}
            total = await self.content.count_documents(combined_filter)
            cursor = (
                self.content.find(combined_filter, {"_id": 0})
                .sort("created_at", DESCENDING)
                .skip(offset)
                .limit(page_size)
            )
            docs = await cursor.to_list(length=page_size)
            return docs, total
        except OperationFailure:
            total = await self.content.count_documents(regex_filter)
            cursor = (
                self.content.find(regex_filter, {"_id": 0})
                .sort("created_at", DESCENDING)
                .skip(offset)
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
