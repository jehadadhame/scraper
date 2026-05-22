from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import build_connectors
from app.connectors.base import CandidateRecord, CollectedRecord, ConnectorError
from app.models import (
    CollectedItem,
    DiscoveryCandidate,
    IngestionRun,
    IssueEvidence,
    Source,
    utcnow,
)
from app.services.analysis import attach_item_to_issue, refresh_all_clusters
from app.services.text import content_hash, dedupe_key, detect_language, normalize_text


def queue_run(session: Session, kind: str, trigger: str = "manual") -> IngestionRun:
    run = IngestionRun(kind=kind, trigger=trigger, status="queued")
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


async def execute_run(session: Session, run: IngestionRun) -> IngestionRun:
    run.status = "running"
    run.started_at = utcnow()
    session.commit()
    try:
        if run.kind == "ingest":
            run.collected_count, run.analyzed_count = await ingest_sources(session)
        elif run.kind == "discover":
            run.discovered_count = await discover_sources(session)
        elif run.kind == "retention":
            run.expired_count = expire_evidence(session)
        else:
            raise ValueError(f"Unsupported run kind: {run.kind}")
        run.status = "succeeded"
    except Exception as exc:  # noqa: BLE001 - worker must capture run failures
        session.rollback()
        run = session.get(IngestionRun, run.id)
        if not run:
            raise
        run.status = "failed"
        run.error = str(exc)
    run.finished_at = utcnow()
    session.commit()
    session.refresh(run)
    return run


async def ingest_sources(session: Session) -> tuple[int, int]:
    connectors = build_connectors()
    collected_count = 0
    analyzed_count = 0
    sources = session.scalars(select(Source).where(Source.enabled.is_(True))).all()

    for source in sources:
        connector = connectors.get(source.platform)
        if not connector:
            source.access_state = "unsupported"
            source.health = f"No connector exists for {source.platform}."
            continue

        try:
            batch = (
                await connector.poll(source)
                if source.cursor_state
                else await connector.backfill(source)
            )
            source.cursor_state = batch.cursor_state
            source.access_state = batch.access_state
            source.health = batch.health
            source.last_run_at = utcnow()
            for record in batch.items:
                item, is_new = store_item(session, source, record)
                if not is_new:
                    continue
                collected_count += 1
                if is_recent_content_duplicate(session, item):
                    continue
                if attach_item_to_issue(session, item):
                    analyzed_count += 1
            session.commit()
        except ConnectorError as exc:
            session.rollback()
            source = session.get(Source, source.id)
            if source:
                source.access_state = exc.access_state
                source.health = str(exc)
                source.last_run_at = utcnow()
                session.commit()
        except Exception as exc:  # noqa: BLE001 - surface connector health without aborting
            session.rollback()
            source = session.get(Source, source.id)
            if source:
                source.access_state = "error"
                source.health = str(exc)
                source.last_run_at = utcnow()
                session.commit()
    return collected_count, analyzed_count


async def discover_sources(session: Session) -> int:
    connectors = build_connectors()
    discovered_count = 0
    for platform in ("telegram", "news"):
        connector = connectors[platform]
        try:
            for candidate in await connector.discover_candidates():
                if save_candidate(session, candidate):
                    discovered_count += 1
            session.commit()
        except ConnectorError:
            session.rollback()
        except Exception:
            session.rollback()
    return discovered_count


def save_candidate(session: Session, record: CandidateRecord) -> bool:
    existing_source = session.scalar(
        select(Source.id).where(
            Source.platform == record.platform,
            Source.external_id == record.external_id,
        )
    )
    existing_candidate = session.scalar(
        select(DiscoveryCandidate.id).where(
            DiscoveryCandidate.platform == record.platform,
            DiscoveryCandidate.external_id == record.external_id,
        )
    )
    if existing_source or existing_candidate:
        return False

    session.add(
        DiscoveryCandidate(
            platform=record.platform,
            label=record.label,
            url=record.url,
            external_id=record.external_id,
            discovered_by=record.discovered_by,
            reason=record.reason,
            payload=record.payload,
        )
    )
    return True


def approve_candidate(session: Session, candidate: DiscoveryCandidate) -> Source:
    candidate.status = "approved"
    candidate.reviewed_at = utcnow()
    source = session.scalar(
        select(Source).where(
            Source.platform == candidate.platform,
            Source.external_id == candidate.external_id,
        )
    )
    if not source:
        source = Source(
            platform=candidate.platform,
            label=candidate.label,
            url=candidate.url,
            external_id=candidate.external_id,
            access_state="unchecked",
        )
        session.add(source)
    session.commit()
    session.refresh(source)
    return source


def reject_candidate(session: Session, candidate: DiscoveryCandidate) -> None:
    candidate.status = "rejected"
    candidate.reviewed_at = utcnow()
    session.commit()


def store_item(
    session: Session, source: Source, record: CollectedRecord
) -> tuple[CollectedItem, bool]:
    normalized = normalize_text(record.text)
    item_dedupe_key = dedupe_key(record.platform, source.id, record.external_id, normalized)
    existing = session.scalar(
        select(CollectedItem).where(CollectedItem.dedupe_key == item_dedupe_key)
    )
    if existing:
        return existing, False

    posted_at = record.posted_at
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    item = CollectedItem(
        source_id=source.id,
        platform=record.platform,
        external_id=record.external_id,
        dedupe_key=item_dedupe_key,
        content_hash=content_hash(normalized),
        text=normalized,
        language=detect_language(normalized),
        original_url=record.original_url,
        posted_at=posted_at,
        platform_metadata=record.metadata,
    )
    session.add(item)
    session.flush()
    return item, True


def is_recent_content_duplicate(session: Session, item: CollectedItem) -> bool:
    cutoff = item.posted_at - timedelta(days=7)
    duplicate_id = session.scalar(
        select(CollectedItem.id)
        .where(
            CollectedItem.id != item.id,
            CollectedItem.content_hash == item.content_hash,
            CollectedItem.posted_at >= cutoff,
        )
        .limit(1)
    )
    return duplicate_id is not None


def expire_evidence(session: Session, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=get_settings().retention_days)
    expired_ids = session.scalars(
        select(CollectedItem.id).where(CollectedItem.collected_at < cutoff)
    ).all()
    if not expired_ids:
        return 0
    session.execute(delete(IssueEvidence).where(IssueEvidence.item_id.in_(expired_ids)))
    session.execute(delete(CollectedItem).where(CollectedItem.id.in_(expired_ids)))
    refresh_all_clusters(session)
    session.commit()
    return len(expired_ids)
