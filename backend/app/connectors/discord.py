from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.connectors.base import (
    CollectedRecord,
    ConnectorError,
    ConnectorPermissionError,
    ConnectorUnavailable,
    FetchBatch,
)
from app.models import Source


class DiscordConnector:
    platform = "discord"
    api_base = "https://discord.com/api/v10"

    async def discover_candidates(self) -> list[object]:
        return []

    async def backfill(self, source: Source, limit: int = 100) -> FetchBatch:
        return await self._fetch(source, limit=limit)

    async def poll(self, source: Source, limit: int = 100) -> FetchBatch:
        cursor_state = source.cursor_state or {}
        return await self._fetch(source, limit=limit, after=cursor_state.get("after"))

    async def _fetch(
        self, source: Source, limit: int, after: str | None = None
    ) -> FetchBatch:
        token = get_settings().discord_bot_token
        channel_id = discord_channel_id(source.external_id or source.url)
        if not token:
            raise ConnectorUnavailable("DISCORD_BOT_TOKEN is not configured.")
        if not channel_id:
            raise ConnectorError(
                "Discord sources need a channel ID or a channel URL like "
                "https://discord.com/channels/<server-id>/<channel-id>."
            )

        params: dict[str, Any] = {"limit": max(1, min(limit, 100))}
        if after:
            params["after"] = after

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{self.api_base}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {token}"},
                params=params,
            )

        if response.status_code in {401, 403, 404}:
            raise ConnectorPermissionError(
                f"Discord channel history is unavailable ({response.status_code})."
            )
        response.raise_for_status()

        messages = response.json()
        records = [self._message_to_record(message) for message in messages]
        records = [record for record in records if record is not None]
        cursor = (source.cursor_state or {}).copy()
        if messages:
            cursor["after"] = str(max(int(message["id"]) for message in messages))
        return FetchBatch(items=records, cursor_state=cursor, health="Discord poll succeeded.")

    def _message_to_record(self, message: dict[str, Any]) -> CollectedRecord | None:
        text = (message.get("content") or "").strip()
        if not text:
            return None

        posted_at = parse_iso_datetime(message["timestamp"])
        guild_id = message.get("guild_id")
        channel_id = message["channel_id"]
        message_id = message["id"]
        original_url = (
            f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
            if guild_id
            else None
        )
        return CollectedRecord(
            platform=self.platform,
            external_id=message_id,
            text=text,
            posted_at=posted_at,
            original_url=original_url,
            metadata={"channel_id": channel_id, "message_type": message.get("type", 0)},
        )


def parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def discord_channel_id(value: str | None) -> str | None:
    if not value:
        return None

    target = value.strip()
    if target.isdigit():
        return target

    parsed = urlparse(target if "://" in target else f"https://{target}")
    if parsed.netloc.casefold() not in {
        "discord.com",
        "www.discord.com",
        "discordapp.com",
        "www.discordapp.com",
    }:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[0] == "channels":
        guild_or_home, channel_id = path_parts[1], path_parts[2]
        if guild_or_home != "@me" and channel_id.isdigit():
            return channel_id
    return None
