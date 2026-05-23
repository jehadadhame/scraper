from __future__ import annotations

from collections import Counter
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, exists, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session, init_db
from app.models import (
    CollectedItem,
    DiscoveryCandidate,
    IngestionRun,
    IssueCluster,
    IssueEvidence,
    IssuePoint,
    Source,
)
from app.schemas import (
    AnalyticsStatsRead,
    AnalyticsTimelineRead,
    CandidateRead,
    CandidateReview,
    EvidenceRead,
    IssueDetail,
    IssuePointRead,
    IssueRead,
    CountRead,
    PostRead,
    PostStatsRead,
    PostTimelineRead,
    RunCreate,
    RunRead,
    SourceCountRead,
    SourceCreate,
    SourceRead,
    SourceUpdate,
)
from app.services.ingestion import (
    approve_candidate,
    queue_run,
    reject_candidate,
)
from app.services.analysis import topic_for_key
from app.services.text import snippet


SessionDep = Annotated[Session, Depends(get_session)]


def create_app(initialize_database: bool = True) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if initialize_database:
            init_db()
        yield

    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/sources", response_model=list[SourceRead])
    def list_sources(session: SessionDep) -> list[Source]:
        return session.scalars(select(Source).order_by(Source.platform, Source.label)).all()

    @application.post(
        "/api/sources",
        response_model=SourceRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_source(payload: SourceCreate, session: SessionDep) -> Source:
        source = Source(**payload.model_dump(), access_state="unchecked")
        session.add(source)
        session.commit()
        session.refresh(source)
        return source

    @application.patch("/api/sources/{source_id}", response_model=SourceRead)
    def update_source(
        source_id: int, payload: SourceUpdate, session: SessionDep
    ) -> Source:
        source = get_or_404(session, Source, source_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(source, key, value)
        session.commit()
        session.refresh(source)
        return source

    @application.delete("/api/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_source(source_id: int, session: SessionDep) -> Response:
        source = get_or_404(session, Source, source_id)
        session.delete(source)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.get("/api/discovery-candidates", response_model=list[CandidateRead])
    def list_candidates(
        session: SessionDep,
        state: str = Query(default="pending", pattern="^(pending|approved|rejected|all)$"),
    ) -> list[DiscoveryCandidate]:
        query = select(DiscoveryCandidate).order_by(desc(DiscoveryCandidate.created_at))
        if state != "all":
            query = query.where(DiscoveryCandidate.status == state)
        return session.scalars(query).all()

    @application.post(
        "/api/discovery-candidates/{candidate_id}/review",
        response_model=CandidateRead,
    )
    def review_candidate(
        candidate_id: int, payload: CandidateReview, session: SessionDep
    ) -> DiscoveryCandidate:
        candidate = get_or_404(session, DiscoveryCandidate, candidate_id)
        if payload.action == "approve":
            approve_candidate(session, candidate)
        else:
            reject_candidate(session, candidate)
        session.refresh(candidate)
        return candidate

    @application.post(
        "/api/runs", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED
    )
    def create_run(payload: RunCreate, session: SessionDep) -> IngestionRun:
        return queue_run(session, payload.kind)

    @application.get("/api/runs", response_model=list[RunRead])
    def list_runs(session: SessionDep, limit: int = Query(default=30, le=100)) -> list[IngestionRun]:
        return session.scalars(
            select(IngestionRun).order_by(desc(IngestionRun.requested_at)).limit(limit)
        ).all()

    @application.get("/api/runs/{run_id}", response_model=RunRead)
    def get_run(run_id: int, session: SessionDep) -> IngestionRun:
        return get_or_404(session, IngestionRun, run_id)

    @application.get("/api/issues", response_model=list[IssueRead])
    def list_issues(
        session: SessionDep,
        category: str | None = None,
        language: str | None = None,
        source_id: int | None = None,
        trend: str | None = Query(default=None, pattern="^(rising|active)$"),
        q: str | None = None,
        days: int = Query(default=14, ge=1, le=365),
    ) -> list[IssueRead]:
        query = select(IssueCluster).where(
            IssueCluster.latest_at >= datetime.now(UTC) - timedelta(days=days)
        )
        if category:
            query = query.where(IssueCluster.category == category)
        if language:
            query = query.where(issue_has_item(language=language))
        if source_id:
            query = query.where(issue_has_item(source_id=source_id))
        if trend == "rising":
            query = query.where(IssueCluster.trend.in_(["rising", "new"]))
        elif trend == "active":
            query = query.where(IssueCluster.recent_count > 0)
        if q:
            search = f"%{q}%"
            query = query.where(
                or_(
                    IssueCluster.label.ilike(search),
                    IssueCluster.summary.ilike(search),
                    issue_has_item(
                        search=q,
                        full_text=session.get_bind().dialect.name == "postgresql",
                    ),
                )
            )
        clusters = session.scalars(
            query.order_by(desc(IssueCluster.score), desc(IssueCluster.latest_at))
        ).all()
        return [issue_read(cluster) for cluster in clusters]

    @application.get("/api/issues/{issue_id}", response_model=IssueDetail)
    def get_issue(issue_id: int, session: SessionDep) -> IssueDetail:
        cluster = get_or_404(session, IssueCluster, issue_id)
        evidence_rows = session.execute(
            select(CollectedItem, Source)
            .join(IssueEvidence, IssueEvidence.item_id == CollectedItem.id)
            .join(Source, Source.id == CollectedItem.source_id)
            .where(IssueEvidence.cluster_id == cluster.id)
            .order_by(desc(CollectedItem.posted_at))
            .limit(get_settings().evidence_limit_per_issue)
        ).all()
        points = session.scalars(
            select(IssuePoint)
            .where(IssuePoint.cluster_id == cluster.id)
            .order_by(IssuePoint.bucket_date)
        ).all()
        return IssueDetail(
            **issue_read(cluster).model_dump(),
            evidence=[
                EvidenceRead(
                    item_id=item.id,
                    source_id=source.id,
                    source_label=source.label,
                    platform=item.platform,
                    language=item.language,
                    snippet=snippet(item.text),
                    original_url=item.original_url,
                    posted_at=item.posted_at,
                )
                for item, source in evidence_rows
            ],
            timeline=[
                IssuePointRead(
                    bucket_date=point.bucket_date,
                    count=point.count,
                    unique_sources=point.unique_sources,
                )
                for point in points
            ],
        )

    @application.get("/api/posts", response_model=list[PostRead])
    def list_posts(
        session: SessionDep,
        platform: str | None = None,
        language: str | None = None,
        source_id: int | None = None,
        q: str | None = None,
        days: int = Query(default=30, ge=1, le=365),
        limit: int = Query(default=100, ge=1, le=300),
    ) -> list[PostRead]:
        query = (
            select(CollectedItem, Source)
            .join(Source, Source.id == CollectedItem.source_id)
            .where(
                *post_filters(
                    platform=platform,
                    language=language,
                    source_id=source_id,
                    q=q,
                    days=days,
                )
            )
            .order_by(desc(CollectedItem.posted_at))
            .limit(limit)
        )
        return [
            post_read(item=item, source=source)
            for item, source in session.execute(query).all()
        ]

    @application.get("/api/posts/stats", response_model=PostStatsRead)
    def post_stats(
        session: SessionDep,
        platform: str | None = None,
        language: str | None = None,
        source_id: int | None = None,
        q: str | None = None,
        days: int = Query(default=30, ge=1, le=365),
    ) -> PostStatsRead:
        filters = post_filters(
            platform=platform,
            language=language,
            source_id=source_id,
            q=q,
            days=days,
        )
        recent_24h = datetime.now(UTC) - timedelta(days=1)
        recent_7d = datetime.now(UTC) - timedelta(days=7)
        bucket = func.date(CollectedItem.posted_at)

        total = session.scalar(
            select(func.count(CollectedItem.id)).where(*filters)
        ) or 0
        last_24h = session.scalar(
            select(func.count(CollectedItem.id)).where(
                *filters, CollectedItem.posted_at >= recent_24h
            )
        ) or 0
        last_7d = session.scalar(
            select(func.count(CollectedItem.id)).where(
                *filters, CollectedItem.posted_at >= recent_7d
            )
        ) or 0

        platform_rows = session.execute(
            select(CollectedItem.platform, func.count(CollectedItem.id))
            .where(*filters)
            .group_by(CollectedItem.platform)
            .order_by(desc(func.count(CollectedItem.id)))
        ).all()
        language_rows = session.execute(
            select(CollectedItem.language, func.count(CollectedItem.id))
            .where(*filters)
            .group_by(CollectedItem.language)
            .order_by(desc(func.count(CollectedItem.id)))
        ).all()
        source_rows = session.execute(
            select(Source.id, Source.label, Source.platform, func.count(CollectedItem.id))
            .join(CollectedItem, CollectedItem.source_id == Source.id)
            .where(*filters)
            .group_by(Source.id, Source.label, Source.platform)
            .order_by(desc(func.count(CollectedItem.id)))
            .limit(8)
        ).all()
        timeline_rows = session.execute(
            select(bucket, func.count(CollectedItem.id))
            .where(*filters)
            .group_by(bucket)
            .order_by(bucket)
        ).all()

        return PostStatsRead(
            total=total,
            last_24h=last_24h,
            last_7d=last_7d,
            by_platform=[
                CountRead(key=key or "unknown", label=key or "unknown", count=count)
                for key, count in platform_rows
            ],
            by_language=[
                CountRead(
                    key=key or "unknown",
                    label=language_label(key or "unknown"),
                    count=count,
                )
                for key, count in language_rows
            ],
            top_sources=[
                SourceCountRead(
                    source_id=row_id,
                    label=label,
                    platform=row_platform,
                    count=count,
                )
                for row_id, label, row_platform, count in source_rows
            ],
            timeline=[
                PostTimelineRead(bucket_date=parse_bucket_date(row_date), count=count)
                for row_date, count in timeline_rows
            ],
        )

    @application.get("/api/analytics", response_model=AnalyticsStatsRead)
    def analytics_stats(
        session: SessionDep,
        category: str | None = None,
        platform: str | None = None,
        language: str | None = None,
        source_id: int | None = None,
        days: int = Query(default=30, ge=1, le=365),
    ) -> AnalyticsStatsRead:
        now = datetime.now(UTC)
        item_filters = analytics_post_filters(
            platform=platform,
            language=language,
            source_id=source_id,
            category=category,
            days=days,
        )
        issue_query = select(IssueCluster).where(
            IssueCluster.latest_at >= now - timedelta(days=days)
        )
        if category:
            issue_query = issue_query.where(IssueCluster.category == category)
        if platform:
            issue_query = issue_query.where(issue_has_item(platform=platform))
        if language:
            issue_query = issue_query.where(issue_has_item(language=language))
        if source_id:
            issue_query = issue_query.where(issue_has_item(source_id=source_id))

        total_posts = session.scalar(
            select(func.count(CollectedItem.id)).where(*item_filters)
        ) or 0
        analyzed_posts = session.scalar(
            select(func.count(func.distinct(CollectedItem.id)))
            .join(IssueEvidence, IssueEvidence.item_id == CollectedItem.id)
            .join(IssueCluster, IssueCluster.id == IssueEvidence.cluster_id)
            .where(*item_filters)
        ) or 0
        issue_count = session.scalar(
            select(func.count()).select_from(issue_query.order_by(None).subquery())
        ) or 0
        rising_issue_count = session.scalar(
            select(func.count()).select_from(
                issue_query.where(IssueCluster.trend.in_(["rising", "new"]))
                .order_by(None)
                .subquery()
            )
        ) or 0

        bucket = func.date(CollectedItem.posted_at)
        post_rows = dict(
            session.execute(
                select(bucket, func.count(CollectedItem.id))
                .where(*item_filters)
                .group_by(bucket)
                .order_by(bucket)
            ).all()
        )
        issue_rows = dict(
            session.execute(
                select(bucket, func.count(func.distinct(IssueEvidence.cluster_id)))
                .join(IssueEvidence, IssueEvidence.item_id == CollectedItem.id)
                .join(IssueCluster, IssueCluster.id == IssueEvidence.cluster_id)
                .where(*item_filters)
                .group_by(bucket)
                .order_by(bucket)
            ).all()
        )

        category_rows = session.execute(
            select(IssueCluster.category, func.count(func.distinct(CollectedItem.id)))
            .join(IssueEvidence, IssueEvidence.cluster_id == IssueCluster.id)
            .join(CollectedItem, CollectedItem.id == IssueEvidence.item_id)
            .where(*item_filters)
            .group_by(IssueCluster.category)
            .order_by(desc(func.count(func.distinct(CollectedItem.id))))
        ).all()
        source_rows = session.execute(
            select(Source.id, Source.label, Source.platform, func.count(CollectedItem.id))
            .join(CollectedItem, CollectedItem.source_id == Source.id)
            .where(*item_filters)
            .group_by(Source.id, Source.label, Source.platform)
            .order_by(desc(func.count(CollectedItem.id)))
            .limit(8)
        ).all()

        clusters = session.scalars(issue_query).all()
        keyword_counts: Counter[str] = Counter()
        for cluster in clusters:
            for keyword in (cluster.keywords or [])[:6]:
                keyword_counts[keyword] += max(cluster.recent_count, 1)

        top_issues = session.scalars(
            issue_query.order_by(desc(IssueCluster.score), desc(IssueCluster.latest_at)).limit(8)
        ).all()
        timeline_dates = sorted({*post_rows.keys(), *issue_rows.keys()}, key=parse_bucket_date)
        return AnalyticsStatsRead(
            total_posts=total_posts,
            analyzed_posts=analyzed_posts,
            issue_count=issue_count,
            rising_issue_count=rising_issue_count,
            timeline=[
                AnalyticsTimelineRead(
                    bucket_date=parse_bucket_date(bucket_date),
                    post_count=post_rows.get(bucket_date, 0),
                    issue_count=issue_rows.get(bucket_date, 0),
                )
                for bucket_date in timeline_dates
            ],
            by_category=[
                CountRead(
                    key=row_category or "unknown",
                    label=category_label(row_category or "unknown"),
                    count=count,
                )
                for row_category, count in category_rows
            ],
            top_sources=[
                SourceCountRead(
                    source_id=row_id,
                    label=label,
                    platform=row_platform,
                    count=count,
                )
                for row_id, label, row_platform, count in source_rows
            ],
            top_keywords=[
                CountRead(key=keyword, label=keyword, count=count)
                for keyword, count in keyword_counts.most_common(12)
            ],
            top_issues=[issue_read(cluster) for cluster in top_issues],
        )

    return application


def issue_has_item(
    language: str | None = None,
    source_id: int | None = None,
    platform: str | None = None,
    search: str | None = None,
    full_text: bool = False,
):
    query = (
        select(IssueEvidence.id)
        .join(CollectedItem, CollectedItem.id == IssueEvidence.item_id)
        .where(IssueEvidence.cluster_id == IssueCluster.id)
    )
    if language:
        query = query.where(CollectedItem.language == language)
    if source_id:
        query = query.where(CollectedItem.source_id == source_id)
    if platform:
        query = query.where(CollectedItem.platform == platform)
    if search:
        if full_text:
            query = query.where(
                func.to_tsvector("simple", func.coalesce(CollectedItem.text, "")).op("@@")(
                    func.plainto_tsquery("simple", search)
                )
            )
        else:
            query = query.where(CollectedItem.text.ilike(f"%{search}%"))
    return exists(query)


def item_has_issue(category: str | None = None):
    query = (
        select(IssueEvidence.id)
        .join(IssueCluster, IssueCluster.id == IssueEvidence.cluster_id)
        .where(IssueEvidence.item_id == CollectedItem.id)
    )
    if category:
        query = query.where(IssueCluster.category == category)
    return exists(query)


def post_filters(
    platform: str | None = None,
    language: str | None = None,
    source_id: int | None = None,
    q: str | None = None,
    days: int = 30,
):
    filters = [CollectedItem.posted_at >= datetime.now(UTC) - timedelta(days=days)]
    if platform:
        filters.append(CollectedItem.platform == platform)
    if language:
        filters.append(CollectedItem.language == language)
    if source_id:
        filters.append(CollectedItem.source_id == source_id)
    if q:
        filters.append(CollectedItem.text.ilike(f"%{q}%"))
    return filters


def analytics_post_filters(
    platform: str | None = None,
    language: str | None = None,
    source_id: int | None = None,
    category: str | None = None,
    days: int = 30,
):
    filters = post_filters(
        platform=platform,
        language=language,
        source_id=source_id,
        days=days,
    )
    if category:
        filters.append(item_has_issue(category=category))
    return filters


def issue_read(cluster: IssueCluster) -> IssueRead:
    topic = topic_for_key(cluster.fingerprint)
    return IssueRead(
        id=cluster.id,
        category=topic.category if topic else cluster.category,
        label=topic.label if topic else cluster.label,
        summary=topic.summary if topic else cluster.summary,
        score=cluster.score,
        latest_at=cluster.latest_at,
        recent_count=cluster.recent_count,
        previous_count=cluster.previous_count,
        source_count=cluster.source_count,
        language_counts=cluster.language_counts or {},
        keywords=cluster.keywords or [],
        growth_rate=cluster.growth_rate or 0.0,
        trend=cluster.trend or "stable",
        confidence=cluster.confidence or 0.0,
        total_count=cluster.total_count or 0,
    )


def post_read(item: CollectedItem, source: Source) -> PostRead:
    return PostRead(
        id=item.id,
        source_id=source.id,
        source_label=source.label,
        platform=item.platform,
        language=item.language,
        snippet=snippet(item.text, max_chars=700),
        original_url=item.original_url,
        posted_at=item.posted_at,
        collected_at=item.collected_at,
    )


def language_label(value: str) -> str:
    return {"ar": "Arabic", "en": "English", "unknown": "Unknown"}.get(value, value)


def category_label(value: str) -> str:
    return {
        "services": "الخدمات",
        "prices": "الأسعار",
        "work": "العمل والتصاريح",
        "aid_food": "الغذاء والمساعدات",
        "health": "الصحة",
        "education": "التعليم",
        "mobility": "التنقل",
        "housing": "السكن",
        "safety": "السلامة",
        "other": "أخرى",
        "unknown": "غير معروف",
    }.get(value, value)


def parse_bucket_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def get_or_404(session: Session, model: type, model_id: int):
    value = session.get(model, model_id)
    if not value:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found.")
    return value


app = create_app()
