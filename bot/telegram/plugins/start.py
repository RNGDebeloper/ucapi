from __future__ import annotations

import re
from asyncio import sleep

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery, Message

from bot import LOGGER
from bot.config import Telegram
from bot.helper.bot_database import bot_db
from bot.helper.retry import tg_retry
from bot.telegram import StreamBot
from bot.telegram.services import (
    build_search_page,
    build_search_response,
    deliver_payload,
    is_user_subscribed,
    send_force_sub_prompt,
)


async def safe_error_reply(target: Message | CallbackQuery, err: Exception) -> None:
    error_text = f"Error: <code>{str(err)}</code>"
    try:
        if isinstance(target, CallbackQuery):
            await target.answer(error_text, show_alert=True)
        else:
            await target.reply_text(error_text)
    except Exception:
        LOGGER.exception("Unable to send fallback error message")


def is_admin(_, __, message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in Telegram.ADMIN_IDS)


admin_filter = filters.create(is_admin)


@StreamBot.on_message(filters.private & filters.command("start"))
async def start_handler(client: Client, message: Message) -> None:
    try:
        if not message.from_user:
            return

        user_id = message.from_user.id
        await bot_db.upsert_user(user_id, message.from_user.username)

        payload = None
        if message.text and len(message.text.split(maxsplit=1)) > 1:
            payload = message.text.split(maxsplit=1)[1].strip()

        subscribed = await is_user_subscribed(client, user_id)
        await bot_db.set_join_status(user_id, subscribed)
        if not subscribed:
            await bot_db.set_pending_request(user_id, payload)
            await send_force_sub_prompt(message)
            return

        caption = (
            f"👋 <b>Welcome, {message.from_user.mention}!</b>\n\n"
            "🔎 Search movies/series using <code>/search keyword</code>\n"
            "📦 Indexed delivery with pagination and fast response\n"
            "✅ Access unlocked after subscription check"
        )
        await tg_retry(message.reply_photo, photo=Telegram.START_IMAGE_URL, caption=caption)

        if payload:
            sent = await deliver_payload(client, message, payload)
            await bot_db.log_request(user_id, sent)
            if sent:
                await bot_db.set_pending_request(user_id, None)
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_callback_query(filters.regex(r"^fs:try_again$"))
async def force_sub_try_again(client: Client, query: CallbackQuery) -> None:
    try:
        if not query.from_user or not query.message:
            return

        user_id = query.from_user.id
        subscribed = await is_user_subscribed(client, user_id)
        await bot_db.set_join_status(user_id, subscribed)

        if not subscribed:
            await query.answer("You still need to join all required channels.", show_alert=True)
            return

        user_doc = await bot_db.get_user(user_id) or {}
        pending = user_doc.get("pending_request")
        await query.answer("✅ Subscription verified", show_alert=False)

        if pending:
            sent = await deliver_payload(client, query.message, pending)
            await bot_db.log_request(user_id, sent)
            if sent:
                await bot_db.set_pending_request(user_id, None)
    except Exception as err:
        await safe_error_reply(query, err)


@StreamBot.on_message(filters.private & filters.command("search"))
async def search_command_handler(client: Client, message: Message) -> None:
    try:
        if not message.from_user:
            return
        if not await is_user_subscribed(client, message.from_user.id):
            await send_force_sub_prompt(message)
            return

        query = " ".join(message.command[1:]).strip()
        if not query:
            await message.reply_text("Usage: /search <movie or series name>")
            return

        text, keyboard = await build_search_response(query, page=1)
        await message.reply_text(text, reply_markup=keyboard)
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
async def search_text_handler(client: Client, message: Message) -> None:
    try:
        if not message.from_user or not message.text:
            return
        if not await is_user_subscribed(client, message.from_user.id):
            await send_force_sub_prompt(message)
            return

        query = message.text.strip()
        if len(query) < 2:
            await message.reply_text("Please send at least 2 characters to search.")
            return

        text, keyboard = await build_search_response(query, page=1)
        await message.reply_text(text, reply_markup=keyboard)
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_callback_query(filters.regex(r"^sp:"))
async def search_page_handler(_, query: CallbackQuery) -> None:
    try:
        if not query.message:
            return
        _, query_id, page_raw = query.data.split(":")
        page_data = await build_search_page(query_id, int(page_raw))
        if not page_data:
            await query.answer("Search session expired. Run /search again.", show_alert=True)
            return

        text, keyboard = page_data
        await query.message.edit_text(text, reply_markup=keyboard)
        await query.answer()
    except Exception as err:
        await safe_error_reply(query, err)


@StreamBot.on_callback_query(filters.regex(r"^content:"))
async def content_delivery_handler(client: Client, query: CallbackQuery) -> None:
    try:
        if not query.from_user or not query.message:
            return

        user_id = query.from_user.id
        if not await is_user_subscribed(client, user_id):
            await bot_db.set_pending_request(user_id, query.data)
            await query.answer("Join required channels first.", show_alert=True)
            await send_force_sub_prompt(query.message)
            return

        sent = await deliver_payload(client, query.message, query.data)
        await bot_db.log_request(user_id, sent)
        await query.answer("Sent ✅" if sent else "Unable to send", show_alert=not sent)
    except Exception as err:
        await safe_error_reply(query, err)


