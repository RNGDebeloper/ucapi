import json
import logging
import math
import mimetypes
import secrets
from aiohttp import web
from aiohttp.http_exceptions import BadStatusLine
from bot.helper.chats import get_chats
from bot.helper.database import Database
from bot.helper.search import search
from bot.helper.thumbnail import get_image
from bot.telegram import work_loads, multi_clients
from aiohttp_session import get_session
from bot.config import Telegram
from bot.helper.exceptions import FIleNotFound, InvalidHash
from bot.helper.index import get_files
from bot.server.custom_dl import ByteStreamer
from bot.helper.cache import rm_cache
from bot.helper.file_size import get_readable_file_size
from bot.server.file_properties import get_file_ids

from bot.telegram import StreamBot

client_cache = {}

routes = web.RouteTableDef()
db = Database()


def _is_admin(username):
    return username == Telegram.ADMIN_USERNAME


def _auth_payload(request):
    return {
        "authenticated": False,
        "login_url": "/login",
        "redirect_url": request.path_qs,
    }


def _serialize_document(document):
    data = {}
    for key, value in document.items():
        data["id" if key == "_id" else key] = str(value) if key == "_id" else value
    return data


def _with_watch_urls(posts, chat_id, id_key="msg_id"):
    enriched = []
    for post in posts:
        item = _serialize_document(post)
        item_chat_id = chat_id or item.get("chat_id")
        public_chat_id = str(item_chat_id).replace("-100", "")
        message_id = item.get(id_key) or item.get("file_id")
        secure_hash = item.get("hash")
        item["watch_url"] = f"/watch/{public_chat_id}?id={message_id}&hash={secure_hash}"
        item["download_url"] = f"/{public_chat_id}/{message_id}?id={message_id}&hash={secure_hash}"
        enriched.append(item)
    return enriched


@routes.get('/login')
async def login_form(request):
    session = await get_session(request)
    redirect_url = session.get('redirect_url', '/')
    return web.json_response({
        "authenticated": "user" in session,
        "redirect_url": redirect_url,
    })


@routes.post('/login')
async def login_route(request):
    session = await get_session(request)
    if 'user' in session:
        return web.HTTPFound('/')
    data = await request.post()
    username = data.get('username')
    password = data.get('password')
    error_message = None
    if (username == Telegram.USERNAME and password == Telegram.PASSWORD) or (username == Telegram.ADMIN_USERNAME and password == Telegram.ADMIN_PASSWORD):
        session['user'] = username
        if 'redirect_url' not in session:
            session['redirect_url'] = '/'
        redirect_url = session['redirect_url']
        del session['redirect_url']
        return web.json_response({
            "authenticated": True,
            "redirect_url": redirect_url,
            "is_admin": _is_admin(username),
        })
    else:
        error_message = "Invalid username or password"
    return web.json_response({"authenticated": False, "error": error_message}, status=401)


@routes.post('/logout')
async def logout_route(request):
    session = await get_session(request)
    session.pop('user', None)
    return web.HTTPFound('/login')


@routes.post('/create')
async def create_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    folderName = data.get('folderName')
    thumbnail = data.get('thumbnail')
    parent_dir = data.get('parent_dir')
    parent_dir = parent_dir.split('db=')[-1] if 'db=' in parent_dir else 'root'
    await db.create_folder(parent_dir, folderName, thumbnail)
    if parent_dir == 'root':
        return web.HTTPFound('/')
    else:
        return web.HTTPFound(f'/playlist?db={parent_dir}')


@routes.post('/delete')
async def delete_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.json()
    id = data.get('delete_id')
    parent = data.get('parent')
    if not (success := db.delete(id)):
        return web.HTTPInternalServerError()
    if parent == 'root':
        return web.HTTPFound('/')
    else:
        return web.HTTPFound(f'/playlist?db={parent}')


@routes.post('/edit')
async def editFolder_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    folderName = data.get('folderName')
    thumbnail = data.get('thumbnail')
    id = data.get('folder_id')
    parent = data.get('parent')
    success = await db.edit(id, folderName, thumbnail)
    if not success:
        return web.HTTPInternalServerError()
    if parent == 'root':
        return web.HTTPFound('/')
    else:
        return web.HTTPFound(f'/playlist?db={parent}')


