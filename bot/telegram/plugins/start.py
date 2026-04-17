from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

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
    text = f"Error: <code>{str(err)}</code>"
    try:
        if isinstance(target, CallbackQuery):
            await target.answer(text, show_alert=True)
        else:
            await target.reply_text(text)
    except Exception:
        LOGGER.exception("Failed to deliver error reply")


def is_admin(_, __, message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in Telegram.ADMIN_IDS)


admin_filter = filters.create(is_admin)


@StreamBot.on_message(filters.private & filters.command("start"))
async def start_handler(client: Client, message: Message) -> None:
    try:
        user = message.from_user
        if not user:
            return

        await bot_db.upsert_user(user.id, user.username)
        payload = message.text.split(maxsplit=1)[1].strip() if len(message.command) > 1 else None

        is_subscribed = await is_user_subscribed(client, user.id)
        await bot_db.set_join_status(user.id, is_subscribed)

        if not is_subscribed:
            await bot_db.set_pending_request(user.id, payload)
            await send_force_sub_prompt(message)
            return

        caption = (
            f"👋 <b>Welcome {user.mention}!</b>\n\n"
            "🔎 Send movie/series name to search content instantly.\n"
            "⚡ Fast indexed delivery with pagination support.\n\n"
            "<i>Use /search &lt;keyword&gt; for direct lookup.</i>"
        )
        await tg_retry(
            message.reply_photo,
            photo=Telegram.START_IMAGE_URL,
            caption=caption,
        )

        if payload:
            sent = await deliver_payload(client, message, payload)
            await bot_db.log_request(user.id, sent)
            if sent:
                await bot_db.set_pending_request(user.id, None)
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_callback_query(filters.regex(r"^fs:try_again$"))
async def force_sub_try_again(client: Client, query: CallbackQuery) -> None:
    try:
        user = query.from_user
        if not user:
            return
        subscribed = await is_user_subscribed(client, user.id)
        await bot_db.set_join_status(user.id, subscribed)

        if not subscribed:
            await query.answer("You still need to join all required channels.", show_alert=True)
            return

        user_doc = await bot_db.get_user(user.id) or {}
        pending = user_doc.get("pending_request")
        await query.answer("✅ Subscription verified")
        await query.message.edit_text("✅ Subscription verified! Sending your content...")
        if pending:
            sent = await deliver_payload(client, query.message, pending)
            await bot_db.log_request(user.id, sent)
            if sent:
                await bot_db.set_pending_request(user.id, None)
    except Exception as err:
        await safe_error_reply(query, err)


@StreamBot.on_message(filters.private & (filters.command("search") | (filters.text & ~filters.command(["start", "stats", "users", "broadcast"]))))
async def search_handler(client: Client, message: Message) -> None:
    try:
        if not message.from_user:
            return
        if not await is_user_subscribed(client, message.from_user.id):
            await send_force_sub_prompt(message)
            return

        query = " ".join(message.command[1:]).strip() if message.command else (message.text or "").strip()
        if not query:
            await message.reply_text("Usage: /search <movie or series name>")
            return

        text, keyboard = await build_search_response(query, page=1)
        await message.reply_text(text, reply_markup=keyboard)
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_callback_query(filters.regex(r"^sp:"))
async def search_page_handler(_, query: CallbackQuery) -> None:
    try:
        _, query_id, page = query.data.split(":")
        page_data = await build_search_page(query_id, int(page))
        if not page_data:
            await query.answer("Search session expired. Run search again.", show_alert=True)
            return
        text, keyboard = page_data
        await query.message.edit_text(text, reply_markup=keyboard)
        await query.answer()
    except Exception as err:
        await safe_error_reply(query, err)


@StreamBot.on_callback_query(filters.regex(r"^content:"))
async def content_delivery_handler(client: Client, query: CallbackQuery) -> None:
    try:
        user = query.from_user
        if not user:
            return

        if not await is_user_subscribed(client, user.id):
            await bot_db.set_pending_request(user.id, query.data)
            await query.answer("Join required channels first.", show_alert=True)
            await send_force_sub_prompt(query.message)
            return

        sent = await deliver_payload(client, query.message, query.data)
        await bot_db.log_request(user.id, sent)
        await query.answer("Sent ✅" if sent else "Unable to send", show_alert=not sent)
    except Exception as err:
        await safe_error_reply(query, err)


@StreamBot.on_message(filters.channel & (filters.document | filters.video))
async def auto_index_channel_posts(_, message: Message) -> None:
    try:
        auth_channels = {str(ch) for ch in (Telegram.AUTH_CHANNEL or [])}
        if auth_channels and str(message.chat.id) not in auth_channels:
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
        LOGGER.exception("Failed to index channel post")


@StreamBot.on_message(filters.command("index") & filters.channel)
async def index_history(client: Client, message: Message) -> None:
    try:
        auth_channels = {str(ch) for ch in (Telegram.AUTH_CHANNEL or [])}
        if auth_channels and str(message.chat.id) not in auth_channels:
            await message.reply_text("Channel is not in AUTH_CHANNEL")
            return

        wait = await message.reply_text("🔄 Indexing previous messages. Please wait...")
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

        await wait.edit_text(f"✅ Indexing completed. Imported <b>{imported}</b> files.")
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.command("stats") & admin_filter)
async def stats_handler(_, message: Message) -> None:
    try:
        stats = await bot_db.get_stats()
        text = (
            "📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total users: <b>{stats['total_users']}</b>\n"
            f"✅ Active users: <b>{stats['active_users']}</b>\n"
            f"📨 Total requests: <b>{stats['total_requests']}</b>\n"
            f"🎯 Success: <b>{stats['success_total']}</b>\n"
            f"❌ Failed: <b>{stats['failure_total']}</b>"
        )
        await message.reply_text(text)
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
async def broadcast_handler(client: Client, message: Message) -> None:
    try:
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

        sent = failed = 0
        failures = []
        for index, user_id in enumerate(user_ids, start=1):
            try:
                await tg_retry(message.reply_to_message.copy, chat_id=user_id)
                sent += 1
            except RPCError as err:
                failed += 1
                failures.append({"user_id": user_id, "error": str(err)})
            if index % 50 == 0 or index == total:
                pending = total - index
                await bot_db.update_broadcast_log(log_id, sent, failed, pending, failures[-100:])
                await progress.edit_text(
                    f"📢 Broadcast Progress\nTotal: {total}\nSent: {sent}\nFailed: {failed}\nPending: {pending}"
                )

        await progress.edit_text(f"✅ Broadcast completed.\nSent: {sent}\nFailed: {failed}")
    except Exception as err:
        await safe_error_reply(message, err)


@StreamBot.on_message(filters.private & filters.command(["stats", "users", "broadcast"]))
async def admin_blocked_reply(_, message: Message) -> None:
    if message.from_user and message.from_user.id not in Telegram.ADMIN_IDS:
        await message.reply_text("❌ Admin only command.")


@StreamBot.on_message(filters.private)
async def user_touchpoint(_, message: Message) -> None:
    """Low priority tracker to keep user activity fresh without spam."""

    if not message.from_user:
        return
    await bot_db.upsert_user(message.from_user.id, message.from_user.username)
    if datetime.now(timezone.utc).minute % 15 == 0:
        await bot_db.users.update_one(
            {"user_id": message.from_user.id},
            {"$set": {"last_ping": datetime.now(timezone.utc) + timedelta(minutes=15)}},
        )
