from asyncio import gather, to_thread

from bot.config import Telegram
from bot.helper.database import Database
from bot.telegram import UserBot
from bot.helper.file_size import get_readable_file_size
from bot.helper.index import normalize_post_title
from bot.helper.tmdb import fetch_poster, FALLBACK_POSTER


db = Database()


async def _build_search_entry(post):
    file = post.video or post.document
    if not file:
        return None

    title = normalize_post_title(post.caption, file.file_name)
    poster = await to_thread(fetch_poster, title)
    return {
        "msg_id": post.id,
        "title": title,
        "poster_url": poster or FALLBACK_POSTER,
        "hash": file.file_unique_id[:6],
        "size": get_readable_file_size(file.file_size),
        "type": file.mime_type,
    }


async def search(chat_id, query, page):
    if Telegram.SESSION_STRING == '':
        return await db.search_tgfiles(id=chat_id, query=query, page=page)

    matches = []
    async for post in UserBot.search_messages(chat_id=int(chat_id), limit=50, query=str(query), offset=(int(page) - 1) * 50):
        matches.append(post)

    built_posts = await gather(*[_build_search_entry(post) for post in matches])
    return [post for post in built_posts if post]
