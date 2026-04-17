from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _channel_button(channel: str) -> InlineKeyboardButton | None:
    if channel.startswith("https://t.me/"):
        return InlineKeyboardButton("📢 Join Channel", url=channel)
    if channel.startswith("@"):
        label = channel[1:]
        return InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{label}")
    return None


def force_sub_keyboard(channels: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, channel in enumerate(channels, start=1):
        btn = _channel_button(channel)
        if not btn:
            continue

        if len(channels) > 1:
            rows.append([InlineKeyboardButton(f"📢 Join Channel {idx}", url=btn.url)])
            continue

        rows.append([btn])
    rows.append([InlineKeyboardButton("✅ Check / Try Again", callback_data="fs:try_again")])
    return InlineKeyboardMarkup(rows)


def search_results_keyboard(items: list[dict], page: int, total_pages: int, query_id: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"🎬 {item['title'][:45]}", callback_data=f"content:{item['chat_id']}:{item['msg_id']}")]
        for item in items
    ]

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sp:{query_id}:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sp:{query_id}:{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    return InlineKeyboardMarkup(rows)
