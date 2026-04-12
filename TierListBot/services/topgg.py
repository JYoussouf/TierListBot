from __future__ import annotations

import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)


class TopGGClient:
    def __init__(self, session: aiohttp.ClientSession, bot_id: str, token: str):
        self.session = session
        self.bot_id = bot_id
        self.token = token

    async def post_stats(self, guild_count: int) -> None:
        url = f"https://top.gg/api/bots/{self.bot_id}/stats"
        payload = {"server_count": guild_count}
        headers = {"Authorization": self.token, "Content-Type": "application/json"}

        delays = [0, 2, 5]
        last_error: Exception | None = None
        for delay in delays:
            if delay:
                await asyncio.sleep(delay)
            try:
                async with self.session.post(
                    url, json=payload, headers=headers, timeout=20
                ) as response:
                    if 200 <= response.status < 300:
                        logger.info("Posted top.gg stats: guild_count=%s", guild_count)
                        return
                    body = await response.text()
                    raise RuntimeError(
                        f"top.gg stats post failed: status={response.status} body={body[:200]}"
                    )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("top.gg stats post retrying after error: %s", exc)

        if last_error:
            raise last_error
