from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from hashlib import sha1
from math import exp, sqrt

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session
from sklearn.cluster import DBSCAN
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize as normalize_vectors

from app.config import get_settings
from app.models import CollectedItem, IssueCluster, IssueEvidence, IssuePoint
from app.services.text import minimize_for_hosted_ai, normalize_text


@dataclass(frozen=True, slots=True)
class IssueTopic:
    key: str
    category: str
    label: str
    summary: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssueCandidate:
    item: CollectedItem
    topic: IssueTopic


@dataclass(frozen=True, slots=True)
class ClusterDraft:
    topic: IssueTopic
    items: list[CollectedItem]
    keywords: list[str]
    confidence: float
    embedding: list[float] | None


CATEGORY_LABELS = {
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
}

CATEGORY_WEIGHTS = {
    "safety": 1.35,
    "health": 1.28,
    "services": 1.18,
    "aid_food": 1.18,
    "housing": 1.08,
}

TOPICS = (
    IssueTopic(
        "safety",
        "safety",
        "السلامة والحماية العاجلة",
        "بلاغات عن التهديدات، الإخلاء، الهجمات، المفقودين، أو الحماية العاجلة.",
        (
            "unsafe",
            "evacuat",
            "attack",
            "missing",
            "danger",
            "خطر",
            "اخلاء",
            "إخلاء",
            "مفقود",
            "قصف",
            "اصابة",
            "اصابات",
            "جرحى",
            "شهيد",
            "شهداء",
            "اعتقال",
        ),
    ),
    IssueTopic(
        "health",
        "health",
        "الوصول إلى الرعاية الصحية والدواء",
        "بلاغات عن المستشفيات، الدواء، الإسعاف، العلاج، أو الوصول إلى الرعاية الصحية.",
        (
            "hospital",
            "medicine",
            "medical",
            "ambulance",
            "clinic",
            "دواء",
            "ادوية",
            "مستشفى",
            "علاج",
            "اسعاف",
            "صحة",
            "طبيب",
            "تمريض",
            "مرضى",
        ),
    ),
    IssueTopic(
        "water",
        "services",
        "الوصول إلى المياه والصرف الصحي",
        "بلاغات عن مياه الشرب، الصرف الصحي، المجاري، أو خدمات المياه الأساسية.",
        ("water", "sanitation", "sewage", "مياه", "ماء", "صرف صحي", "مجاري", "صهاريج"),
    ),
    IssueTopic(
        "food",
        "aid_food",
        "نقص الغذاء والمساعدات",
        "بلاغات عن توفر الغذاء، توزيع المساعدات، الطحين، الخبز، أو الجوع.",
        (
            "food",
            "flour",
            "bread",
            "aid",
            "hunger",
            "طعام",
            "غذاء",
            "خبز",
            "طحين",
            "مساعد",
            "اغاث",
            "سلة",
        ),
    ),
    IssueTopic(
        "mobility",
        "mobility",
        "عوائق التنقل والوصول",
        "بلاغات عن الطرق، الحواجز، المواصلات، المعابر، أو قيود الحركة.",
        (
            "checkpoint",
            "crossing",
            "road",
            "transport",
            "mobility",
            "حاجز",
            "حواجز",
            "معبر",
            "طريق",
            "طرق",
            "مواصل",
            "اغلاق",
            "إغلاق",
        ),
    ),
    IssueTopic(
        "housing",
        "housing",
        "احتياجات السكن والمأوى",
        "بلاغات عن المأوى، الخيام، المنازل، الإيجار، سكن النزوح، أو احتياجات الإصلاح.",
        (
            "shelter",
            "tent",
            "housing",
            "rent",
            "home",
            "خيمة",
            "خيام",
            "مأوى",
            "ماوى",
            "سكن",
            "منزل",
            "بيوت",
            "ايجار",
            "إيجار",
        ),
    ),
    IssueTopic(
        "prices",
        "prices",
        "الأسعار والضغط المعيشي",
        "بلاغات عن الأسعار، القدرة على الشراء، السيولة، الأجور، أو الضغط الاقتصادي على الأسر.",
        (
            "price",
            "prices",
            "expensive",
            "afford",
            "cash",
            "راتب",
            "رواتب",
            "اسعار",
            "أسعار",
            "غلاء",
            "شيكل",
            "تكلفة",
        ),
    ),
    IssueTopic(
        "work",
        "work",
        "العمل والتصاريح والوظائف",
        "بلاغات عن الوظائف، تصاريح العمل، العمال، فرص العمل، أو شروط التشغيل.",
        (
            "job",
            "jobs",
            "work permit",
            "worker",
            "وظيفة",
            "وظائف",
            "عمل",
            "عمال",
            "تصريح",
            "تصاريح",
            "تشغيل",
            "شواغر",
        ),
    ),
    IssueTopic(
        "education",
        "education",
        "تعطل التعليم",
        "بلاغات عن المدارس، الجامعات، الامتحانات، أو الوصول إلى التعليم.",
        (
            "school",
            "university",
            "exam",
            "education",
            "مدرس",
            "مدارس",
            "جامعة",
            "جامعات",
            "امتحان",
            "تعليم",
            "طلبة",
            "طلاب",
        ),
    ),
    IssueTopic(
        "power",
        "services",
        "الوصول إلى الكهرباء والطاقة",
        "بلاغات عن توفر الكهرباء، الانقطاعات، الشحن، أو الوقود اللازم للطاقة.",
        (
            "electricity",
            "power cut",
            "generator",
            "charging",
            "كهربا",
            "كهرباء",
            "انقطاع",
            "مولد",
            "وقود",
        ),
    ),
)

