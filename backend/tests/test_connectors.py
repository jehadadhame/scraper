import asyncio
from types import SimpleNamespace

import feedparser
import pytest

from app.connectors.base import ConnectorUnavailable
from app.connectors.discord import DiscordConnector
from app.connectors.facebook import FacebookConnector
from app.connectors.news import NewsConnector
from app.connectors.telegram import TelegramConnector, telegram_message_url, telegram_target
from app.models import Source


def test_news_cursor_skips_seen_entries(monkeypatch) -> None:
    parsed_feed = feedparser.parse(
        b"""
        <rss><channel><title>Local feed</title>
        <item><guid>one</guid><title>Water problem</title><description>Need water</description></item>
        <item><guid>two</guid><title>Medicine update</title><description>Hospital needs medicine</description></item>
        </channel></rss>
        """
    )
    connector = NewsConnector()

    async def fake_read_feed(_: str):
        return parsed_feed

    monkeypatch.setattr(connector, "_read_feed", fake_read_feed)
    source = Source(platform="news", label="Feed", url="https://feed.test")
    backfill = asyncio.run(connector.backfill(source))
    source.cursor_state = backfill.cursor_state
    poll = asyncio.run(connector.poll(source))

    assert len(backfill.items) == 2
    assert poll.items == []
    assert set(source.cursor_state["seen_ids"]) == {"one", "two"}


def test_discord_requires_bot_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.connectors.discord.get_settings",
        lambda: SimpleNamespace(discord_bot_token=None),
    )
    source = Source(platform="discord", label="Channel", external_id="123")

    with pytest.raises(ConnectorUnavailable, match="DISCORD_BOT_TOKEN"):
        asyncio.run(DiscordConnector().poll(source))


def test_facebook_is_explicitly_gated() -> None:
    source = Source(platform="facebook", label="Page", external_id="page")

    with pytest.raises(ConnectorUnavailable, match="approved Meta"):
        asyncio.run(FacebookConnector().poll(source))


def test_telegram_requires_session_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.connectors.telegram.get_settings",
        lambda: SimpleNamespace(telegram_api_id=None, telegram_api_hash=None),
    )

    with pytest.raises(ConnectorUnavailable, match="TELEGRAM_API_ID"):
        asyncio.run(TelegramConnector().discover_candidates())

    assert telegram_message_url("palestine", 8) == "https://t.me/palestine/8"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HebMix", "HebMix"),
        ("https://t.me/s/HebMix?utm_source=chatgpt.com", "HebMix"),
        ("https://t.me/s/nabuls_news/30316?q=%23%D8%B9%D8%A7%D8%AC%D9%84", "nabuls_news"),
        ("https://t.me/s/ramallahmix1?before=166225", "ramallahmix1"),
        ("t.me/khalelnews/117117", "khalelnews"),
    ],
)
def test_telegram_target_normalizes_public_web_urls(value: str, expected: str) -> None:
    assert telegram_target(value) == expected
