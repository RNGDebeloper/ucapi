from __future__ import annotations

from asyncio import sleep
from typing import Any, Awaitable, Callable

from pyrogram.errors import FloodWait, RPCError


async def tg_retry(
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    retries: int = 3,
    base_delay: float = 1.2,
    **kwargs: Any,
) -> Any:
    attempt = 0
    while True:
        try:
            return await func(*args, **kwargs)
        except FloodWait as err:
            await sleep(err.value + 1)
        except RPCError:
            attempt += 1
            if attempt > retries:
                raise
            await sleep(base_delay * attempt)
