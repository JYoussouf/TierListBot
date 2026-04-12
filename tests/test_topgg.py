from __future__ import annotations

import asyncio

from TierListBot.services.topgg import TopGGClient


class FakeResponse:
    def __init__(self, status: int, text: str = "ok"):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.posts = []

    def post(self, url, json, headers, timeout):
        self.posts.append((url, json, headers, timeout))
        status = self.statuses.pop(0)
        return FakeResponse(status=status, text="error" if status >= 400 else "ok")


async def _run_topgg_post_stats_success_after_retry():
    session = FakeSession([500, 200])
    client = TopGGClient(session, bot_id="123", token="secret")

    await client.post_stats(42)
    assert len(session.posts) == 2
    assert session.posts[0][1] == {"server_count": 42}


async def _run_topgg_post_stats_failure_raises():
    session = FakeSession([500, 500, 500])
    client = TopGGClient(session, bot_id="123", token="secret")

    try:
        await client.post_stats(42)
        assert False, "expected an exception after retries"
    except Exception:
        pass


def test_topgg_post_stats_success_after_retry_sync():
    asyncio.run(_run_topgg_post_stats_success_after_retry())


def test_topgg_post_stats_failure_raises_sync():
    asyncio.run(_run_topgg_post_stats_failure_raises())