@routes.post('/edit_post')
async def editPost_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    fileName = data.get('fileName')
    thumbnail = data.get('filethumbnail')
    id = data.get('file_id')
    parent = data.get('file_folder_id')
    success = await db.edit(id, fileName, thumbnail)
    if not success:
        return web.HTTPInternalServerError()
    if parent == 'root':
        return web.HTTPFound('/')
    else:
        return web.HTTPFound(f'/playlist?db={parent}')


@routes.get('/searchDbFol')
async def searchDbFolder_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    query = request.query.get('query', '')
    folder_names = await db.search_DbFolder(query)
    return web.json_response(folder_names)


@routes.post('/send')
async def send_route(request):
    data = await request.post()
    chat_id = data.get('chatId')
    chat_id = f"-100{chat_id}"
    folder_id = data.get('folderId')
    selected_ids = data.get('selectedIds')
    if not all([chat_id, folder_id, selected_ids]):
        return {'error': 'Missing required data in request'}

    formatted_entries = []
    for entry in selected_ids.split(','):
        file_id, hash, filename, size, file_type, thumbnail = entry.split('|')
        formatted_entries.append({
            'chat_id': chat_id,
            'parent_folder': folder_id,
            'file_id': file_id,
            'hash': hash,
            'name': filename,
            'size': size,
            'file_type': file_type,
            'thumbnail': thumbnail,
            'type': 'file'
        })

    json_data = json.dumps(formatted_entries)
    data = json.loads(json_data)
    await db.add_json(data)
    if folder_id == 'root':
        return web.HTTPFound('/')
    else:
        return web.HTTPFound(f'/playlist?db={folder_id}')


@routes.get('/reload')
async def reload_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})

    chat_id = request.query.get('chatId', '')
    if chat_id == 'home':
        rm_cache()
        return web.HTTPFound('/')
    else:
        rm_cache(f"-100{chat_id}")
        return web.HTTPFound(f'/channel/{chat_id}')


@routes.post('/config')
async def editConfig_route(request):
    session = await get_session(request)
    if (username := session.get('user')) != Telegram.ADMIN_USERNAME:
        return web.json_response({'msg': 'Who the hell you are'})
    data = await request.post()
    channel = data.get('channel')
    theme = data.get('theme')
    success = await db.update_config(theme=theme, auth_channel=channel)
    if not success:
        return web.HTTPInternalServerError()
    return web.HTTPFound('/')



@routes.get('/')
async def home_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        try:
            channels = await get_chats()
            playlists = await db.get_Dbfolder()
            return web.json_response({
                "route": "home",
                "is_admin": _is_admin(username),
                "channels": channels,
                "playlists": [_serialize_document(playlist) for playlist in playlists],
            })
        except Exception as e:
            logging.critical(e.with_traceback(None))
            raise web.HTTPInternalServerError(text=str(e)) from e
    else:
        session['redirect_url'] = request.path_qs
        return web.json_response(_auth_payload(request), status=401)


@routes.get('/playlist')
async def playlist_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        try:
            parent_id = request.query.get('db')
            page = request.query.get('page', '1')
            playlists = await db.get_Dbfolder(parent_id, page=page)
            files = await db.get_dbFiles(parent_id, page=page)
            text = await db.get_info(parent_id)
            return web.json_response({
                "route": "playlist",
                "is_admin": _is_admin(username),
                "parent_id": parent_id,
                "page": int(page),
                "title": text,
                "playlists": [_serialize_document(playlist) for playlist in playlists],
                "files": _with_watch_urls(files, None, id_key="file_id"),
            })
        except Exception as e:
            logging.critical(e.with_traceback(None))
            raise web.HTTPInternalServerError(text=str(e)) from e
    else:
        session['redirect_url'] = request.path_qs
        return web.json_response(_auth_payload(request), status=401)


@routes.get('/search/db/{parent}')
async def dbsearch_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        parent = request.match_info['parent']
        page = request.query.get('page', '1')
        query = request.query.get('q')
        try:
            files = await db.search_dbfiles(id=parent, page=page, query=query)
            name = await db.get_info(parent)
            text = f"{name} - {query}"
            return web.json_response({
                "route": "dbsearch",
                "is_admin": _is_admin(username),
                "parent_id": parent,
                "page": int(page),
                "query": query,
                "title": text,
                "files": _with_watch_urls(files, None, id_key="file_id"),
            })
        except Exception as e:
            logging.critical(e.with_traceback(None))
            raise web.HTTPInternalServerError(text=str(e)) from e
    else:
        session['redirect_url'] = request.path_qs
        return web.json_response(_auth_payload(request), status=401)