@StreamBot.on_message(filters.channel & (filters.document | filters.video))
async def auto_index_channel_posts(_, message: Message) -> None:
    try:
        allowed = {str(ch) for ch in Telegram.AUTH_CHANNEL}
        if allowed and str(message.chat.id) not in allowed:
            return

        file = message.document or message.video
        if not file:
            return

        raw_title = file.file_name or message.caption or file.file_unique_id
        title = re.sub(r"[.,|_'-]", " ", raw_title).strip()
        tags = [token.lower() for token in re.findall(r"\w+", title)[:20]]
        await bot_db.add_content(
            chat_id=message.chat.id,
            msg_id=message.id,
            file_id=file.file_id,
            file_unique_id=file.file_unique_id,
            title=title,
            tags=tags,
            mime_type=file.mime_type,
            file_size=file.file_size,
        )
    except Exception:
        LOGGER.exception("Auto-index failure")


@StreamBot.on_message(filters.command("index") & filters.channel)
async def index_history(client: Client, message: Message) -> None:
    try:
        allowed = {str(ch) for ch in Telegram.AUTH_CHANNEL}
        if allowed and str(message.chat.id) not in allowed:
            await message.reply_text("Channel is not in AUTH_CHANNEL")
            return

        notice = await message.reply_text("🔄 Indexing channel history. Please wait...")
        imported = 0
        async for msg in client.get_chat_history(message.chat.id, limit=5000):
            file = msg.document or msg.video
            if not file:
                continue
            raw_title = file.file_name or msg.caption or file.file_unique_id
            title = re.sub(r"[.,|_'-]", " ", raw_title).strip()
            tags = [token.lower() for token in re.findall(r"\w+", title)[:20]]
            await bot_db.add_content(
                chat_id=msg.chat.id,
                msg_id=msg.id,
                file_id=file.file_id,
                file_unique_id=file.file_unique_id,
                title=title,
                tags=tags,
                mime_type=file.mime_type,
                file_size=file.file_size,
            )
            imported += 1
            if imported % 200 == 0:
                await sleep(0)

        await notice.edit_text(f"✅ Indexing completed. Imported <b>{imported}</b> files.")
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.command("stats") & admin_filter)
async def stats_handler(_, message: Message) -> None:
    try:
        stats = await bot_db.get_stats()
        await message.reply_text(
            "📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total users: <b>{stats['total_users']}</b>\n"
            f"✅ Active users: <b>{stats['active_users']}</b>\n"
            f"📨 Total requests: <b>{stats['total_requests']}</b>\n"
            f"🎯 Success: <b>{stats['success_total']}</b>\n"
            f"❌ Failed: <b>{stats['failure_total']}</b>"
        )
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.command("users") & admin_filter)
async def users_handler(_, message: Message) -> None:
    try:
        users = await bot_db.list_user_ids()
        preview = ", ".join(map(str, users[:20])) if users else "No users"
        await message.reply_text(f"👥 Total users: <b>{len(users)}</b>\n<code>{preview}</code>")
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.command("broadcast") & admin_filter)
async def broadcast_handler(_, message: Message) -> None:
    try:
        if not message.from_user:
            return
        if not message.reply_to_message:
            await message.reply_text("Reply to a message with /broadcast")
            return

        user_ids = await bot_db.list_user_ids()
        total = len(user_ids)
        if total == 0:
            await message.reply_text("No users available for broadcast.")
            return

        progress = await message.reply_text(f"📢 Broadcast started for {total} users...")
        log_id = await bot_db.create_broadcast_log(message.from_user.id, message.reply_to_message.id, total)

        sent = 0
        failed = 0
        failures: list[dict] = []

        for idx, user_id in enumerate(user_ids, start=1):
            try:
                await tg_retry(message.reply_to_message.copy, chat_id=user_id)
                sent += 1
            except RPCError as err:
                failed += 1
                failures.append({"user_id": user_id, "error": str(err)})

            if idx % 50 == 0 or idx == total:
                pending = total - idx
                await bot_db.update_broadcast_log(log_id, sent, failed, pending, failures[-100:])
                await progress.edit_text(
                    f"📢 Broadcast Progress\nTotal: {total}\nSent: {sent}\nFailed: {failed}\nPending: {pending}"
                )
                await sleep(0)

        await progress.edit_text(f"✅ Broadcast completed.\nSent: {sent}\nFailed: {failed}")
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.command(["stats", "users", "broadcast"]))
async def admin_guard_handler(_, message: Message) -> None:
    if message.from_user and message.from_user.id not in Telegram.ADMIN_IDS:
        await message.reply_text("❌ Admin only command.")


@StreamBot.on_message(filters.private)
async def touchpoint_handler(_, message: Message) -> None:
    if not message.from_user:
        return
    await bot_db.upsert_user(message.from_user.id, message.from_user.username)
