"""Backward-compatible database facade.

Legacy route/helper code imports :class:`Database` directly. Internally this
facade now delegates to repository classes backed by ``DatabaseManager`` so new
code can use logical databases without breaking existing callers.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable

from bot.app.database.manager import DatabaseManager
from bot.app.database.repositories import ConfigRepository, PlaylistRepository, TelegramFileRepository
from bot.config import Telegram

LOGGER = logging.getLogger(__name__)


class Database:
    """Compatibility wrapper around repository-based persistence."""

    def __init__(self) -> None:
        manager = DatabaseManager()
        self.mongo_client = manager.get_client("media")
        self.db = manager.get_database("media")
        self.collection = manager.collection("playlist", logical_db="media")
        self.config = manager.collection("config", logical_db="user")
        self.files = manager.collection("files", logical_db="media")
        self.playlists = PlaylistRepository()
        self.config_repo = ConfigRepository()
        self.tg_files = TelegramFileRepository()

    async def create_folder(self, parent_id, folder_name, thumbnail):
        self.playlists.create_folder(parent_id, folder_name, thumbnail)

    def delete(self, document_id):
        try:
            return self.playlists.delete(document_id)
        except Exception as exc:
            LOGGER.exception("Failed to delete document %s", document_id)
            return False

    async def edit(self, id, name, thumbnail):
        return self.playlists.update(id, name, thumbnail)

    async def search_DbFolder(self, query):
        return self.playlists.search_folders(query)

    async def add_json(self, data: Iterable[Dict[str, Any]]):
        self.playlists.insert_many(data)

    async def get_Dbfolder(self, parent_id="root", page=1, per_page=50):
        return self.playlists.folders(parent_id or "root", int(page), per_page)

    async def get_dbFiles(self, parent_id=None, page=1, per_page=50):
        return self.playlists.files(parent_id, int(page), per_page)

    async def get_info(self, id):
        document = self.playlists.get(id)
        return document.get("name") if document else None

    async def search_dbfiles(self, id, query, page=1, per_page=50):
        return self.playlists.search_files(id, query, int(page), per_page)

    async def update_config(self, theme, auth_channel):
        bot_id = Telegram.BOT_TOKEN.split(":", 1)[0]
        return self.config_repo.upsert(bot_id, theme, auth_channel)

    async def get_variable(self, key):
        bot_id = Telegram.BOT_TOKEN.split(":", 1)[0]
        return self.config_repo.get_variable(bot_id, key)

    async def list_tgfiles(self, id, page=1, per_page=50):
        return self.tg_files.list(id, int(page), per_page)

    async def add_tgfiles(self, chat_id, file_id, hash, name, size, file_type):
        self.tg_files.add(chat_id, file_id, hash, name, size, file_type)

    async def search_tgfiles(self, id, query, page=1, per_page=50):
        return self.tg_files.search(id, query, int(page), per_page)

    async def add_btgfiles(self, data):
        self.tg_files.insert_many(data)
