from asyncio import gather, create_task
from bot.helper.database import Database
from bot.telegram import StreamBot
from bot.config import Telegram


db = Database()


def _public_chat_id(chat_id):
    return str(chat_id).replace("-100", "")


def _stream_url(chat_id, file_id, file_hash):
    return f"/{_public_chat_id(chat_id)}/stream?id={file_id}&hash={file_hash}"


def _watch_url(chat_id, file_id, file_hash):
    return f"/watch/{_public_chat_id(chat_id)}?id={file_id}&hash={file_hash}"


async def get_chats():
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]

    return [{"chat-id": chat.id, "title": chat.title or chat.first_name, "type": chat.type.name} for chat in await gather(*[create_task(StreamBot.get_chat(int(channel_id))) for channel_id in AUTH_CHANNEL])]


async def posts_chat(channels):
    return [
        {
            "id": channel["chat-id"],
            "chat_id": channel["chat-id"],
            "public_id": _public_chat_id(channel["chat-id"]),
            "title": channel["title"],
            "type": channel["type"],
            "thumbnail": f"/api/thumb/{channel['chat-id']}",
            "url": f"/channel/{_public_chat_id(channel['chat-id'])}",
        }
        for channel in channels
    ]


async def post_playlist(playlists):
    return [
        {
            "id": playlist["_id"],
            "title": playlist["name"],
            "name": playlist["name"],
            "type": "folder",
            "thumbnail": playlist.get("thumbnail"),
            "parent_folder": playlist.get("parent_folder"),
            "url": f"/playlist?db={playlist['_id']}",
        }
        for playlist in playlists
    ]


async def posts_db_file(posts):
    return [
        {
            "id": post["_id"],
            "file_id": post["file_id"],
            "chat_id": post["chat_id"],
            "public_chat_id": _public_chat_id(post["chat_id"]),
            "title": post["title"],
            "name": post.get("name", post["title"]),
            "size": post.get("size"),
            "file_size": post.get("size"),
            "mime_type": post.get("file_type"),
            "file_type": post.get("file_type"),
            "thumbnail": post.get("thumbnail"),
            "hash": post.get("hash"),
            "parent_folder": post.get("parent_folder"),
            "type": "file",
            "stream_url": _stream_url(post["chat_id"], post["file_id"], post.get("hash")),
            "watch_url": _watch_url(post["chat_id"], post["file_id"], post.get("hash")),
        }
        for post in posts
    ]
