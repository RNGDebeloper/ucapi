from __future__ import annotations

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def force_sub_keyboard(channels: list[str]) -> InlineKeyboardMarkup:
    join_buttons = []
    for channel in channels:
        label = channel.replace("@", "")
        if channel.startswith("-100"):
            continue
        join_buttons.append([InlineKeyboardButton(f"📢 Join {label}", url=f"https://t.me/{label}")])
    join_buttons.append([InlineKeyboardButton("✅ Try Again", callback_data="fs:try_again")])
    return InlineKeyboardMarkup(join_buttons)


def search_results_keyboard(items: list[dict], page: int, total_pages: int, query_id: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"🎬 {item['title'][:45]}", callback_data=f"content:{item['chat_id']}:{item['msg_id']}")]
        for item in items
    ]
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"sp:{query_id}:{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"sp:{query_id}:{page+1}"))
    if nav_row:
        rows.append(nav_row)
    return InlineKeyboardMarkup(rows)
