from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models import Source


@dataclass(slots=True)
class CollectedRecord:
    platform: str
    external_id: str | None
    text: str
    posted_at: datetime
    original_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CandidateRecord:
    platform: str
    label: str
    external_id: str
    discovered_by: str
    url: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchBatch:
    items: list[CollectedRecord]
    cursor_state: dict[str, Any] = field(default_factory=dict)
    access_state: str = "ready"
    health: str | None = None


class ConnectorError(RuntimeError):
    access_state = "error"


class ConnectorUnavailable(ConnectorError):
    access_state = "missing_credentials"


class ConnectorPermissionError(ConnectorError):
    access_state = "permission_denied"


class Connector(Protocol):
    platform: str

    async def discover_candidates(self) -> list[CandidateRecord]: ...

    async def backfill(self, source: Source, limit: int = 200) -> FetchBatch: ...

    async def poll(self, source: Source, limit: int = 100) -> FetchBatch: ...

