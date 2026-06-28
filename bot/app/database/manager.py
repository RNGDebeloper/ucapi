"""MongoDB connection management for tgstr logical databases."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from os import getenv
from typing import Dict, Mapping

from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase
from pymongo.errors import PyMongoError

from bot.config import Telegram

LOGGER = logging.getLogger(__name__)

LOGICAL_DATABASES = ("user", "media", "analytics", "social", "cache")
ENV_BY_DATABASE = {
    "user": "USER_DB_URI",
    "media": "MEDIA_DB_URI",
    "analytics": "ANALYTICS_DB_URI",
    "social": "SOCIAL_DB_URI",
    "cache": "CACHE_DB_URI",
}


@dataclass(frozen=True)
class DatabaseHealth:
    """Health status for a logical MongoDB connection."""

    name: str
    ok: bool
    message: str


class DatabaseManager:
    """Owns pooled MongoDB clients for each logical tgstr database.

    If a logical database URI is not configured, the legacy ``DATABASE_URI`` /
    ``DATABASE_URL`` value is used so existing deployments continue to work.
    ``MongoClient`` already provides connection pooling and reconnects lazily;
    this manager centralizes client creation, health checks, and collection
    access for repositories.
    """

    _instance: "DatabaseManager | None" = None

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._clients: Dict[str, MongoClient] = {}
        self._uris = self._resolve_uris()
        self._initialized = True

    @staticmethod
    def _legacy_uri() -> str:
        return getenv("DATABASE_URI") or Telegram.DATABASE_URL

    def _resolve_uris(self) -> Mapping[str, str]:
        fallback = self._legacy_uri()
        return {name: getenv(env) or fallback for name, env in ENV_BY_DATABASE.items()}

    def get_client(self, logical_db: str = "media") -> MongoClient:
        """Return a pooled client for the requested logical database."""
        if logical_db not in LOGICAL_DATABASES:
            raise KeyError(f"Unknown logical database: {logical_db}")
        if logical_db not in self._clients:
            uri = self._uris[logical_db]
            if not uri:
                raise RuntimeError("No MongoDB URI configured. Set DATABASE_URI or DATABASE_URL.")
            self._clients[logical_db] = MongoClient(
                uri,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                retryWrites=True,
                maxPoolSize=int(getenv("MONGO_MAX_POOL_SIZE", "100")),
            )
        return self._clients[logical_db]

    def get_database(self, logical_db: str = "media", name: str = "surftg") -> MongoDatabase:
        """Return a named MongoDB database from a logical connection."""
        return self.get_client(logical_db)[name]

    def collection(self, collection_name: str, logical_db: str = "media", db_name: str = "surftg"):
        """Return a collection from a logical database."""
        return self.get_database(logical_db, db_name)[collection_name]

    def health_checks(self) -> Dict[str, DatabaseHealth]:
        """Ping every configured logical database and return structured status."""
        results: Dict[str, DatabaseHealth] = {}
        for name in LOGICAL_DATABASES:
            try:
                self.get_client(name).admin.command("ping")
                results[name] = DatabaseHealth(name=name, ok=True, message="ok")
            except PyMongoError as exc:
                LOGGER.warning("MongoDB health check failed for %s: %s", name, exc)
                results[name] = DatabaseHealth(name=name, ok=False, message=str(exc))
            except Exception as exc:  # defensive: configuration/runtime errors
                LOGGER.exception("Unexpected database health failure for %s", name)
                results[name] = DatabaseHealth(name=name, ok=False, message=str(exc))
        return results

    def close(self) -> None:
        """Close all initialized clients."""
        for client in self._clients.values():
            client.close()
        self._clients.clear()