TOPICS_BY_KEY = {topic.key: topic for topic in TOPICS}

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

STOP_WORDS = {
    "في",
    "من",
    "على",
    "علي",
    "الى",
    "إلى",
    "الي",
    "عن",
    "مع",
    "هذا",
    "هذه",
    "ذلك",
    "تلك",
    "هناك",
    "هنا",
    "اليوم",
    "امس",
    "أمس",
    "غدا",
    "بعد",
    "قبل",
    "كل",
    "او",
    "أو",
    "ان",
    "أن",
    "إن",
    "كان",
    "كانت",
    "يكون",
    "تم",
    "يتم",
    "هو",
    "هي",
    "هم",
    "كما",
    "حتى",
    "ضمن",
    "خلال",
    "بسبب",
    "لدى",
    "عند",
    "اذا",
    "إذا",
    "غير",
    "ما",
    "لا",
    "التي",
    "الذي",
    "الذين",
    "the",
    "and",
    "for",
    "from",
    "with",
    "this",
    "that",
    "are",
    "was",
    "were",
    "will",
    "http",
    "https",
    "www",
    "com",
    "html",
    "motqdmon",
    "رابط",
    "الرابط",
}
TOKEN_RE = re.compile(r"[\w\u0600-\u06ff]{2,}")
MAX_EMBEDDING_DIMENSIONS = 384


def match_issue(text: str) -> IssueTopic | None:
    folded = normalize_text(text).casefold()
    for topic in TOPICS:
        if any(keyword.casefold() in folded for keyword in topic.keywords):
            return topic
    if any(keyword.casefold() in folded for keyword in ACTIONABLE_FALLBACK):
        return IssueTopic(
            "other_need",
            "other",
            "احتياجات أخرى قابلة للمعالجة",
            "بلاغات تصف احتياجا قابلا للمعالجة ولم يصنف بعد ضمن موضوع أقوى في النسخة الأولى.",
            ACTIONABLE_FALLBACK,
        )
    return None


def topic_for_key(key: str) -> IssueTopic | None:
    if key == "other_need":
        return IssueTopic(
            "other_need",
            "other",
            "احتياجات أخرى قابلة للمعالجة",
            "بلاغات تصف احتياجا قابلا للمعالجة ولم يصنف بعد ضمن موضوع أقوى في النسخة الأولى.",
            ACTIONABLE_FALLBACK,
        )
    return TOPICS_BY_KEY.get(key)


