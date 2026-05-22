from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session, init_db
from app.main import create_app
from app.models import DiscoveryCandidate


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
