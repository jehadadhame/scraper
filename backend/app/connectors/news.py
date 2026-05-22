from __future__ import annotations

import calendar
from datetime import UTC, datetime
from hashlib import sha256
from time import struct_time
from typing import Any

import feedparser
import httpx

from app.config import get_settings
from app.connectors.base import CandidateRecord, CollectedRecord, ConnectorUnavailable, FetchBatch
from app.models import Source


class NewsConnector:
    platform = "news"

    async def discover_candidates(self) -> list[CandidateRecord]:
        settings = get_settings()
        candidates: list[CandidateRecord] = []
        for feed_url in settings.news_discovery_feeds:
            parsed = await self._read_feed(feed_url)
            matching_entries = [
                {
                    "title": entry.get("title", "Untitled"),
                    "url": entry.get("link"),
                }
                for entry in parsed.entries[:20]
                if mentions_keywords(
                    f"{entry.get('title', '')} {entry.get('summary', '')}",
                    settings.news_keywords,
                )
            ]
            if not matching_entries:
                continue
            candidates.append(
                CandidateRecord(
                    platform=self.platform,
                    label=parsed.feed.get("title", feed_url),
                    external_id=feed_url,
                    url=feed_url,
                    discovered_by="news_discovery_feeds",
                    reason="Discovery feed contains Palestine-related text matches.",
                    payload={"sample_articles": matching_entries[:5]},
                )
            )
        return candidates

    async def backfill(self, source: Source, limit: int = 200) -> FetchBatch:
        return await self._fetch(source, limit=limit, polling=False)

    async def poll(self, source: Source, limit: int = 100) -> FetchBatch:
        return await self._fetch(source, limit=limit, polling=True)

    async def _fetch(self, source: Source, limit: int, polling: bool) -> FetchBatch:
        feed_url = source.url or source.external_id
        if not feed_url:
            raise ConnectorUnavailable("News sources need an RSS or Atom URL.")

        parsed = await self._read_feed(feed_url)
        seen_ids = set((source.cursor_state or {}).get("seen_ids", []))
        records: list[CollectedRecord] = []
        next_seen = list(seen_ids)

        for entry in parsed.entries[:limit]:
            entry_id = entry_key(entry)
            if polling and entry_id in seen_ids:
                continue
            next_seen.append(entry_id)
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            text = "\n".join(part for part in [title, summary] if part).strip()
            if not text:
                continue
            records.append(
                CollectedRecord(
                    platform=self.platform,
                    external_id=entry_id,
                    text=text,
                    posted_at=entry_datetime(entry),
                    original_url=entry.get("link"),
                    metadata={
                        "feed_title": parsed.feed.get("title"),
                        "entry_title": title,
                    },
                )
            )

        cursor = {"seen_ids": next_seen[-250:]}
        return FetchBatch(
            items=records,
            cursor_state=cursor,
            health=f"Fetched {len(records)} items from RSS/Atom.",
        )

    async def _read_feed(self, feed_url: str) -> Any:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                feed_url,
                headers={"User-Agent": "PalestineSignalDashboard/0.1 authorized-feed-reader"},
            )
        response.raise_for_status()
        return feedparser.parse(response.content)


def mentions_keywords(text: str, keywords: list[str]) -> bool:
    folded = text.casefold()
    return any(keyword.casefold() in folded for keyword in keywords)


def entry_key(entry: Any) -> str:
    if entry.get("id"):
        return str(entry.id)
    if entry.get("link"):
        return str(entry.link)
    material = f"{entry.get('title', '')}|{entry.get('published', '')}"
    return sha256(material.encode("utf-8")).hexdigest()


def entry_datetime(entry: Any) -> datetime:
    time_value: struct_time | None = entry.get("published_parsed") or entry.get(
        "updated_parsed"
    )
    if time_value:
        return datetime.fromtimestamp(calendar.timegm(time_value), tz=UTC)
    return datetime.now(UTC)
