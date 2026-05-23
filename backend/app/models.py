from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_source_external_id"),
        Index("ix_sources_platform_enabled", "platform", "enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(240))
    url: Mapped[str | None] = mapped_column(String(1200))
    external_id: Mapped[str | None] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    access_state: Mapped[str] = mapped_column(String(64), default="unchecked")
    health: Mapped[str | None] = mapped_column(String(240))
    cursor_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    platform_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    items: Mapped[list[CollectedItem]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_candidate_external_id"),
        Index("ix_discovery_candidates_status", "status", "platform"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(240))
    url: Mapped[str | None] = mapped_column(String(1200))
    external_id: Mapped[str | None] = mapped_column(String(512))
    discovered_by: Mapped[str] = mapped_column(String(240))
    reason: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingestion_runs_status_kind", "status", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="ingest")
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    expired_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class CollectedItem(Base):
    __tablename__ = "collected_items"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_collected_item_dedupe_key"),
        Index("ix_collected_items_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str | None] = mapped_column(String(512))
    dedupe_key: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(16), default="unknown")
    original_url: Mapped[str | None] = mapped_column(String(1200))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    platform_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source: Mapped[Source] = relationship(back_populates="items")
    evidence_links: Mapped[list[IssueEvidence]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class IssueCluster(Base):
    __tablename__ = "issue_clusters"
    __table_args__ = (Index("ix_issue_clusters_score_latest", "score", "latest_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(240))
    summary: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    latest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recent_count: Mapped[int] = mapped_column(Integer, default=0)
    previous_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    language_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    growth_rate: Mapped[float] = mapped_column(Float, default=0.0)
    trend: Mapped[str] = mapped_column(String(32), default="stable", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    evidence_links: Mapped[list[IssueEvidence]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )
    points: Mapped[list[IssuePoint]] = relationship(
        back_populates="cluster", cascade="all, delete-orphan"
    )


class IssueEvidence(Base):
    __tablename__ = "issue_evidence"
    __table_args__ = (
        UniqueConstraint("cluster_id", "item_id", name="uq_issue_evidence_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("issue_clusters.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("collected_items.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cluster: Mapped[IssueCluster] = relationship(back_populates="evidence_links")
    item: Mapped[CollectedItem] = relationship(back_populates="evidence_links")


class IssuePoint(Base):
    __tablename__ = "issue_points"
    __table_args__ = (
        UniqueConstraint("cluster_id", "bucket_date", name="uq_issue_point_bucket"),
        Index("ix_issue_points_bucket", "bucket_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("issue_clusters.id", ondelete="CASCADE"), index=True
    )
    bucket_date: Mapped[date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer, default=0)
    unique_sources: Mapped[int] = mapped_column(Integer, default=0)

    cluster: Mapped[IssueCluster] = relationship(back_populates="points")
