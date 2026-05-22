from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from math import exp

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import CollectedItem, IssueCluster, IssueEvidence, IssuePoint
from app.services.text import minimize_for_hosted_ai


@dataclass(frozen=True, slots=True)
class IssueTopic:
    key: str
    category: str
    label: str
    summary: str
    keywords: tuple[str, ...]


TOPICS = (
    IssueTopic(
        "power",
        "services",
        "Electricity and power access",
        "Reports about electricity availability, outages, charging, or fuel for power.",
        ("electricity", "power cut", "generator", "charging", "كهربا", "كهرباء", "انقطاع"),
    ),
    IssueTopic(
        "water",
        "services",
        "Water and sanitation access",
        "Reports about drinking water, sanitation, sewage, or basic water service.",
        ("water", "sanitation", "sewage", "مياه", "ماء", "صرف صحي"),
    ),
    IssueTopic(
        "prices",
        "prices",
        "Prices and economic pressure",
        "Reports about prices, affordability, cash, wages, or household economic pressure.",
        ("price", "prices", "expensive", "afford", "cash", "راتب", "اسعار", "أسعار", "غلاء"),
    ),
    IssueTopic(
        "food",
        "aid_food",
        "Food supply and aid gaps",
        "Reports about food access, aid distribution, flour, bread, or hunger.",
        ("food", "flour", "bread", "aid", "hunger", "طعام", "غذاء", "خبز", "طحين", "مساعد"),
    ),
    IssueTopic(
        "health",
        "health",
        "Health access and medicine",
        "Reports about hospitals, medicine, ambulances, treatment, or health access.",
        ("hospital", "medicine", "medical", "ambulance", "clinic", "دواء", "مستشفى", "علاج", "اسعاف"),
    ),
    IssueTopic(
        "education",
        "education",
        "Education disruption",
        "Reports about schools, universities, exams, or learning access.",
        ("school", "university", "exam", "education", "مدرس", "جامعة", "امتحان", "تعليم"),
    ),
    IssueTopic(
        "mobility",
        "mobility",
        "Mobility and access barriers",
        "Reports about roads, checkpoints, transport, crossings, or movement barriers.",
        ("checkpoint", "crossing", "road", "transport", "mobility", "حاجز", "معبر", "طريق", "مواصل"),
    ),
    IssueTopic(
        "housing",
        "housing",
        "Housing and shelter needs",
        "Reports about shelter, tents, homes, rent, displacement housing, or repair needs.",
        ("shelter", "tent", "housing", "rent", "home", "خيمة", "مأوى", "سكن", "منزل", "ايجار"),
    ),
    IssueTopic(
        "safety",
        "safety",
        "Safety and urgent protection",
        "Reports about safety threats, evacuation, attacks, missing people, or urgent protection.",
        ("unsafe", "evacuat", "attack", "missing", "danger", "خطر", "اخلاء", "إخلاء", "مفقود", "قصف"),
    ),
)

ACTIONABLE_FALLBACK = (
    "problem",
    "issue",
    "need",
    "shortage",
    "urgent",
    "مشكلة",
    "بحاجة",
    "نقص",
    "ازمة",
    "أزمة",
)


def match_issue(text: str) -> IssueTopic | None:
    folded = text.casefold()
    for topic in TOPICS:
        if any(keyword.casefold() in folded for keyword in topic.keywords):
            return topic
    if any(keyword.casefold() in folded for keyword in ACTIONABLE_FALLBACK):
        return IssueTopic(
            "other_need",
            "other",
            "Other actionable need",
            "Reports that describe an actionable need not yet assigned to a stronger MVP topic.",
            ACTIONABLE_FALLBACK,
        )
    return None


