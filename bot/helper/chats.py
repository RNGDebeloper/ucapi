from asyncio import gather, create_task
from bot.helper.database import Database
from bot.telegram import StreamBot
from bot.config import Telegram

db = Database()

async def get_chats():
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]
    
    return [{"chat-id": chat.id, "title": chat.title or chat.first_name, "type": chat.type.name} for chat in await gather(*[create_task(StreamBot.get_chat(int(channel_id))) for channel_id in AUTH_CHANNEL])]



def _public_chat_id(chat_id):
    return str(chat_id).replace("-100", "")


async def posts_chat(channels):
    return [
        {
            **channel,
            "public_id": _public_chat_id(channel["chat-id"]),
            "thumbnail_url": f"/api/thumb/{channel['chat-id']}",
            "channel_url": f"/channel/{_public_chat_id(channel['chat-id'])}",
        }
        for channel in channels
    ]


async def post_playlist(playlists):
    return [
        {
            "id": str(playlist["_id"]),
            "parent_folder": playlist["parent_folder"],
            "name": playlist["name"],
            "thumbnail": playlist["thumbnail"],
            "type": playlist["type"],
            "playlist_url": f"/playlist?db={playlist['_id']}",
        }
        for playlist in playlists
    ]


async def posts_db_file(posts):
    items = []
    for post in posts:
        public_chat_id = _public_chat_id(post["chat_id"])
        message_id = post["file_id"]
        secure_hash = post["hash"]
        items.append({
            "id": str(post["_id"]),
            "chat_id": post["chat_id"],
            "public_chat_id": public_chat_id,
            "parent_folder": post["parent_folder"],
            "file_id": message_id,
            "hash": secure_hash,
            "title": post["title"],
            "thumbnail": post["thumbnail"],
            "size": post["size"],
            "file_type": post["file_type"],
            "type": post["type"],
            "watch_url": f"/watch/{public_chat_id}?id={message_id}&hash={secure_hash}",
            "download_url": f"/{public_chat_id}/{message_id}?id={message_id}&hash={secure_hash}",
        })
    return items
