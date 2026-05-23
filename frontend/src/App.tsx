import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Check,
  Clock3,
  DatabaseZap,
  FileSearch,
  Filter,
  Newspaper,
  Plus,
  RefreshCcw,
  Search,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  Candidate,
  Issue,
  IssueDetail,
  IssueFilters,
  issueQuery,
  Platform,
  Post,
  PostFilters,
  postQuery,
  PostStats,
  postStatsQuery,
  Run,
  Source,
  View,
} from "./api";

const defaultFilters: IssueFilters = {
  q: "",
  category: "",
  language: "",
  trend: "active",
  days: "14",
  sourceId: "",
};

const defaultPostFilters: PostFilters = {
  q: "",
  platform: "",
  language: "",
  sourceId: "",
  days: "30",
  limit: "100",
};

const platforms: Platform[] = ["telegram", "discord", "facebook", "news"];
const categories = [
  "services",
  "prices",
  "aid_food",
  "health",
  "education",
  "mobility",
  "housing",
  "safety",
  "other",
];
const categoryLabels: Record<string, string> = {
  services: "الخدمات",
  prices: "الأسعار",
  aid_food: "الغذاء والمساعدات",
  health: "الصحة",
  education: "التعليم",
  mobility: "التنقل",
  housing: "السكن",
  safety: "السلامة",
  other: "أخرى",
};
const languageLabels: Record<string, string> = {
  ar: "Arabic",
  en: "English",
  unknown: "Unknown",
};

