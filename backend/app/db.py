from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


def make_engine(database_url: str) -> Engine:
    kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(target_engine: Engine | None = None) -> None:
    selected_engine = target_engine or engine
    if selected_engine.dialect.name == "postgresql":
        with selected_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.create_all(selected_engine)
    ensure_issue_cluster_columns(selected_engine)

    if selected_engine.dialect.name == "postgresql":
        with selected_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_collected_items_text_fts
                    ON collected_items
                    USING GIN (to_tsvector('simple', coalesce(text, '')))
                    """
                )
            )


def ensure_issue_cluster_columns(target_engine: Engine) -> None:
    inspector = inspect(target_engine)
    if "issue_clusters" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("issue_clusters")}
    if target_engine.dialect.name == "postgresql":
        statements = {
            "keywords": "ALTER TABLE issue_clusters ADD COLUMN IF NOT EXISTS keywords JSON DEFAULT '[]'::json",
            "growth_rate": "ALTER TABLE issue_clusters ADD COLUMN IF NOT EXISTS growth_rate DOUBLE PRECISION DEFAULT 0",
            "trend": "ALTER TABLE issue_clusters ADD COLUMN IF NOT EXISTS trend VARCHAR(32) DEFAULT 'stable'",
            "confidence": "ALTER TABLE issue_clusters ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION DEFAULT 0",
            "total_count": "ALTER TABLE issue_clusters ADD COLUMN IF NOT EXISTS total_count INTEGER DEFAULT 0",
        }
    else:
        statements = {
            "keywords": "ALTER TABLE issue_clusters ADD COLUMN keywords JSON DEFAULT '[]'",
            "growth_rate": "ALTER TABLE issue_clusters ADD COLUMN growth_rate FLOAT DEFAULT 0",
            "trend": "ALTER TABLE issue_clusters ADD COLUMN trend VARCHAR(32) DEFAULT 'stable'",
            "confidence": "ALTER TABLE issue_clusters ADD COLUMN confidence FLOAT DEFAULT 0",
            "total_count": "ALTER TABLE issue_clusters ADD COLUMN total_count INTEGER DEFAULT 0",
        }
    missing_statements = [
        statement for column, statement in statements.items() if column not in existing
    ]
    if not missing_statements:
        return
    with target_engine.begin() as connection:
        for statement in missing_statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_issue_clusters_trend "
                "ON issue_clusters (trend)"
            )
        )


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
