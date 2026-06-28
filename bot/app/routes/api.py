"""Modern JSON API routes for tgstr."""
from __future__ import annotations

from aiohttp import web
from aiohttp_session import get_session

from bot.app.database.manager import DatabaseManager
from bot.app.database.repositories import PlaylistRepository
from bot.app.services.media_info import MediaInfoService
from bot.app.services.media_scanner import MediaScanner
from bot.app.services.playback import PlaybackService
from bot.app.utils.json import serialize

routes = web.RouteTableDef()

_media_info: MediaInfoService | None = None
_playback: PlaybackService | None = None
_playlist: PlaylistRepository | None = None
_scanner: MediaScanner | None = None


def get_media_info_service() -> MediaInfoService:
    global _media_info
    if _media_info is None:
        _media_info = MediaInfoService()
    return _media_info


def get_playback_service() -> PlaybackService:
    global _playback
    if _playback is None:
        _playback = PlaybackService()
    return _playback


def get_media_scanner() -> MediaScanner:
    global _scanner
    if _scanner is None:
        _scanner = MediaScanner()
    return _scanner


def get_playlist_repository() -> PlaylistRepository:
    global _playlist
    if _playlist is None:
        _playlist = PlaylistRepository()
    return _playlist


def _user_id(session) -> str:
    return session.get("user", "anonymous")


@routes.get("/api/health")
async def health(request: web.Request) -> web.Response:
    checks = DatabaseManager().health_checks()
    status = 200 if all(check.ok for check in checks.values()) else 503
    return web.json_response({"databases": {name: check.__dict__ for name, check in checks.items()}}, status=status)


@routes.get("/api/media/{id}")
async def get_media(request: web.Request) -> web.Response:
    media_id = request.match_info["id"]
    document = get_playlist_repository().get(media_id)
    metadata = get_media_info_service().get_cached(media_id)
    if not document and not metadata:
        raise web.HTTPNotFound(text="Media not found")
    if metadata is None:
        metadata = await get_media_scanner().get_or_schedule(media_id)
    return web.json_response({"media": serialize(document or metadata), "metadata": serialize(metadata)})


@routes.get("/api/playback/{id}")
async def get_playback(request: web.Request) -> web.Response:
    session = await get_session(request)
    service = get_playback_service()
    user_id = _user_id(session)
    media_id = request.match_info["id"]
    history = service.history.find_one({"user_id": user_id, "media_id": media_id}) or {}
    preferences = service.get_preferences(user_id)
    return web.json_response({"playback": serialize(history), "preferences": serialize(preferences)})


@routes.post("/api/playback/{id}")
async def update_playback(request: web.Request) -> web.Response:
    session = await get_session(request)
    data = await request.json()
    updated = get_playback_service().update_history(_user_id(session), request.match_info["id"], data)
    return web.json_response({"playback": serialize(updated)})


@routes.get("/api/search")
async def api_search(request: web.Request) -> web.Response:
    query = request.query.get("q", "")
    parent = request.query.get("parent", "root")
    page = int(request.query.get("page", "1"))
    return web.json_response({"results": serialize(get_playlist_repository().search_files(parent, query, page=page))})


@routes.get("/api/history")
async def get_history(request: web.Request) -> web.Response:
    session = await get_session(request)
    return web.json_response({"history": serialize(get_playback_service().get_history(_user_id(session)))})


@routes.get("/api/preferences")
async def get_preferences(request: web.Request) -> web.Response:
    session = await get_session(request)
    return web.json_response({"preferences": serialize(get_playback_service().get_preferences(_user_id(session)))})


@routes.post("/api/preferences")
async def update_preferences(request: web.Request) -> web.Response:
    session = await get_session(request)
    data = await request.json()
    return web.json_response({"preferences": serialize(get_playback_service().update_preferences(_user_id(session), data))})


@routes.post("/api/admin/rescan/{message_id}")
async def rescan_media(request: web.Request) -> web.Response:
    """Force-delete cached media metadata and scan again."""
    metadata = await get_media_scanner().rescan(request.match_info["message_id"])
    return web.json_response({"metadata": serialize(metadata)})


@routes.get("/api/admin/scanner")
async def scanner_health(request: web.Request) -> web.Response:
    """Return Media Intelligence Engine queue/cache counters."""
    return web.json_response({"scanner": serialize(get_media_scanner().health())})
