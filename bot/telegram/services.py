from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import uuid4

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import Message

from bot.config import Telegram
from bot.helper.bot_database import bot_db
from bot.helper.retry import tg_retry
from bot.telegram.keyboards import force_sub_keyboard, search_results_keyboard


@dataclass
class SearchState:
    query: str
    expires_at: datetime


SEARCH_CACHE: dict[str, SearchState] = {}


def _prune_cache() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in SEARCH_CACHE.items() if v.expires_at < now]
    for key in expired:
        SEARCH_CACHE.pop(key, None)


async def is_user_subscribed(client: Client, user_id: int) -> bool:
    channels = Telegram.FORCE_SUB_CHANNELS
    if not channels:
        return True

    for channel in channels:
        try:
            member = await tg_retry(client.get_chat_member, channel, user_id)
        except Exception:
            return False
        if member.status in {ChatMemberStatus.BANNED, ChatMemberStatus.LEFT}:
            return False
    return True


async def send_force_sub_prompt(message: Message) -> None:
    text = (
        "🔒 <b>Subscription Required</b>\n\n"
        "Please join all required channels, then tap <b>Try Again</b> to continue."
    )
    await message.reply_text(text, reply_markup=force_sub_keyboard(Telegram.FORCE_SUB_CHANNELS))


async def deliver_payload(client: Client, message: Message, payload: str) -> bool:
    if payload.startswith("file_"):
        parts = payload.replace("file_", "").split("-")
        if len(parts) != 2:
            return False
        msg_id = int(parts[0])
        chat_id = int(f"-{parts[1]}")
        await tg_retry(client.copy_message, message.chat.id, chat_id, msg_id)
        return True

    if payload.startswith("content:"):
        _, chat_id, msg_id = payload.split(":", 2)
        await tg_retry(client.copy_message, message.chat.id, int(chat_id), int(msg_id))
        return True

    return False


async def build_search_response(query: str, page: int) -> tuple[str, object]:
    items, total = await bot_db.search_content(query, page, Telegram.SEARCH_PAGE_SIZE)
    if total == 0:
        return "❌ No results found. Try another keyword.", None

    total_pages = ceil(total / Telegram.SEARCH_PAGE_SIZE)
    query_id = uuid4().hex[:10]
    _prune_cache()
    SEARCH_CACHE[query_id] = SearchState(
        query=query,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    text = f"🔎 Results for: <code>{query}</code>\nPage <b>{page}/{total_pages}</b>"
    keyboard = search_results_keyboard(items, page, total_pages, query_id)
    return text, keyboard


async def build_search_page(query_id: str, page: int) -> tuple[str, object] | None:
    _prune_cache()
    state = SEARCH_CACHE.get(query_id)
    if not state:
        return None

    items, total = await bot_db.search_content(state.query, page, Telegram.SEARCH_PAGE_SIZE)
    if total == 0:
        return None

    total_pages = ceil(total / Telegram.SEARCH_PAGE_SIZE)
    text = f"🔎 Results for: <code>{state.query}</code>\nPage <b>{page}/{total_pages}</b>"
    keyboard = search_results_keyboard(items, page, total_pages, query_id)
    return text, keyboard