@routes.get('/channel/{chat_id}')
async def channel_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        chat_id = request.match_info['chat_id']
        chat_id = f"-100{chat_id}"
        page = request.query.get('page', '1')
        try:
            posts = await get_files(chat_id, page=page)
            chat = await StreamBot.get_chat(int(chat_id))
            return web.json_response({
                "route": "channel",
                "is_admin": _is_admin(username),
                "chat": {
                    "id": chat_id,
                    "public_id": chat_id.replace("-100", ""),
                    "title": chat.title,
                },
                "page": int(page),
                "posts": _with_watch_urls(posts, chat_id),
            })
        except Exception as e:
            logging.critical(e.with_traceback(None))
            raise web.HTTPInternalServerError(text=str(e)) from e
    else:
        session['redirect_url'] = request.path_qs
        return web.json_response(_auth_payload(request), status=401)


@routes.get('/search/{chat_id}')
async def search_route(request):
    session = await get_session(request)
    if username := session.get('user'):
        chat_id = request.match_info['chat_id']
        chat_id = f"-100{chat_id}"
        page = request.query.get('page', '1')
        query = request.query.get('q')
        try:
            posts = await search(chat_id, page=page, query=query)
            chat = await StreamBot.get_chat(int(chat_id))
            text = f"{chat.title} - {query}"
            return web.json_response({
                "route": "search",
                "is_admin": _is_admin(username),
                "chat": {
                    "id": chat_id,
                    "public_id": chat_id.replace("-100", ""),
                    "title": chat.title,
                },
                "page": int(page),
                "query": query,
                "title": text,
                "posts": _with_watch_urls(posts, chat_id),
            })
        except Exception as e:
            logging.critical(e.with_traceback(None))
            raise web.HTTPInternalServerError(text=str(e)) from e
    else:
        session['redirect_url'] = request.path_qs
        return web.json_response(_auth_payload(request), status=401)


@routes.get('/api/thumb/{chat_id}', allow_head=True)
async def get_thumbnail(request):
    chat_id = request.match_info['chat_id']
    if message_id := request.query.get('id'):
        img = await get_image(chat_id, message_id)
    else:
        img = await get_image(chat_id, None)
    response = web.FileResponse(img)
    response.content_type = "image/jpeg"
    return response


@routes.get('/watch/{chat_id}', allow_head=True)
async def stream_handler_watch(request: web.Request):
    session = await get_session(request)
    if username := session.get('user'):
        try:
            chat_id = request.match_info['chat_id']
            chat_id = f"-100{chat_id}"
            message_id = request.query.get('id')
            secure_hash = request.query.get('hash')
            file_data = await get_file_ids(
                StreamBot, chat_id=int(chat_id), message_id=int(message_id)
            )
            if file_data.unique_id[:6] != secure_hash:
                logging.info("Link hash: %s - %s", secure_hash, file_data.unique_id[:6])
                logging.info("Invalid hash for message with - ID %s", message_id)
                raise InvalidHash

            filename = file_data.file_name or "Proper Filename is Missing"
            mime_type = file_data.mime_type or "application/octet-stream"
            tag = mime_type.split("/")[0].strip() if "/" in mime_type else "file"
            stream_url = (
                f"/{chat_id.replace('-100', '')}/{message_id}"
                f"?id={message_id}&hash={secure_hash}"
            )
            payload = {
                "route": "watch",
                "is_admin": _is_admin(username),
                "chat_id": chat_id,
                "message_id": int(message_id),
                "hash": secure_hash,
                "file": {
                    "name": filename,
                    "mime_type": mime_type,
                    "tag": tag,
                    "size": file_data.file_size,
                    "readable_size": get_readable_file_size(file_data.file_size),
                    "stream_url": stream_url,
                    "download_url": stream_url,
                    "thumbnail_url": f"/api/thumb/{chat_id}?id={message_id}",
                },
            }
            if tag == "video":
                message = await StreamBot.get_messages(chat_id, int(message_id))
                video = getattr(message, "video", None)
                duration_sec = getattr(video, "duration", None)
                payload["video"] = {
                    "caption": message.caption or getattr(video, "file_name", "") or "",
                    "duration": int(duration_sec) if duration_sec else None,
                }
            return web.json_response(payload)
        except InvalidHash as e:
            raise web.HTTPForbidden(text=e.message) from e
        except FIleNotFound as e:
            db.delete_file(chat_id=chat_id, msg_id=message_id, hash=secure_hash)
            raise web.HTTPNotFound(text=e.message) from e
        except (AttributeError, BadStatusLine, ConnectionResetError):
            pass
        except Exception as e:
            logging.critical(e.with_traceback(None))
            raise web.HTTPInternalServerError(text=str(e)) from e
    else:
        session['redirect_url'] = request.path_qs
        return web.json_response(_auth_payload(request), status=401)


