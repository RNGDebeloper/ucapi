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


async def posts_chat(channels):
    phtml = """
            <div class="col nm-platform-col">
                <a href="/channel/{cid}" class="nm-platform-link" aria-label="Open {title}">
                    <article class="nm-platform-card">
                        <div class="nm-platform-logo-wrap">
                            <img src="{img}"
                                class="nm-platform-logo" loading="lazy" alt="{title}" onerror="this.onerror=null;this.src='/static/logo.png';">
                        </div>
                        <div class="nm-platform-copy">
                            <span class="nm-platform-kicker">Telegram OTT</span>
                            <h6 class="nm-platform-title">{title}</h6>
                            <span class="nm-platform-pill">{ctype}</span>
                        </div>
                    </article>
                </a>
            </div>
"""
    return ''.join(phtml.format(cid=str(channel["chat-id"]).replace("-100", ""), img=f"/api/thumb/{channel['chat-id']}", title=channel["title"], ctype=channel['type']) for channel in channels)


async def post_playlist(playlists):
    dhtml = """
    <div class="col nm-rail-col">
        <article class="nm-media-card nm-folder-card">
            <a href="" onclick="openEditPopupForm(event, '{img}', '{ctype}', '{cid}', '{title}')"
                class="admin-only nm-edit-btn" data-bs-toggle="modal" data-bs-target="#editFolderModal"><i class="bi bi-pencil-square"></i>
            </a>
            <a href="/playlist?db={cid}" class="nm-media-link">
                <div class="nm-media-poster-wrap">
                    <img src="{img}"
                        class="nm-media-poster" loading="lazy" alt="{title}" onerror="this.onerror=null;this.src='/static/thumbnail.jpg';">
                    <div class="nm-media-overlay"></div>
                    <div class="nm-play-chip"><i class="bi bi-play-fill"></i></div>
                </div>
                <div class="nm-media-body">
                    <span class="nm-media-tag">Collection</span>
                    <h6 class="nm-media-title">{title}</h6>
                    <div class="nm-meta-row"><span class="nm-media-badge">Folder</span></div>
                </div>
            </a>
        </article>
    </div>
    """

    return ''.join(dhtml.format(cid=playlist["_id"], img=playlist["thumbnail"], title=playlist["name"], ctype=playlist['parent_folder']) for playlist in playlists)


async def posts_db_file(posts):
    phtml = """
    <div class="col nm-rail-col">
        <article class="nm-media-card">
            <a href=""
                onclick="openPostEditPopupForm(event, '{img}', '{type}', '{size}', '{title}', '{cid}', '{ctype}')"
                class="admin-only nm-edit-btn" data-bs-toggle="modal" data-bs-target="#editModal"><i
                    class="bi bi-pencil-square"></i></a>
            <a href="/watch/{chat_id}?id={id}&hash={hash}" class="nm-media-link">
                <div class="nm-media-poster-wrap">
                    <img src="{img}"
                        class="nm-media-poster" loading="lazy" alt="{title}" onerror="this.onerror=null;this.src='/static/thumbnail.jpg';">
                    <div class="nm-media-overlay"></div>
                    <div class="nm-play-chip"><i class="bi bi-play-fill"></i></div>
                </div>
                <div class="nm-media-body">
                    <span class="nm-media-tag">Telegram Library</span>
                    <h6 class="nm-media-title">{title}</h6>
                    <div class="nm-meta-row"><span class="nm-media-badge">{type}</span><span class="nm-media-badge nm-media-badge--info">{size}</span></div>
                </div>
            </a>
        </article>
    </div>
"""
    return ''.join(phtml.format(cid=post["_id"], chat_id=str(post["chat_id"]).replace("-100", ""), id=post["file_id"], img=post["thumbnail"], title=post["title"], hash=post["hash"], size=post['size'], type=post['file_type'], ctype=post["parent_folder"]) for post in posts)
