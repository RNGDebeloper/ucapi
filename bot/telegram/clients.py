from asyncio import gather, sleep as asleep

from pyrogram import Client

from bot import LOGGER
from bot.config import Telegram
from bot.helper.parser import TokenParser
from bot.telegram import StreamBot, multi_clients, work_loads


async def initialize_clients() -> None:
    multi_clients[0], work_loads[0] = StreamBot, 0
    all_tokens = TokenParser().parse_from_env()
    if not all_tokens:
        LOGGER.info("No additional Bot Clients found, using default client")
        return

    async def start_client(client_id: int, token: str):
        try:
            LOGGER.info(f"Starting Bot Client {client_id}")
            if client_id == len(all_tokens):
                await asleep(1.2)
            client = await Client(
                name=str(client_id),
                api_id=Telegram.API_ID,
                api_hash=Telegram.API_HASH,
                bot_token=token,
                sleep_threshold=Telegram.SLEEP_THRESHOLD,
                no_updates=True,
                in_memory=True,
            ).start()
            work_loads[client_id] = 0
            return client_id, client
        except Exception:
            LOGGER.error(f"Failed starting Client {client_id}", exc_info=True)
            return None

    started = await gather(*[start_client(i, token) for i, token in all_tokens.items()])
    for item in started:
        if item is None:
            continue
        idx, cli = item
        multi_clients[idx] = cli

    if len(multi_clients) > 1:
        Telegram.MULTI_CLIENT = True
        LOGGER.info("Multi-Client Mode Enabled")
    else:
        LOGGER.info("No additional clients initialized, using default client")
