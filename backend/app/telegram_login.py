from __future__ import annotations

import asyncio
from pathlib import Path

from telethon import TelegramClient

from app.config import get_settings


async def login() -> None:
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise SystemExit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first.")
    session_path = Path(settings.telegram_session_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    async with TelegramClient(
        str(session_path), settings.telegram_api_id, settings.telegram_api_hash
    ) as client:
        await client.start()
        me = await client.get_me()
        print(f"Telegram session authorized for user id {me.id}.")


if __name__ == "__main__":
    asyncio.run(login())

