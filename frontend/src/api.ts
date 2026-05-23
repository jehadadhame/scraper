export type Platform = "telegram" | "discord" | "facebook" | "news";
export type View = "issues" | "analytics" | "posts" | "sources" | "discovery" | "runs";

export interface Source {
  id: number;
  platform: Platform;
  label: string;
  url: string | null;
  external_id: string | null;
  enabled: boolean;
  access_state: string;
  health: string | null;
  cursor_state: Record<string, unknown>;
  platform_config: Record<string, unknown>;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Candidate {
  id: number;
  platform: Platform;
  label: string;
  url: string | null;
  external_id: string | null;
  discovered_by: string;
  reason: string | null;
  status: string;
  payload: Record<string, unknown>;
  reviewed_at: string | null;
  created_at: string;
}

export interface Run {
  id: number;
  kind: "ingest" | "discover" | "retention" | "analyze";
  trigger: string;
  status: string;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  collected_count: number;
  analyzed_count: number;
  discovered_count: number;
  expired_count: number;
  error: string | null;
}

export interface Issue {
  id: number;
  category: string;
  label: string;
  summary: string;
  score: number;
  latest_at: string | null;
  recent_count: number;
  previous_count: number;
  source_count: number;
  language_counts: Record<string, number>;
  keywords: string[];
  growth_rate: number;
  trend: string;
  confidence: number;
  total_count: number;
}

export interface Evidence {
  item_id: number;
  source_id: number;
  source_label: string;
  platform: Platform;
  language: string;
  snippet: string;
  original_url: string | null;
  posted_at: string;
}

export interface Point {
  bucket_date: string;
  count: number;
  unique_sources: number;
}

export interface IssueDetail extends Issue {
  evidence: Evidence[];
  timeline: Point[];
}

export interface IssueFilters {
  q: string;
  category: string;
  language: string;
  trend: string;
  days: string;
  sourceId: string;
}

export interface Post {
  id: number;
  source_id: number;
  source_label: string;
  platform: Platform;
  language: string;
  snippet: string;
  original_url: string | null;
  posted_at: string;
  collected_at: string;
}

export interface Count {
  key: string;
  label: string;
  count: number;
}

export interface SourceCount {
  source_id: number;
  label: string;
  platform: Platform;
  count: number;
}

export interface PostTimelinePoint {
  bucket_date: string;
  count: number;
}

export interface PostStats {
  total: number;
  last_24h: number;
  last_7d: number;
  by_platform: Count[];
  by_language: Count[];
  top_sources: SourceCount[];
  timeline: PostTimelinePoint[];
}

export interface PostFilters {
  q: string;
  platform: string;
  language: string;
  sourceId: string;
  days: string;
  limit: string;
}

export interface AnalyticsTimelinePoint {
  bucket_date: string;
  post_count: number;
  issue_count: number;
}

export interface AnalyticsStats {
  total_posts: number;
  analyzed_posts: number;
  issue_count: number;
  rising_issue_count: number;
  timeline: AnalyticsTimelinePoint[];
  by_category: Count[];
  top_sources: SourceCount[];
  top_keywords: Count[];
  top_issues: Issue[];
}

export interface AnalyticsFilters {
  category: string;
  platform: string;
  language: string;
  sourceId: string;
  days: string;
}

const apiRoot = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiRoot}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export function issueQuery(filters: IssueFilters): string {
  const params = new URLSearchParams();
  Object.entries({
    q: filters.q,
    category: filters.category,
    language: filters.language,
    trend: filters.trend,
    days: filters.days,
    source_id: filters.sourceId,
  }).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString();
  return `/issues${query ? `?${query}` : ""}`;
}

export function postQuery(filters: PostFilters): string {
  const params = postParams(filters);
  if (filters.limit) params.set("limit", filters.limit);
  const query = params.toString();
  return `/posts${query ? `?${query}` : ""}`;
}

export function postStatsQuery(filters: PostFilters): string {
  const query = postParams(filters).toString();
  return `/posts/stats${query ? `?${query}` : ""}`;
}

export function analyticsQuery(filters: AnalyticsFilters): string {
  const params = new URLSearchParams();
  Object.entries({
    category: filters.category,
    platform: filters.platform,
    language: filters.language,
    days: filters.days,
    source_id: filters.sourceId,
  }).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString();
  return `/analytics${query ? `?${query}` : ""}`;
}

function postParams(filters: PostFilters): URLSearchParams {
  const params = new URLSearchParams();
  Object.entries({
    q: filters.q,
    platform: filters.platform,
    language: filters.language,
    days: filters.days,
    source_id: filters.sourceId,
  }).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params;
}
