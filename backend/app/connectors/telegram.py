from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from telethon import TelegramClient, functions

from app.config import get_settings
from app.connectors.base import CandidateRecord, CollectedRecord, ConnectorUnavailable, FetchBatch
from app.models import Source


class TelegramConnector:
    platform = "telegram"

    async def discover_candidates(self) -> list[CandidateRecord]:
        client = await self._client()
        candidates: list[CandidateRecord] = []
        async with client:
            for query in get_settings().telegram_queries:
                result = await client(functions.contacts.SearchRequest(q=query, limit=20))
                for chat in result.chats:
                    external_id, url = chat_reference(chat)
                    candidates.append(
                        CandidateRecord(
                            platform=self.platform,
                            label=getattr(chat, "title", external_id),
                            external_id=external_id,
                            url=url,
                            discovered_by=query,
                            reason="Telegram public search match.",
                            payload={
                                "username": getattr(chat, "username", None),
                                "broadcast": bool(getattr(chat, "broadcast", False)),
                                "megagroup": bool(getattr(chat, "megagroup", False)),
                            },
                        )
                    )
        return candidates

    async def backfill(self, source: Source, limit: int = 200) -> FetchBatch:
        return await self._fetch(source, limit=limit)

    async def poll(self, source: Source, limit: int = 100) -> FetchBatch:
        last_message_id = (source.cursor_state or {}).get("last_message_id")
        return await self._fetch(source, limit=limit, min_id=last_message_id)

    async def _fetch(
        self, source: Source, limit: int, min_id: int | None = None
    ) -> FetchBatch:
        target = telegram_target(source.external_id or source.url)
        if not target:
            raise ConnectorUnavailable("Telegram sources need a username, ID, or t.me URL.")

        client = await self._client()
        records: list[CollectedRecord] = []
        latest_id = int((source.cursor_state or {}).get("last_message_id", 0))
        async with client:
            entity = await client.get_entity(target)
            username = getattr(entity, "username", None)
            async for message in client.iter_messages(
                entity,
                limit=limit,
                min_id=int(min_id or 0),
                reverse=bool(min_id),
            ):
                text = (message.message or "").strip()
                if not text:
                    continue
                latest_id = max(latest_id, int(message.id))
                records.append(
                    CollectedRecord(
                        platform=self.platform,
                        external_id=str(message.id),
                        text=text,
                        posted_at=message.date,
                        original_url=telegram_message_url(username, message.id),
                        metadata={
                            "message_id": message.id,
                            "views": getattr(message, "views", None),
                        },
                    )
                )
        return FetchBatch(
            items=records,
            cursor_state={"last_message_id": latest_id},
            health=f"Fetched {len(records)} Telegram messages.",
        )

    async def _client(self) -> TelegramClient:
        settings = get_settings()
        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ConnectorUnavailable(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for Telegram."
            )

        session_path = Path(settings.telegram_session_path)
        session_path.parent.mkdir(parents=True, exist_ok=True)
        client = TelegramClient(
            str(session_path),
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise ConnectorUnavailable(
                "Telegram session is not authorized; run the login helper first."
            )
        return client


def chat_reference(chat: Any) -> tuple[str, str | None]:
    username = getattr(chat, "username", None)
    if username:
        return username, f"https://t.me/{username}"
    return str(chat.id), None


def telegram_message_url(username: str | None, message_id: int) -> str | None:
    return f"https://t.me/{username}/{message_id}" if username else None


def telegram_target(value: str | None) -> str | None:
    if not value:
        return None

    target = value.strip()
    parsed = urlparse(target if "://" in target else f"https://{target}")
    if parsed.netloc.casefold() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        return target

    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts[:1] == ["s"]:
        path_parts = path_parts[1:]
    if not path_parts:
        return target

    # Telethon resolves the channel username/ID, not Telegram web preview URLs.
    return path_parts[0].lstrip("@")
