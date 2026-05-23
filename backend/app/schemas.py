from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Platform = Literal["telegram", "discord", "facebook", "news"]
RunKind = Literal["ingest", "discover", "retention", "analyze"]


class SourceCreate(BaseModel):
    platform: Platform
    label: str = Field(min_length=1, max_length=240)
    url: str | None = Field(default=None, max_length=1200)
    external_id: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    platform_config: dict[str, Any] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=240)
    url: str | None = Field(default=None, max_length=1200)
    external_id: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
    platform_config: dict[str, Any] | None = None


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    label: str
    url: str | None
    external_id: str | None
    enabled: bool
    access_state: str
    health: str | None
    cursor_state: dict[str, Any]
    platform_config: dict[str, Any]
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform: str
    label: str
    url: str | None
    external_id: str | None
    discovered_by: str
    reason: str | None
    status: str
    payload: dict[str, Any]
    reviewed_at: datetime | None
    created_at: datetime


class CandidateReview(BaseModel):
    action: Literal["approve", "reject"]


class RunCreate(BaseModel):
    kind: RunKind = "ingest"


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    trigger: str
    status: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    collected_count: int
    analyzed_count: int
    discovered_count: int
    expired_count: int
    error: str | None


class IssuePointRead(BaseModel):
    bucket_date: date
    count: int
    unique_sources: int


class IssueRead(BaseModel):
    id: int
    category: str
    label: str
    summary: str
    score: float
    latest_at: datetime | None
    recent_count: int
    previous_count: int
    source_count: int
    language_counts: dict[str, int]
    keywords: list[str]
    growth_rate: float
    trend: str
    confidence: float
    total_count: int


class EvidenceRead(BaseModel):
    item_id: int
    source_id: int
    source_label: str
    platform: str
    language: str
    snippet: str
    original_url: str | None
    posted_at: datetime


class IssueDetail(IssueRead):
    evidence: list[EvidenceRead]
    timeline: list[IssuePointRead]


class PostRead(BaseModel):
    id: int
    source_id: int
    source_label: str
    platform: str
    language: str
    snippet: str
    original_url: str | None
    posted_at: datetime
    collected_at: datetime


class CountRead(BaseModel):
    key: str
    label: str
    count: int


class SourceCountRead(BaseModel):
    source_id: int
    label: str
    platform: str
    count: int


class PostTimelineRead(BaseModel):
    bucket_date: date
    count: int


class PostStatsRead(BaseModel):
    total: int
    last_24h: int
    last_7d: int
    by_platform: list[CountRead]
    by_language: list[CountRead]
    top_sources: list[SourceCountRead]
    timeline: list[PostTimelineRead]


class AnalyticsTimelineRead(BaseModel):
    bucket_date: date
    post_count: int
    issue_count: int


class AnalyticsStatsRead(BaseModel):
    total_posts: int
    analyzed_posts: int
    issue_count: int
    rising_issue_count: int
    timeline: list[AnalyticsTimelineRead]
    by_category: list[CountRead]
    top_sources: list[SourceCountRead]
    top_keywords: list[CountRead]
    top_issues: list[IssueRead]
