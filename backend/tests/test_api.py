import asyncio
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.connectors.base import CollectedRecord
from app.db import get_session, init_db
from app.main import create_app
from app.models import DiscoveryCandidate, IngestionRun, IssueCluster, Source
from app.services.ingestion import execute_run, store_item


def test_source_crud_and_candidate_review() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(initialize_database=False)

    def session_override() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with testing_session() as session:
        session.add(
            DiscoveryCandidate(
                platform="telegram",
                label="Candidate channel",
                external_id="candidate-channel",
                discovered_by="Palestine",
            )
        )
        session.commit()

    client = TestClient(app)
    created = client.post(
        "/api/sources",
        json={
            "platform": "news",
            "label": "Local RSS",
            "url": "https://news.test/rss",
        },
    )
    assert created.status_code == 201
    source_id = created.json()["id"]

    patched = client.patch(f"/api/sources/{source_id}", json={"enabled": False})
    assert patched.json()["enabled"] is False

    candidates = client.get("/api/discovery-candidates").json()
    reviewed = client.post(
        f"/api/discovery-candidates/{candidates[0]['id']}/review",
        json={"action": "approve"},
    )
    assert reviewed.json()["status"] == "approved"
    assert len(client.get("/api/sources").json()) == 2

    deleted = client.delete(f"/api/sources/{source_id}")
    assert deleted.status_code == 204


def test_post_list_and_stats_filters() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(initialize_database=False)

    def session_override() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    now = datetime.now(UTC)
    with testing_session() as session:
        telegram = Source(platform="telegram", label="Telegram A", external_id="telegram-a")
        news = Source(platform="news", label="News feed", url="https://feed.test/rss")
        session.add_all([telegram, news])
        session.flush()
        store_item(
            session,
            telegram,
            CollectedRecord(
                platform="telegram",
                external_id="m1",
                text="ازمة مياه في الحي وحاجة لصهاريج",
                posted_at=now,
            ),
        )
        store_item(
            session,
            news,
            CollectedRecord(
                platform="news",
                external_id="n1",
                text="Medicine shortage at the clinic",
                posted_at=now - timedelta(days=2),
            ),
        )
        session.commit()

    client = TestClient(app)
    searched = client.get("/api/posts", params={"q": "مياه", "language": "ar"}).json()
    assert len(searched) == 1
    assert searched[0]["source_label"] == "Telegram A"

    stats = client.get("/api/posts/stats", params={"days": 30}).json()
    assert stats["total"] == 2
    assert stats["last_7d"] == 2
    assert stats["by_platform"][0]["count"] >= 1
    assert {entry["label"] for entry in stats["by_language"]} == {"Arabic", "English"}


def test_analytics_endpoint_and_analyze_run() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(initialize_database=False)

    def session_override() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    now = datetime.now(UTC)
    with testing_session() as session:
        source = Source(platform="telegram", label="Workers", external_id="workers")
        session.add(source)
        session.flush()
        for index, text in enumerate(
            [
                "تصاريح العمل للعمال متوقفة وهناك حاجة لمتابعة عاجلة",
                "العمال يطالبون بحل مشكلة تصاريح العمل",
                "نقص ادوية في العيادة وحاجة لدعم صحي",
            ]
        ):
            store_item(
                session,
                source,
                CollectedRecord(
                    platform="telegram",
                    external_id=f"w{index}",
                    text=text,
                    posted_at=now - timedelta(hours=index),
                ),
            )
        run = IngestionRun(kind="analyze", trigger="manual", status="queued")
        session.add(run)
        session.commit()
        asyncio.run(execute_run(session, run))
        assert session.query(IssueCluster).count() >= 2

    client = TestClient(app)
    stats = client.get("/api/analytics", params={"days": 30}).json()

    assert stats["total_posts"] == 3
    assert stats["analyzed_posts"] == 3
    assert stats["issue_count"] >= 2
    assert stats["top_keywords"]
    assert stats["top_issues"][0]["keywords"]
