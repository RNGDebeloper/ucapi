from os.path import splitext
import re
from asyncio import gather, to_thread
from bot.config import Telegram
from bot.helper.database import Database
from bot.telegram import StreamBot, UserBot
from bot.helper.file_size import get_readable_file_size
from bot.helper.cache import get_cache, save_cache
from bot.helper.tmdb import fetch_poster, FALLBACK_POSTER


db = Database()


def normalize_post_title(caption, fallback_name=None):
    raw_title = caption or fallback_name or "Untitled"
    title, _ = splitext(raw_title)
    title = re.sub(r"[.,|_\',]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title or "Untitled"


async def fetch_message(chat_id, message_id):
    try:
        message = await StreamBot.get_messages(chat_id, message_id)
        return message
    except Exception:
        return None


async def get_messages(chat_id, first_message_id, last_message_id, batch_size=50):
    messages = []
    current_message_id = first_message_id
    while current_message_id <= last_message_id:
        batch_message_ids = list(range(current_message_id, min(current_message_id + batch_size, last_message_id + 1)))
        tasks = [fetch_message(chat_id, message_id) for message_id in batch_message_ids]
        batch_messages = await gather(*tasks)
        for message in batch_messages:
            if message:
                if file := message.video or message.document:
                    title = normalize_post_title(message.caption, file.file_name)
                    messages.append({"msg_id": message.id, "title": title,
                                     "hash": file.file_unique_id[:6], "size": get_readable_file_size(file.file_size),
                                     "type": file.mime_type, "chat_id": str(chat_id)})
        current_message_id += batch_size
    return messages


async def _build_post_entry(post):
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


async def get_files(chat_id, page=1):
    if Telegram.SESSION_STRING == '':
        return await db.list_tgfiles(id=chat_id, page=page)
    if cache := get_cache(chat_id, int(page)):
        return cache
    history = []
    async for post in UserBot.get_chat_history(chat_id=int(chat_id), limit=50, offset=(int(page) - 1) * 50):
        history.append(post)

    built_posts = await gather(*[_build_post_entry(post) for post in history])
    posts = [post for post in built_posts if post]
    save_cache(chat_id, {"posts": posts}, page)
    return posts


async def posts_file(posts, chat_id):
    phtml = """
            <div class="col nm-rail-col">
                <article class="nm-media-card nm-video-card">
                    <input type="checkbox" class="admin-only nm-select-box"
                        onchange="checkSendButton()" id="selectCheckbox"
                        data-id="{id}|{hash}|{title}|{size}|{type}|{img}">
                    <a href="/watch/{chat_id}?id={id}&hash={hash}" class="nm-media-link">
                        <div class="nm-media-poster-wrap">
                            <img src="{img}" class="nm-media-poster"
                                loading="lazy" alt="{title}"
                                onerror="this.onerror=null;this.src='https://cdn-icons-png.flaticon.com/512/565/565547.png';">
                            <div class="nm-media-overlay"></div>
                            <div class="nm-play-chip"><i class="bi bi-play-fill"></i></div>
                        </div>
                        <div class="nm-media-body">
                            <span class="nm-media-tag">Featured</span>
                            <h6 class="nm-media-title">{title}</h6>
                            <div class="nm-meta-row"><span class="nm-media-badge">{type}</span><span class="nm-media-badge nm-media-badge--info">{size}</span></div>
                        </div>
                    </a>
                </article>
            </div>
"""

    return ''.join(phtml.format(chat_id=str(chat_id).replace("-100", ""), id=post["msg_id"], img=post["poster_url"], title=post["title"], hash=post["hash"], size=post['size'], type=post['type']) for post in posts)
