import asyncio
from types import SimpleNamespace

import feedparser
import pytest

from app.connectors.base import CandidateRecord, ConnectorError, ConnectorUnavailable
from app.connectors.discord import DiscordConnector, discord_channel_id
from app.connectors.facebook import FacebookConnector
from app.connectors.news import NewsConnector
from app.connectors.telegram import TelegramConnector, telegram_message_url, telegram_target
from app.models import Source
from app.services.ingestion import discover_sources


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


def test_discord_rejects_server_url_as_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.connectors.discord.get_settings",
        lambda: SimpleNamespace(discord_bot_token="token"),
    )
    source = Source(
        platform="discord",
        label="Server URL",
        url="https://discord.com/channels/1158821273372196956",
    )

    with pytest.raises(ConnectorError, match="channel URL"):
        asyncio.run(DiscordConnector().poll(source))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120030040050060070", "120030040050060070"),
        (
            "https://discord.com/channels/1158821273372196956/120030040050060070",
            "120030040050060070",
        ),
        ("https://discord.com/channels/1158821273372196956", None),
        ("https://discord.com/channels/1158821273372196956/@home", None),
    ],
)
def test_discord_channel_id_accepts_channel_urls_only(
    value: str, expected: str | None
) -> None:
    assert discord_channel_id(value) == expected


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


def test_discovery_dedupes_candidates_before_save(monkeypatch, session) -> None:
    duplicate = CandidateRecord(
        platform="telegram",
        label="Palestine channel",
        external_id="palestine-channel",
        discovered_by="Palestine",
    )

    class FakeConnector:
        async def discover_candidates(self):
            return [duplicate, duplicate]

    class EmptyConnector:
        async def discover_candidates(self):
            return []

    monkeypatch.setattr(
        "app.services.ingestion.build_connectors",
        lambda: {"telegram": FakeConnector(), "news": EmptyConnector()},
    )

    assert asyncio.run(discover_sources(session)) == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HebMix", "HebMix"),
        ("https://t.me/s/HebMix?utm_source=chatgpt.com", "HebMix"),
        ("https://t.me/s/nabuls_news/30316?q=%23%D8%B9%D8%A7%D8%AC%D9%84", "nabuls_news"),
        ("https://t.me/s/ramallahmix1?before=166225", "ramallahmix1"),
        ("t.me/khalelnews/117117", "khalelnews"),
        ("https://discord.com/channels/server/channel", None),
    ],
)
def test_telegram_target_normalizes_public_web_urls(
    value: str, expected: str | None
) -> None:
    assert telegram_target(value) == expected
