from app.connectors.base import ConnectorUnavailable, FetchBatch
from app.models import Source


class FacebookConnector:
    platform = "facebook"

    async def discover_candidates(self) -> list[object]:
        return []

    async def backfill(self, source: Source, limit: int = 200) -> FetchBatch:
        raise ConnectorUnavailable(
            "Facebook is gated until an approved Meta access path is configured."
        )

    async def poll(self, source: Source, limit: int = 100) -> FetchBatch:
        raise ConnectorUnavailable(
            "Facebook is gated until an approved Meta access path is configured."
        )

