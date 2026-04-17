from asyncio import get_event_loop, sleep as asleep
from traceback import format_exc

from aiohttp import web
from pyrogram import idle

from bot import __version__, LOGGER
from bot.config import Telegram
from bot.helper.bot_database import bot_db
from bot.server import web_server
from bot.telegram import StreamBot, UserBot
from bot.telegram.clients import initialize_clients

loop = get_event_loop()


def _validate_restricted_bot() -> None:
    username = (StreamBot.me.username or "").lower()
    if username != Telegram.REQUIRED_BOT_USERNAME:
        raise RuntimeError(
            f"Restricted bot check failed. Expected @{Telegram.REQUIRED_BOT_USERNAME}, got @{username or 'unknown'}."
        )

    token_prefix = Telegram.BOT_TOKEN.split(":", 1)[0].strip()
    if token_prefix and token_prefix != str(StreamBot.me.id):
        raise RuntimeError("BOT_TOKEN does not belong to the connected bot account.")


async def start_services() -> None:
    LOGGER.info(f"Initializing Surf-TG v-{__version__}")
    await bot_db.ensure_indexes()
    await asleep(0.8)

    await StreamBot.start()
    _validate_restricted_bot()
    StreamBot.username = StreamBot.me.username
    LOGGER.info(f"Bot Client : [@{StreamBot.username}]")

    if Telegram.SESSION_STRING:
        await UserBot.start()
        UserBot.username = UserBot.me.username or UserBot.me.first_name or UserBot.me.id
        LOGGER.info(f"User Client : {UserBot.username}")

    await asleep(0.8)
    LOGGER.info("Initializing Multi Clients")
    await initialize_clients()

    LOGGER.info("Initializing Surf Web Server..")
    server = web.AppRunner(await web_server())
    await server.setup()
    await web.TCPSite(server, "0.0.0.0", Telegram.PORT).start()

    LOGGER.info("Surf-TG Started")
    await idle()


async def stop_clients() -> None:
    if StreamBot.is_connected:
        await StreamBot.stop()
    if Telegram.SESSION_STRING and UserBot.is_connected:
        await UserBot.stop()


if __name__ == "__main__":
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info("Service Stopping...")
    except Exception:
        LOGGER.error(format_exc())
    finally:
        loop.run_until_complete(stop_clients())
        loop.stop()
