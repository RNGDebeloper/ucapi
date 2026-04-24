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
FORCE_SUB_LINK_CACHE: dict[str, tuple[str, datetime]] = {}


def _prune_cache() -> None:
    now = datetime.now(timezone.utc)
    expired = [k for k, v in SEARCH_CACHE.items() if v.expires_at < now]
    for key in expired:
        SEARCH_CACHE.pop(key, None)


def _prune_force_sub_links() -> None:
    now = datetime.now(timezone.utc)
    expired = [channel for channel, (_, exp) in FORCE_SUB_LINK_CACHE.items() if exp < now]
    for channel in expired:
        FORCE_SUB_LINK_CACHE.pop(channel, None)


def _is_direct_join_link(channel: str) -> bool:
    return channel.startswith("https://t.me/")


async def _resolve_channel_join_link(client: Client, channel: str) -> str | None:
    _prune_force_sub_links()
    cached = FORCE_SUB_LINK_CACHE.get(channel)
    if cached:
        return cached[0]

    if channel.startswith("@"):
        link = f"https://t.me/{channel[1:]}"
        FORCE_SUB_LINK_CACHE[channel] = (link, datetime.now(timezone.utc) + timedelta(hours=6))
        return link

    if _is_direct_join_link(channel):
        FORCE_SUB_LINK_CACHE[channel] = (channel, datetime.now(timezone.utc) + timedelta(hours=6))
        return channel

    try:
        chat = await tg_retry(client.get_chat, channel)
    except Exception:
        return None

    if chat.username:
        link = f"https://t.me/{chat.username}"
        FORCE_SUB_LINK_CACHE[channel] = (link, datetime.now(timezone.utc) + timedelta(hours=6))
        return link

    try:
        invite = await tg_retry(
            client.create_chat_invite_link,
            chat.id,
            name="Force Subscription",
            creates_join_request=False,
        )
        FORCE_SUB_LINK_CACHE[channel] = (invite.invite_link, datetime.now(timezone.utc) + timedelta(hours=1))
        return invite.invite_link
    except Exception:
        try:
            link = await tg_retry(client.export_chat_invite_link, chat.id)
            FORCE_SUB_LINK_CACHE[channel] = (link, datetime.now(timezone.utc) + timedelta(hours=1))
            return link
        except Exception:
            return None


async def is_user_subscribed(client: Client, user_id: int) -> bool:
    if not Telegram.FORCE_SUB_CHANNELS:
        return True

    for channel in Telegram.FORCE_SUB_CHANNELS:
        try:
            member = await tg_retry(client.get_chat_member, channel, user_id)
        except Exception:
            return False
        if member.status in {ChatMemberStatus.BANNED, ChatMemberStatus.LEFT, ChatMemberStatus.RESTRICTED}:
            return False
    return True


async def send_force_sub_prompt(client: Client, message: Message) -> None:
    join_links: list[str] = []
    for channel in Telegram.FORCE_SUB_CHANNELS:
        resolved = await _resolve_channel_join_link(client, channel)
        if resolved:
            join_links.append(resolved)

    extra = ""
    if not join_links:
        extra = "\n\n⚠️ Unable to generate a channel link. Please contact admin."
    text = (
        "🔒 <b>Subscription Required</b>\n\n"
        "Please join all required channels, then tap <b>Check / Try Again</b> to continue."
        f"{extra}"
    )
    await message.reply_text(text, reply_markup=force_sub_keyboard(join_links))


def _parse_file_payload(payload: str) -> tuple[int, int] | None:
    # Supports: file_<msg_id>-100<chat_id>
    match = re.fullmatch(r"file_(\d+)-100(\d+)", payload)
    if match:
        msg_id = int(match.group(1))
        chat_id = int(f"-100{match.group(2)}")
        return chat_id, msg_id

    # Supports old fallback pattern: file_<msg_id>-<chat_suffix>
    fallback = re.fullmatch(r"file_(\d+)-(\d+)", payload)
    if fallback:
        msg_id = int(fallback.group(1))
        chat_id = int(f"-100{fallback.group(2)}")
        return chat_id, msg_id

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
