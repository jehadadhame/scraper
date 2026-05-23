from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.connectors.base import CollectedRecord
from app.main import issue_read
from app.models import IssueCluster, IssueEvidence, Source
from app.services.analysis import attach_item_to_issue, extract_keywords, rebuild_issue_clusters
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
    assert session.scalar(select(IssueCluster)).label == "الوصول إلى الرعاية الصحية والدواء"


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


def test_issue_read_localizes_stored_topic_metadata() -> None:
    stored_cluster = IssueCluster(
        id=4,
        fingerprint="housing",
        category="housing",
        label="Housing and shelter needs",
        summary="Stored before Arabic topic labels were added.",
        score=0,
        recent_count=0,
        previous_count=0,
        source_count=0,
        language_counts={},
    )

    issue = issue_read(stored_cluster)

    assert issue.label == "احتياجات السكن والمأوى"
    assert issue.summary.startswith("بلاغات عن المأوى")


def test_rebuild_clusters_related_arabic_posts_into_fine_issue(session) -> None:
    now = datetime.now(UTC)
    source = Source(platform="telegram", label="Local channel", external_id="local")
    session.add(source)
    session.flush()
    for index, text in enumerate(
        [
            "ازمة مياه في الحي الشرقي وحاجة عاجلة لصهاريج مياه",
            "نقص مياه الشرب في الحي الشرقي والسكان يطلبون صهاريج",
            "انقطاع المياه عن الحي الشرقي منذ الصباح",
            "اغلاق حاجز المدينة يسبب ازمة مواصلات للطلاب",
        ]
    ):
        store_item(
            session,
            source,
            CollectedRecord(
                platform="telegram",
                external_id=f"m{index}",
                text=text,
                posted_at=now - timedelta(hours=index),
            ),
        )

    analyzed_count = rebuild_issue_clusters(session, now=now)
    clusters = session.scalars(select(IssueCluster).order_by(IssueCluster.total_count.desc())).all()

    assert analyzed_count == 4
    assert len(clusters) >= 2
    assert clusters[0].category == "services"
    assert clusters[0].total_count >= 3
    assert clusters[0].keywords
    assert clusters[0].confidence > 0


def test_extract_keywords_is_local_and_arabic_aware() -> None:
    keywords = extract_keywords(
        [
            "تصاريح العمل للعمال متوقفة منذ الصباح",
            "العمال بحاجة الى تصاريح عمل جديدة",
        ]
    )

    assert {"تصاريح", "العمال"} & set(keywords)