def attach_item_to_issue(session: Session, item: CollectedItem) -> IssueCluster | None:
    topic = match_issue(item.text)
    if not topic:
        return None

    cluster = session.scalar(
        select(IssueCluster).where(IssueCluster.fingerprint == topic.key)
    )
    if not cluster:
        cluster = IssueCluster(
            fingerprint=topic.key,
            category=topic.category,
            label=topic.label,
            summary=topic.summary,
        )
        session.add(cluster)
        session.flush()

    existing_link = session.scalar(
        select(IssueEvidence.id).where(
            IssueEvidence.cluster_id == cluster.id,
            IssueEvidence.item_id == item.id,
        )
    )
    if existing_link:
        return cluster

    session.add(IssueEvidence(cluster_id=cluster.id, item_id=item.id))
    session.flush()
    update_point(session, cluster, item)
    refresh_cluster_metrics(session, cluster)
    return cluster


def update_point(session: Session, cluster: IssueCluster, item: CollectedItem) -> None:
    bucket = item.posted_at.date()
    point = session.scalar(
        select(IssuePoint).where(
            IssuePoint.cluster_id == cluster.id,
            IssuePoint.bucket_date == bucket,
        )
    )
    if not point:
        point = IssuePoint(cluster_id=cluster.id, bucket_date=bucket)
        session.add(point)
        session.flush()

    start = datetime.combine(bucket, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    point.count = session.scalar(
        evidence_items(cluster.id)
        .where(CollectedItem.posted_at >= start, CollectedItem.posted_at < end)
        .with_only_columns(func.count(CollectedItem.id))
    ) or 0
    point.unique_sources = session.scalar(
        evidence_items(cluster.id)
        .where(CollectedItem.posted_at >= start, CollectedItem.posted_at < end)
        .with_only_columns(func.count(func.distinct(CollectedItem.source_id)))
    ) or 0


def refresh_all_clusters(session: Session) -> None:
    for cluster in session.scalars(select(IssueCluster)):
        refresh_cluster_metrics(session, cluster)


def refresh_cluster_metrics(
    session: Session, cluster: IssueCluster, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    recent_start = now - timedelta(days=7)
    previous_start = now - timedelta(days=14)
    base = evidence_items(cluster.id)

    cluster.recent_count = session.scalar(
        base.where(CollectedItem.posted_at >= recent_start).with_only_columns(
            func.count(CollectedItem.id)
        )
    ) or 0
    cluster.previous_count = session.scalar(
        base.where(
            CollectedItem.posted_at >= previous_start,
            CollectedItem.posted_at < recent_start,
        ).with_only_columns(func.count(CollectedItem.id))
    ) or 0
    cluster.source_count = session.scalar(
        base.where(CollectedItem.posted_at >= recent_start).with_only_columns(
            func.count(func.distinct(CollectedItem.source_id))
        )
    ) or 0
    cluster.latest_at = session.scalar(
        base.with_only_columns(func.max(CollectedItem.posted_at))
    )
    cluster.language_counts = dict(
        session.execute(
            base.where(CollectedItem.posted_at >= recent_start)
            .with_only_columns(CollectedItem.language, func.count(CollectedItem.id))
            .group_by(CollectedItem.language)
        ).all()
    )
    growth = max(cluster.recent_count - cluster.previous_count, 0) / max(
        cluster.previous_count, 1
    )
    latest_at = ensure_utc(cluster.latest_at)
    age_hours = max((now - latest_at).total_seconds() / 3600, 0) if latest_at else 7 * 24
    recency_boost = 4 * exp(-age_hours / 72)
    cluster.score = round(
        cluster.recent_count * 2 + cluster.source_count * 1.5 + growth * 1.2 + recency_boost,
        3,
    )


def evidence_items(cluster_id: int) -> Select[tuple[CollectedItem]]:
    return (
        select(CollectedItem)
        .join(IssueEvidence, IssueEvidence.item_id == CollectedItem.id)
        .where(IssueEvidence.cluster_id == cluster_id)
    )


def hosted_ai_snippets(items: list[CollectedItem]) -> list[str]:
    return [minimize_for_hosted_ai(item.text) for item in items]


def ensure_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)
