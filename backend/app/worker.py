from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import IngestionRun
from app.services.ingestion import execute_run, queue_run


async def worker_loop() -> None:
    init_db()
    while True:
        with SessionLocal() as session:
            queue_due_scheduled_runs(session)
            run = session.scalar(
                select(IngestionRun)
                .where(IngestionRun.status == "queued")
                .order_by(IngestionRun.requested_at)
                .limit(1)
            )
            if run:
                await execute_run(session, run)
        await asyncio.sleep(5)


def queue_due_scheduled_runs(session) -> None:
    threshold = datetime.now(UTC) - timedelta(seconds=get_settings().schedule_seconds)
    for kind in ("ingest", "discover", "retention"):
        latest = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.kind == kind, IngestionRun.trigger == "scheduled")
            .order_by(desc(IngestionRun.requested_at))
            .limit(1)
        )
        queued = session.scalar(
            select(IngestionRun.id).where(
                IngestionRun.kind == kind,
                IngestionRun.status.in_(["queued", "running"]),
            )
        )
        if not queued and (not latest or latest.requested_at < threshold):
            queue_run(session, kind=kind, trigger="scheduled")


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()

