from __future__ import annotations

import re
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
CHANNEL_LINK_CACHE: dict[str, tuple[str, str]] = {}


def _prune_cache() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in SEARCH_CACHE.items() if v.expires_at < now]
    for key in expired:
        SEARCH_CACHE.pop(key, None)


async def _resolve_join_target(client: Client, channel: str) -> tuple[str, str] | None:
    if channel in CHANNEL_LINK_CACHE:
        return CHANNEL_LINK_CACHE[channel]

    if channel.startswith("https://t.me/"):
        title = channel.rsplit("/", 1)[-1]
        CHANNEL_LINK_CACHE[channel] = (title, channel)
        return CHANNEL_LINK_CACHE[channel]

    if channel.startswith("@"):
        title = channel[1:]
        target = (title, f"https://t.me/{title}")
        CHANNEL_LINK_CACHE[channel] = target
        return target

    try:
        chat = await tg_retry(client.get_chat, channel)
    except Exception:
        return None

    if chat.username:
        target = (chat.title or chat.username, f"https://t.me/{chat.username}")
        CHANNEL_LINK_CACHE[channel] = target
        return target

    return None


async def get_join_targets(client: Client) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for channel in Telegram.FORCE_SUB_CHANNELS:
        resolved = await _resolve_join_target(client, channel)
        if resolved:
            targets.append(resolved)
    return targets


async def is_user_subscribed(client: Client, user_id: int) -> bool:
    if not Telegram.FORCE_SUB_CHANNELS:
        return True

    for channel in Telegram.FORCE_SUB_CHANNELS:
        try:
            member = await tg_retry(client.get_chat_member, channel, user_id)
        except Exception:
            return False
        if member.status in {ChatMemberStatus.BANNED, ChatMemberStatus.LEFT}:
            return False
    return True


async def send_force_sub_prompt(client: Client, message: Message) -> None:
    join_targets = await get_join_targets(client)
    extra = ""
    if not join_targets:
        extra = "\n\n⚠️ Join links are unavailable for private channels. Contact admin for invite links."

    text = (
        "🔒 <b>Subscription Required</b>\n\n"
        "Please join required channel(s) and press <b>Check / Try Again</b>."
        f"{extra}"
    )
    await message.reply_text(text, reply_markup=force_sub_keyboard(join_targets))


def _parse_file_payload(payload: str) -> tuple[int, int] | None:
    # file_<msg_id>-100<chat_id_suffix>
    match = re.fullmatch(r"file_(\d+)-100(\d+)", payload)
    if match:
        return int(f"-100{match.group(2)}"), int(match.group(1))

    # fallback: file_<msg_id>-<chat_suffix>
    fallback = re.fullmatch(r"file_(\d+)-(\d+)", payload)
    if fallback:
        return int(f"-100{fallback.group(2)}"), int(fallback.group(1))

    return None


async def deliver_payload(client: Client, message: Message, payload: str) -> bool:
    parsed = _parse_file_payload(payload)
    if parsed:
        chat_id, msg_id = parsed
        await tg_retry(client.copy_message, message.chat.id, chat_id, msg_id)
        return True

    if payload.startswith("content:"):
        _, chat_id, msg_id = payload.split(":", 2)
        await tg_retry(client.copy_message, message.chat.id, int(chat_id), int(msg_id))
        return True

    return False


async def build_search_response(query: str, page: int) -> tuple[str, object | None]:
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
    if not state or page < 1:
        return None

    items, total = await bot_db.search_content(state.query, page, Telegram.SEARCH_PAGE_SIZE)
    if total == 0:
        return None

    total_pages = ceil(total / Telegram.SEARCH_PAGE_SIZE)
    if page > total_pages:
        return None

    text = f"🔎 Results for: <code>{state.query}</code>\nPage <b>{page}/{total_pages}</b>"
    keyboard = search_results_keyboard(items, page, total_pages, query_id)
    return text, keyboard