export function App() {
  const [view, setView] = useState<View>("issues");
  const [sources, setSources] = useState<Source[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issueDetail, setIssueDetail] = useState<IssueDetail | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [postStats, setPostStats] = useState<PostStats | null>(null);
  const [filters, setFilters] = useState(defaultFilters);
  const [postFilters, setPostFilters] = useState(defaultPostFilters);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const loadBase = useCallback(async () => {
    try {
      const [nextSources, nextCandidates, nextRuns] = await Promise.all([
        api<Source[]>("/sources"),
        api<Candidate[]>("/discovery-candidates"),
        api<Run[]>("/runs"),
      ]);
      setSources(nextSources);
      setCandidates(nextCandidates);
      setRuns(nextRuns);
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  }, []);

  const loadIssues = useCallback(async () => {
    try {
      const nextIssues = await api<Issue[]>(issueQuery(filters));
      setIssues(nextIssues);
      if (!nextIssues.find((issue) => issue.id === issueDetail?.id)) {
        setIssueDetail(null);
      }
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  }, [filters, issueDetail?.id]);

  const loadPosts = useCallback(async () => {
    try {
      const [nextPosts, nextStats] = await Promise.all([
        api<Post[]>(postQuery(postFilters)),
        api<PostStats>(postStatsQuery(postFilters)),
      ]);
      setPosts(nextPosts);
      setPostStats(nextStats);
    } catch (nextError) {
      setError(errorMessage(nextError));
    }
  }, [postFilters]);

  useEffect(() => {
    void loadBase();
  }, [loadBase]);

  useEffect(() => {
    void loadIssues();
  }, [loadIssues]);

  useEffect(() => {
    void loadPosts();
  }, [loadPosts]);

  async function refreshAll() {
    setBusy("refresh");
    setError("");
    await Promise.all([loadBase(), loadIssues(), loadPosts()]);
    setBusy("");
  }

  async function triggerRun(kind: Run["kind"]) {
    setBusy(kind);
    setError("");
    try {
      await api<Run>("/runs", {
        method: "POST",
        body: JSON.stringify({ kind }),
      });
      await loadBase();
      setView("runs");
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy("");
    }
  }

  async function selectIssue(issueId: number) {
    setBusy(`issue-${issueId}`);
    setError("");
    try {
      setIssueDetail(await api<IssueDetail>(`/issues/${issueId}`));
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy("");
    }
  }

  async function reviewCandidate(candidateId: number, action: "approve" | "reject") {
    setBusy(`candidate-${candidateId}`);
    setError("");
    try {
      await api<Candidate>(`/discovery-candidates/${candidateId}/review`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      await loadBase();
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy("");
    }
  }

  async function updateSource(source: Source, patch: Partial<Source>) {
    setBusy(`source-${source.id}`);
    setError("");
    try {
      await api<Source>(`/sources/${source.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      await loadBase();
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy("");
    }
  }

  async function deleteSource(sourceId: number) {
    setBusy(`source-${sourceId}`);
    setError("");
    try {
      await api<void>(`/sources/${sourceId}`, { method: "DELETE" });
      await loadBase();
    } catch (nextError) {
      setError(errorMessage(nextError));
    } finally {
      setBusy("");
    }
  }

  const sourceCounts = useMemo(
    () =>
      platforms.map((platform) => ({
        platform,
        count: sources.filter((source) => source.platform === platform).length,
      })),
    [sources],
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <strong>Palestine Signals</strong>
          <span>{issues.length} قضايا نشطة · {postStats?.total ?? posts.length} posts</span>
        </div>
        <nav className="tabs" aria-label="Dashboard views">
          <Tab view={view} value="issues" label="القضايا" onSelect={setView} icon={<Activity />} />
          <Tab view={view} value="posts" label="Posts" onSelect={setView} icon={<BarChart3 />} />
          <Tab view={view} value="sources" label="Sources" onSelect={setView} icon={<DatabaseZap />} />
          <Tab view={view} value="discovery" label="Review" onSelect={setView} icon={<FileSearch />} />
          <Tab view={view} value="runs" label="Runs" onSelect={setView} icon={<Clock3 />} />
        </nav>
        <div className="toolbar">
          <IconButton
            label="Refresh dashboard"
            onClick={() => void refreshAll()}
            disabled={Boolean(busy)}
            icon={<RefreshCcw />}
          />
          <RunButton label="Collect" onClick={() => void triggerRun("ingest")} busy={busy === "ingest"} icon={<DatabaseZap />} />
          <RunButton label="Discover" onClick={() => void triggerRun("discover")} busy={busy === "discover"} icon={<Search />} />
        </div>
      </header>

      <section className="source-strip" aria-label="Source totals">
        {sourceCounts.map(({ platform, count }) => (
          <div className={`source-count ${platform}`} key={platform}>
            <span>{platform}</span>
            <strong>{count}</strong>
          </div>
        ))}
      </section>

      {error ? <div className="error-banner">{error}</div> : null}
      <SourceAccessNotice sources={sources} onSources={() => setView("sources")} />

      {view === "issues" ? (
        <IssuesView
          filters={filters}
          sources={sources}
          issues={issues}
          issueDetail={issueDetail}
          busy={busy}
          onFilter={setFilters}
          onSelect={selectIssue}
        />
      ) : null}
      {view === "sources" ? (
        <SourcesView
          sources={sources}
          busy={busy}
          onCreate={loadBase}
          onUpdate={updateSource}
          onDelete={deleteSource}
          onError={setError}
        />
      ) : null}
      {view === "posts" ? (
        <PostsView
          filters={postFilters}
          sources={sources}
          posts={posts}
          stats={postStats}
          onFilter={setPostFilters}
        />
      ) : null}
      {view === "discovery" ? (
        <DiscoveryView candidates={candidates} busy={busy} onReview={reviewCandidate} />
      ) : null}
      {view === "runs" ? <RunsView runs={runs} onRetention={() => void triggerRun("retention")} /> : null}
    </main>
  );
}

function IssuesView({
  filters,
  sources,
  issues,
  issueDetail,
  busy,
  onFilter,
  onSelect,
}: {
  filters: IssueFilters;
  sources: Source[];
  issues: Issue[];
  issueDetail: IssueDetail | null;
  busy: string;
  onFilter: (filters: IssueFilters) => void;
  onSelect: (issueId: number) => Promise<void>;
}) {
  return (
    <section className="workspace issues-workspace">
      <aside className="filter-rail" dir="rtl">
        <h2><Filter /> الفلاتر</h2>
        <label>
          بحث
          <input
            value={filters.q}
            onChange={(event) => onFilter({ ...filters, q: event.target.value })}
            placeholder="مياه، دواء، أسعار"
          />
        </label>
        <label>
          الفئة
          <select value={filters.category} onChange={(event) => onFilter({ ...filters, category: event.target.value })}>
            <option value="">الكل</option>
            {categories.map((category) => <option key={category} value={category}>{categoryLabel(category)}</option>)}
          </select>
        </label>
        <label>
          اللغة
          <select value={filters.language} onChange={(event) => onFilter({ ...filters, language: event.target.value })}>
            <option value="">الكل</option>
            <option value="ar">العربية</option>
            <option value="en">الإنجليزية</option>
          </select>
        </label>
        <label>
          الاتجاه
          <select value={filters.trend} onChange={(event) => onFilter({ ...filters, trend: event.target.value })}>
            <option value="">الكل</option>
            <option value="active">نشط</option>
            <option value="rising">صاعد</option>
          </select>
        </label>
        <label>
          الفترة
          <select value={filters.days} onChange={(event) => onFilter({ ...filters, days: event.target.value })}>
            <option value="7">7 أيام</option>
            <option value="14">14 يوما</option>
            <option value="30">30 يوما</option>
            <option value="90">90 يوما</option>
          </select>
        </label>
        <label>
          المصدر
          <select value={filters.sourceId} onChange={(event) => onFilter({ ...filters, sourceId: event.target.value })}>
            <option value="">الكل</option>
            {sources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
          </select>
        </label>
      </aside>

      <section className="issue-list" aria-label="Issue clusters">
        {issues.map((issue) => (
          <button
            className={`issue-row ${issueDetail?.id === issue.id ? "selected" : ""}`}
            disabled={busy === `issue-${issue.id}`}
            key={issue.id}
            onClick={() => void onSelect(issue.id)}
          >
            <div className="issue-copy" dir="rtl">
              <strong>{issue.label}</strong>
              <span>{issue.summary}</span>
            </div>
            <dl>
              <Stat label="الدرجة" value={issue.score.toFixed(1)} />
              <Stat label="7 أيام" value={String(issue.recent_count)} />
              <Stat label="المصادر" value={String(issue.source_count)} />
            </dl>
          </button>
        ))}
        {!issues.length ? <EmptyState icon={<Newspaper />} title="لا توجد قضايا بعد" /> : null}
      </section>

      <section className="detail-pane" aria-label="Issue detail">
        {issueDetail ? <IssueDetailPane issue={issueDetail} /> : <EmptyState icon={<Activity />} title="اختر قضية" />}
      </section>
    </section>
  );
}

function IssueDetailPane({ issue }: { issue: IssueDetail }) {
  const peak = Math.max(...issue.timeline.map((point) => point.count), 1);
  return (
    <>
      <header className="detail-header">
        <div className="issue-copy" dir="rtl">
          <p>{categoryLabel(issue.category)}</p>
          <h1>{issue.label}</h1>
          <span>{issue.summary}</span>
        </div>
        <dl>
          <Stat label="الدرجة" value={issue.score.toFixed(1)} />
          <Stat label="حديث" value={String(issue.recent_count)} />
          <Stat label="السابق" value={String(issue.previous_count)} />
        </dl>
      </header>
      <section className="timeline">
        {issue.timeline.map((point) => (
          <div key={point.bucket_date} className="bar-slot" title={`${point.bucket_date}: ${point.count}`}>
            <i style={{ height: `${Math.max((point.count / peak) * 100, 8)}%` }} />
            <span>{point.bucket_date.slice(5)}</span>
          </div>
        ))}
      </section>
      <section className="evidence-list">
        {issue.evidence.map((evidence) => (
          <article key={evidence.item_id} className="evidence-row">
            <header>
              <span className={`platform-pill ${evidence.platform}`}>{evidence.platform}</span>
              <strong>{evidence.source_label}</strong>
              <time>{formatDate(evidence.posted_at)}</time>
              {evidence.original_url ? (
                <a href={evidence.original_url} target="_blank" rel="noreferrer" aria-label="Open original source">
                  <ArrowUpRight />
                </a>
              ) : null}
            </header>
            <p dir="auto">{evidence.snippet}</p>
          </article>
        ))}
        {!issue.evidence.length ? <EmptyState icon={<ShieldAlert />} title="Evidence expired" /> : null}
      </section>
    </>
  );
}

function PostsView({
  filters,
  sources,
  posts,
  stats,
  onFilter,
}: {
  filters: PostFilters;
  sources: Source[];
  posts: Post[];
  stats: PostStats | null;
  onFilter: (filters: PostFilters) => void;
}) {
  const timelinePeak = Math.max(...(stats?.timeline ?? []).map((point) => point.count), 1);
  return (
    <section className="posts-view">
      <aside className="post-filters">
        <h2><Filter /> Post filters</h2>
        <label>
          Search
          <input
            value={filters.q}
            onChange={(event) => onFilter({ ...filters, q: event.target.value })}
            placeholder="water, medicine, حاجز"
          />
        </label>
        <label>
          Platform
          <select value={filters.platform} onChange={(event) => onFilter({ ...filters, platform: event.target.value })}>
            <option value="">All</option>
            {platforms.map((platform) => <option key={platform} value={platform}>{labelize(platform)}</option>)}
          </select>
        </label>
        <label>
          Language
          <select value={filters.language} onChange={(event) => onFilter({ ...filters, language: event.target.value })}>
            <option value="">All</option>
            <option value="ar">Arabic</option>
            <option value="en">English</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label>
          Window
          <select value={filters.days} onChange={(event) => onFilter({ ...filters, days: event.target.value })}>
            <option value="1">24 hours</option>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </label>
        <label>
          Source
          <select value={filters.sourceId} onChange={(event) => onFilter({ ...filters, sourceId: event.target.value })}>
            <option value="">All</option>
            {sources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
          </select>
        </label>
        <label>
          Rows
          <select value={filters.limit} onChange={(event) => onFilter({ ...filters, limit: event.target.value })}>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="200">200</option>
            <option value="300">300</option>
          </select>
        </label>
      </aside>

      <section className="post-dashboard">
        <section className="stats-grid" aria-label="Post statistics">
          <StatCard label="Total posts" value={String(stats?.total ?? 0)} />
          <StatCard label="Last 24h" value={String(stats?.last_24h ?? 0)} />
          <StatCard label="Last 7d" value={String(stats?.last_7d ?? 0)} />
          <StatCard label="Visible rows" value={String(posts.length)} />
        </section>

        <section className="post-stat-panels">
          <div>
            <h2>Timeline</h2>
            <section className="post-timeline">
              {(stats?.timeline ?? []).map((point) => (
                <div key={point.bucket_date} className="bar-slot" title={`${point.bucket_date}: ${point.count}`}>
                  <i style={{ height: `${Math.max((point.count / timelinePeak) * 100, 8)}%` }} />
                  <span>{point.bucket_date.slice(5)}</span>
                </div>
              ))}
              {!stats?.timeline.length ? <small>No posts in this window</small> : null}
            </section>
          </div>
          <div>
            <h2>Top sources</h2>
            <section className="rank-list">
              {(stats?.top_sources ?? []).map((source) => (
                <div key={source.source_id}>
                  <span><b>{source.label}</b><small>{source.platform}</small></span>
                  <strong>{source.count}</strong>
                </div>
              ))}
              {!stats?.top_sources.length ? <small>No source counts yet</small> : null}
            </section>
          </div>
          <div>
            <h2>Breakdown</h2>
            <section className="rank-list compact">
              {(stats?.by_platform ?? []).map((entry) => (
                <div key={`platform-${entry.key}`}>
                  <span>{labelize(entry.label)}</span>
                  <strong>{entry.count}</strong>
                </div>
              ))}
              {(stats?.by_language ?? []).map((entry) => (
                <div key={`language-${entry.key}`}>
                  <span>{entry.label}</span>
                  <strong>{entry.count}</strong>
                </div>
              ))}
            </section>
          </div>
        </section>

        <section className="post-list" aria-label="Collected posts">
          {posts.map((post) => (
            <article key={post.id} className="post-row">
              <header>
                <span className={`platform-pill ${post.platform}`}>{post.platform}</span>
                <strong>{post.source_label}</strong>
                <span>{languageLabel(post.language)}</span>
                <time>{formatDate(post.posted_at)}</time>
                {post.original_url ? (
                  <a href={post.original_url} target="_blank" rel="noreferrer" aria-label="Open original source">
                    <ArrowUpRight />
                  </a>
                ) : null}
              </header>
              <p dir="auto">{post.snippet}</p>
            </article>
          ))}
          {!posts.length ? <EmptyState icon={<Newspaper />} title="No posts match these filters" /> : null}
        </section>
      </section>
    </section>
  );
}

function SourcesView({
  sources,
  busy,
  onCreate,
  onUpdate,
  onDelete,
  onError,
}: {
  sources: Source[];
  busy: string;
  onCreate: () => Promise<void>;
  onUpdate: (source: Source, patch: Partial<Source>) => Promise<void>;
  onDelete: (sourceId: number) => Promise<void>;
  onError: (message: string) => void;
}) {
  return (
    <section className="workspace sources-workspace">
      <SourceForm onCreate={onCreate} onError={onError} />
      <section className="source-table">
        <header>
          <span>Source</span>
          <span>Access</span>
          <span>Last run</span>
          <span>Enabled</span>
          <span />
        </header>
        {sources.map((source) => (
          <article key={source.id}>
            <div>
              <span className={`platform-pill ${source.platform}`}>{source.platform}</span>
              <strong>{source.label}</strong>
              <small>{source.health ?? source.url ?? source.external_id ?? "No endpoint"}</small>
            </div>
            <b className={`state ${source.access_state}`}>{labelize(source.access_state)}</b>
            <time>{source.last_run_at ? formatDate(source.last_run_at) : "Never"}</time>
            <label className="toggle">
              <input
                type="checkbox"
                checked={source.enabled}
                disabled={busy === `source-${source.id}`}
                onChange={(event) => void onUpdate(source, { enabled: event.target.checked })}
              />
              <span />
            </label>
            <IconButton
              label={`Delete ${source.label}`}
              onClick={() => void onDelete(source.id)}
              disabled={busy === `source-${source.id}`}
              icon={<Trash2 />}
            />
          </article>
        ))}
      </section>
    </section>
  );
}

function SourceForm({
  onCreate,
  onError,
}: {
  onCreate: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [platform, setPlatform] = useState<Platform>("telegram");
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [externalId, setExternalId] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await api<Source>("/sources", {
        method: "POST",
        body: JSON.stringify({
          platform,
          label,
          url: url || null,
          external_id: externalId || null,
        }),
      });
      setLabel("");
      setUrl("");
      setExternalId("");
      await onCreate();
    } catch (nextError) {
      onError(errorMessage(nextError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="source-form" onSubmit={(event) => void submit(event)}>
      <h2><Plus /> Add source</h2>
      <label>
        Platform
        <select value={platform} onChange={(event) => setPlatform(event.target.value as Platform)}>
          {platforms.map((entry) => <option key={entry} value={entry}>{labelize(entry)}</option>)}
        </select>
      </label>
      <label>
        Label
        <input required value={label} onChange={(event) => setLabel(event.target.value)} />
      </label>
      <label>
        URL
        <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder={sourceUrlPlaceholder(platform)} />
      </label>
      <label>
        External ID
        <input value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder={sourceExternalIdPlaceholder(platform)} />
      </label>
      {platform === "discord" ? (
        <p className="form-note">
          Use a Discord text channel ID or a channel URL with both server ID and channel ID. Server and @home URLs cannot be collected.
        </p>
      ) : null}
      {platform === "facebook" ? (
        <p className="form-note warning">
          Facebook records stay blocked until an approved Meta access path is configured.
        </p>
      ) : null}
      <button className="command" disabled={saving}>
        <Plus /> Add
      </button>
    </form>
  );
}

function DiscoveryView({
  candidates,
  busy,
  onReview,
}: {
  candidates: Candidate[];
  busy: string;
  onReview: (candidateId: number, action: "approve" | "reject") => Promise<void>;
}) {
  return (
    <section className="candidate-list">
      {candidates.map((candidate) => (
        <article key={candidate.id} className="candidate-row">
          <div>
            <span className={`platform-pill ${candidate.platform}`}>{candidate.platform}</span>
            <h2>{candidate.label}</h2>
            <p>{candidate.reason ?? candidate.url ?? candidate.external_id}</p>
          </div>
          <small>{candidate.discovered_by}</small>
          <div className="row-actions">
            <IconButton label="Approve source" disabled={busy === `candidate-${candidate.id}`} onClick={() => void onReview(candidate.id, "approve")} icon={<Check />} />
            <IconButton label="Reject source" disabled={busy === `candidate-${candidate.id}`} onClick={() => void onReview(candidate.id, "reject")} icon={<X />} />
          </div>
        </article>
      ))}
      {!candidates.length ? <EmptyState icon={<FileSearch />} title="Review queue is empty" /> : null}
    </section>
  );
}

function RunsView({ runs, onRetention }: { runs: Run[]; onRetention: () => void }) {
  return (
    <section className="runs-view">
      <header>
        <h2>Run history</h2>
        <RunButton label="Expire evidence" onClick={onRetention} busy={false} icon={<Trash2 />} />
      </header>
      <section className="run-table">
        {runs.map((run) => (
          <article key={run.id}>
            <strong>{labelize(run.kind)}</strong>
            <b className={`state ${run.status}`}>{labelize(run.status)}</b>
            <time>{formatDate(run.requested_at)}</time>
            <span>{run.collected_count} collected</span>
            <span>{run.analyzed_count} analyzed</span>
            <span>{run.discovered_count} discovered</span>
            <p>{run.error ?? `${run.expired_count} expired`}</p>
          </article>
        ))}
      </section>
    </section>
  );
}

function Tab({
  view,
  value,
  label,
  icon,
  onSelect,
}: {
  view: View;
  value: View;
  label: string;
  icon: React.ReactNode;
  onSelect: (view: View) => void;
}) {
  return <button className={view === value ? "active" : ""} onClick={() => onSelect(value)}>{icon}{label}</button>;
}

function IconButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return <button className="icon-button" title={label} aria-label={label} disabled={disabled} onClick={onClick}>{icon}</button>;
}

function RunButton({
  label,
  icon,
  busy,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  busy: boolean;
  onClick: () => void;
}) {
  return <button className="command" disabled={busy} onClick={onClick}>{icon}{label}</button>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function StatCard({ label, value }: { label: string; value: string }) {
  return <article className="stat-card"><span>{label}</span><strong>{value}</strong></article>;
}

function EmptyState({ icon, title }: { icon: React.ReactNode; title: string }) {
  return <div className="empty-state">{icon}<strong>{title}</strong></div>;
}

function SourceAccessNotice({
  sources,
  onSources,
}: {
  sources: Source[];
  onSources: () => void;
}) {
  const enabledSources = sources.filter((source) => source.enabled);
  const blockedSources = enabledSources.filter((source) =>
    ["missing_credentials", "permission_denied", "error"].includes(source.access_state),
  );
  const facebookOnly =
    enabledSources.length > 0 &&
    enabledSources.every((source) => source.platform === "facebook");

  if (!facebookOnly && blockedSources.length === 0) {
    return null;
  }

  const title = facebookOnly
    ? "Facebook sources are blocked"
    : `${blockedSources.length} enabled source${blockedSources.length === 1 ? "" : "s"} need access`;
  const body = facebookOnly
    ? "This authorized-only MVP stores Facebook source records but does not collect them until approved Meta access is configured."
    : "Collection skipped sources with missing credentials, permissions, or connector errors.";

  return (
    <section className="source-access-notice" aria-live="polite">
      <ShieldAlert />
      <div>
        <strong>{title}</strong>
        <p>{body}</p>
      </div>
      <button className="command secondary" onClick={onSources}>
        Open Sources
      </button>
    </section>
  );
}

function labelize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function categoryLabel(value: string) {
  return categoryLabels[value] ?? labelize(value);
}

function languageLabel(value: string) {
  return languageLabels[value] ?? value;
}

function sourceUrlPlaceholder(platform: Platform) {
  if (platform === "discord") {
    return "https://discord.com/channels/server-id/channel-id";
  }
  if (platform === "telegram") {
    return "https://t.me/channel";
  }
  return "RSS or public source URL";
}

function sourceExternalIdPlaceholder(platform: Platform) {
  if (platform === "discord") {
    return "Discord channel ID";
  }
  if (platform === "telegram") {
    return "Telegram username or chat ID";
  }
  return "Optional external ID";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Request failed.";
}