@routes.get('/{chat_id}/{encoded_name}', allow_head=True)
async def stream_handler(request: web.Request):
    try:
        chat_id = request.match_info['chat_id']
        chat_id = f"-100{chat_id}"
        message_id = request.query.get('id')
        #name = request.match_info['encoded_name']
        secure_hash = request.query.get('hash')
        return await media_streamer(request, int(chat_id), int(message_id), secure_hash)
    except InvalidHash as e:
        raise web.HTTPForbidden(text=e.message) from e
    except FIleNotFound as e:
        db.delete_file(chat_id=chat_id, msg_id=message_id, hash=secure_hash)
        raise web.HTTPNotFound(text=e.message) from e
    except (AttributeError, BadStatusLine, ConnectionResetError):
        pass
    except Exception as e:
        logging.critical(e.with_traceback(None))
        raise web.HTTPInternalServerError(text=str(e))


class_cache = {}


async def media_streamer(request: web.Request, chat_id: int, id: int, secure_hash: str):
    range_header = request.headers.get("Range", 0)

    index = min(work_loads, key=work_loads.get)
    faster_client = multi_clients[index]

    if Telegram.MULTI_CLIENT:
        logging.info(f"Client {index} is now serving {request.remote}")

    if faster_client in class_cache:
        tg_connect = class_cache[faster_client]
        logging.debug(f"Using cached ByteStreamer object for client {index}")
    else:
        logging.debug(f"Creating new ByteStreamer object for client {index}")
        tg_connect = ByteStreamer(faster_client)
        class_cache[faster_client] = tg_connect
    logging.debug("before calling get_file_properties")
    file_id = await tg_connect.get_file_properties(chat_id=chat_id, message_id=id)
    logging.debug("after calling get_file_properties")

    if file_id.unique_id[:6] != secure_hash:
        logging.debug(f"Invalid hash for message with ID {id}")
        raise InvalidHash

    file_size = file_id.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace("bytes=", "").split("-")
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = (request.http_range.stop or file_size) - 1

    if (until_bytes > file_size) or (from_bytes < 0) or (until_bytes < from_bytes):
        return web.Response(
            status=416,
            body="416: Range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = 1024 * 1024
    until_bytes = min(until_bytes, file_size - 1)

    offset = from_bytes - (from_bytes % chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = until_bytes % chunk_size + 1

    req_length = until_bytes - from_bytes + 1
    part_count = math.ceil(until_bytes / chunk_size) - \
        math.floor(offset / chunk_size)
    body = tg_connect.yield_file(
        file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size
    )

    mime_type = file_id.mime_type
    file_name = file_id.file_name
    disposition = "attachment"

    if mime_type:
        if not file_name:
            try:
                file_name = f"{secrets.token_hex(2)}.{mime_type.split('/')[1]}"
            except (IndexError, AttributeError):
                file_name = f"{secrets.token_hex(2)}.unknown"
    else:
        if file_name:
            mime_type = mimetypes.guess_type(file_id.file_name)
        else:
            mime_type = "application/octet-stream"
            file_name = f"{secrets.token_hex(2)}.unknown"

    return web.Response(
        status=206 if range_header else 200,
        body=body,
        headers={
            "Content-Type": f"{mime_type}",
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(req_length),
            "Content-Disposition": f'{disposition}; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        },
    )