def rebuild_issue_clusters(
    session: Session, days: int | None = None, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    window_days = days or get_settings().retention_days
    cutoff = now - timedelta(days=window_days)
    candidates = issue_candidates(session, cutoff)
    drafts = build_cluster_drafts(candidates)

    session.execute(delete(IssuePoint))
    session.execute(delete(IssueEvidence))
    session.execute(delete(IssueCluster))
    session.flush()

    analyzed_count = 0
    use_embeddings = session.get_bind().dialect.name == "postgresql"
    for draft in drafts:
        cluster = IssueCluster(
            fingerprint=cluster_fingerprint(draft),
            category=draft.topic.category,
            label=cluster_label(draft.topic, draft.keywords),
            summary=cluster_summary(draft.topic, draft.keywords, len(draft.items)),
            keywords=draft.keywords,
            confidence=draft.confidence,
            embedding=pad_embedding(draft.embedding) if use_embeddings else None,
        )
        session.add(cluster)
        session.flush()
        for item in draft.items:
            session.add(IssueEvidence(cluster_id=cluster.id, item_id=item.id))
        session.flush()
        rebuild_cluster_points(session, cluster, draft.items)
        refresh_cluster_metrics(session, cluster, now=now)
        analyzed_count += len(draft.items)

    session.commit()
    return analyzed_count


def issue_candidates(session: Session, cutoff: datetime) -> list[IssueCandidate]:
    rows = session.scalars(
        select(CollectedItem)
        .where(CollectedItem.posted_at >= cutoff)
        .order_by(CollectedItem.posted_at)
    ).all()
    candidates: list[IssueCandidate] = []
    recent_hashes: dict[str, datetime] = {}
    for item in rows:
        previous_at = recent_hashes.get(item.content_hash)
        if previous_at and item.posted_at - previous_at <= timedelta(days=7):
            continue
        topic = match_issue(item.text)
        if not topic:
            continue
        recent_hashes[item.content_hash] = item.posted_at
        candidates.append(IssueCandidate(item=item, topic=topic))
    return candidates


def build_cluster_drafts(candidates: list[IssueCandidate]) -> list[ClusterDraft]:
    by_topic: dict[str, list[IssueCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_topic[candidate.topic.key].append(candidate)

    drafts: list[ClusterDraft] = []
    for topic_key, topic_candidates in by_topic.items():
        topic = topic_candidates[0].topic
        drafts.extend(cluster_topic_candidates(topic, topic_candidates))
    return sorted(
        drafts,
        key=lambda draft: (len(draft.items), max(item.posted_at for item in draft.items)),
        reverse=True,
    )


def cluster_topic_candidates(
    topic: IssueTopic, candidates: list[IssueCandidate]
) -> list[ClusterDraft]:
    if len(candidates) <= 1:
        return [draft_from_candidates(topic, candidates, None, 0.35)]

    texts = [candidate.item.text for candidate in candidates]
    vectors, feature_vectors = vectorize_texts(texts)
    if vectors is None or feature_vectors is None:
        return [draft_from_candidates(topic, [candidate], None, 0.35) for candidate in candidates]

    labels = DBSCAN(eps=0.9, min_samples=2, metric="cosine").fit_predict(vectors)
    grouped: dict[int, list[int]] = defaultdict(list)
    noise_index = -1
    for index, label in enumerate(labels):
        if label == -1:
            grouped[noise_index].append(index)
            noise_index -= 1
        else:
            grouped[int(label)].append(index)

    drafts: list[ClusterDraft] = []
    for indexes in grouped.values():
        cluster_candidates = [candidates[index] for index in indexes]
        cluster_vectors = vectors[indexes]
        confidence = cluster_confidence(cluster_vectors, len(cluster_candidates))
        centroid = cluster_vectors.mean(axis=0).tolist()
        drafts.append(draft_from_candidates(topic, cluster_candidates, centroid, confidence))
    return drafts


def vectorize_texts(texts: list[str]):
    try:
        vectorizer = TfidfVectorizer(
            max_df=1.0,
            min_df=1,
            ngram_range=(1, 2),
            tokenizer=vector_tokens,
            token_pattern=None,
            lowercase=False,
        )
        tfidf = vectorizer.fit_transform(texts)
    except ValueError:
        return None, None

    if tfidf.shape[0] >= 8 and min(tfidf.shape) > 2:
        components = min(32, tfidf.shape[0] - 1, tfidf.shape[1] - 1)
        reduced = TruncatedSVD(n_components=components, random_state=13).fit_transform(tfidf)
        return normalize_vectors(reduced), tfidf
    return normalize_vectors(tfidf.toarray()), tfidf


def draft_from_candidates(
    topic: IssueTopic,
    candidates: list[IssueCandidate],
    embedding: list[float] | None,
    confidence: float,
) -> ClusterDraft:
    items = [candidate.item for candidate in candidates]
    keywords = extract_keywords([item.text for item in items])
    return ClusterDraft(
        topic=topic,
        items=items,
        keywords=keywords,
        confidence=round(confidence, 3),
        embedding=embedding,
    )


def extract_keywords(texts: list[str], limit: int = 6) -> list[str]:
    normalized_texts = [normalize_text(text) for text in texts if normalize_text(text)]
    if not normalized_texts:
        return []
    try:
        vectorizer = TfidfVectorizer(
            max_features=40,
            ngram_range=(1, 1),
            tokenizer=vector_tokens,
            token_pattern=None,
            lowercase=False,
        )
        matrix = vectorizer.fit_transform(normalized_texts)
        features = vectorizer.get_feature_names_out()
        scores = matrix.sum(axis=0).A1
        ordered = [features[index] for index in scores.argsort()[::-1]]
    except ValueError:
        ordered = [word for word, _ in Counter(tokenize(" ".join(normalized_texts))).most_common()]

    keywords: list[str] = []
    for keyword in ordered:
        cleaned = keyword.strip("_- ")
        if not cleaned or cleaned.casefold() in STOP_WORDS:
            continue
        if cleaned.isnumeric() or len(cleaned) < 2:
            continue
        keywords.append(cleaned)
        if len(keywords) >= limit:
            break
    return keywords


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_RE.findall(normalize_text(text).casefold())
        if token not in STOP_WORDS and not token.isnumeric()
    ]


def vector_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in tokenize(text):
        tokens.append(token)
        if token.startswith("ال") and len(token) > 4:
            tokens.append(token[2:])
    return tokens


def cluster_confidence(vectors, size: int) -> float:
    if size <= 1:
        return 0.35
    similarity = cosine_similarity(vectors)
    density = float((similarity.sum() - size) / max(size * (size - 1), 1))
    return min(0.98, 0.45 + min(size, 12) * 0.03 + max(density, 0) * 0.25)


def cluster_fingerprint(draft: ClusterDraft) -> str:
    item_ids = "|".join(str(item.id) for item in draft.items[:8])
    material = "|".join(draft.keywords[:6]) or item_ids
    material = f"{material}:{item_ids}"
    digest = sha1(f"{draft.topic.key}:{material}".encode("utf-8")).hexdigest()[:14]
    return f"ml:{draft.topic.key}:{digest}"


def cluster_label(topic: IssueTopic, keywords: list[str]) -> str:
    prefix = CATEGORY_LABELS.get(topic.category, topic.label)
    if not keywords:
        return topic.label
    return f"{prefix}: {'، '.join(keywords[:3])}"


def cluster_summary(topic: IssueTopic, keywords: list[str], count: int) -> str:
    if keywords:
        focus = "، ".join(keywords[:4])
        return f"{count} منشورات مرتبطة حول {focus} ضمن {topic.label}."
    return f"{count} منشورات مرتبطة ضمن {topic.label}."


def pad_embedding(embedding: list[float] | None) -> list[float] | None:
    if embedding is None:
        return None
    padded = list(embedding[:MAX_EMBEDDING_DIMENSIONS])
    padded.extend([0.0] * (MAX_EMBEDDING_DIMENSIONS - len(padded)))
    return padded


def rebuild_cluster_points(
    session: Session, cluster: IssueCluster, items: list[CollectedItem]
) -> None:
    counts: dict[datetime.date, int] = defaultdict(int)
    sources: dict[datetime.date, set[int]] = defaultdict(set)
    for item in items:
        bucket = item.posted_at.date()
        counts[bucket] += 1
        sources[bucket].add(item.source_id)

    for bucket, count in counts.items():
        session.add(
            IssuePoint(
                cluster_id=cluster.id,
                bucket_date=bucket,
                count=count,
                unique_sources=len(sources[bucket]),
            )
        )


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
            keywords=[],
            confidence=0.35,
        )
        session.add(cluster)
        session.flush()
    else:
        cluster.category = topic.category
        cluster.label = topic.label
        cluster.summary = topic.summary

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

    cluster.total_count = session.scalar(
        base.with_only_columns(func.count(CollectedItem.id))
    ) or 0
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
    cluster.growth_rate = growth_rate(cluster.recent_count, cluster.previous_count)
    cluster.trend = trend_label(cluster.recent_count, cluster.previous_count)
    latest_at = ensure_utc(cluster.latest_at)
    age_hours = max((now - latest_at).total_seconds() / 3600, 0) if latest_at else 7 * 24
    recency_boost = 6 * exp(-age_hours / 72)
    growth_component = min(max(cluster.growth_rate, 0), 5) * 3
    category_weight = CATEGORY_WEIGHTS.get(cluster.category, 1.0)
    cluster.score = round(
        (
            cluster.recent_count * 2.2
            + sqrt(max(cluster.total_count, 0)) * 1.2
            + cluster.source_count * 2
            + growth_component
            + recency_boost
            + (cluster.confidence or 0) * 5
        )
        * category_weight,
        3,
    )


def growth_rate(recent_count: int, previous_count: int) -> float:
    if previous_count == 0:
        return float(recent_count) if recent_count else 0.0
    return round((recent_count - previous_count) / previous_count, 3)


def trend_label(recent_count: int, previous_count: int) -> str:
    if recent_count > 0 and previous_count == 0:
        return "new"
    if recent_count >= 2 and recent_count > previous_count:
        return "rising"
    if previous_count > recent_count:
        return "falling"
    return "stable"


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
