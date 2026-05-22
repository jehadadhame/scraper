from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.connectors.base import CollectedRecord
from app.models import IssueCluster, IssueEvidence, Source
from app.services.analysis import attach_item_to_issue
from app.services.ingestion import expire_evidence, is_recent_content_duplicate, store_item
from app.services.text import detect_language, minimize_for_hosted_ai, normalize_text


def test_normalizes_arabic_and_minimizes_identifiers() -> None:
    text = "أزمة <b>مِيَاه</b> اتصل +970 599-123-456 أو user@example.com @helper https://x.test"

    normalized = normalize_text(text)
    minimized = minimize_for_hosted_ai(text)

    assert "ازمة مياه" in normalized
    assert "[phone]" in minimized
    assert "[email]" in minimized
    assert "[handle]" in minimized
    assert "[url]" in minimized
    assert detect_language(normalized) == "ar"


def test_dedupes_recent_content_before_issue_attachment(session) -> None:
    first_source = Source(platform="news", label="Feed A", url="https://feed-a.test")
    second_source = Source(platform="telegram", label="Channel B", external_id="channel-b")
    session.add_all([first_source, second_source])
    session.flush()
    record = CollectedRecord(
        platform="news",
        external_id="entry-1",
        text="Medicine shortage at a hospital needs urgent support.",
        posted_at=datetime.now(UTC),
    )
    first_item, _ = store_item(session, first_source, record)
    first_cluster = attach_item_to_issue(session, first_item)
    second_item, _ = store_item(
        session,
        second_source,
        CollectedRecord(
            platform="telegram",
            external_id="message-2",
            text=record.text,
            posted_at=record.posted_at + timedelta(minutes=2),
        ),
    )

    assert first_cluster is not None
    assert is_recent_content_duplicate(session, second_item) is True
    assert session.scalar(select(IssueEvidence).where(IssueEvidence.item_id == second_item.id)) is None
    assert session.scalar(select(IssueCluster)).label == "Health access and medicine"


def test_retention_deletes_evidence_text_and_keeps_issue_cluster(session) -> None:
    source = Source(platform="news", label="Feed", url="https://feed.test")
    session.add(source)
    session.flush()
    item, _ = store_item(
        session,
        source,
        CollectedRecord(
            platform="news",
            external_id="entry",
            text="Water shortage problem in a neighborhood.",
            posted_at=datetime.now(UTC) - timedelta(days=4),
        ),
    )
    item.collected_at = datetime.now(UTC) - timedelta(days=91)
    cluster = attach_item_to_issue(session, item)
    session.commit()

    expired_count = expire_evidence(session)

    assert expired_count == 1
    assert session.get(IssueCluster, cluster.id) is not None
    assert session.scalar(select(IssueEvidence)) is None

