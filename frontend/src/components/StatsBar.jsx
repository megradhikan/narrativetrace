export default function StatsBar({ stats, wsStatus }) {
  return (
    <div className="stats-bar">
      <span className="stat">
        <span className="stat-value">{stats?.total_posts?.toLocaleString() ?? "—"}</span>
        <span className="stat-label">posts ingested</span>
      </span>
      <span className="stat-divider" />
      <span className="stat">
        <span className="stat-value">{stats?.active_clusters ?? "—"}</span>
        <span className="stat-label">active clusters</span>
      </span>
      <span className="stat-divider" />
      <span className="stat">
        <span className="stat-value">{stats?.posts_last_minute ?? "—"}</span>
        <span className="stat-label">posts/min</span>
      </span>
      {stats?.active_alerts > 0 && (
        <>
          <span className="stat-divider" />
          <span className="stat stat-alert">
            <span className="stat-value alert-value">{stats.active_alerts}</span>
            <span className="stat-label">flagged for review</span>
          </span>
        </>
      )}
      <span className="stat-divider" />
      <span className={`firehose-status ${wsStatus}`}>
        <span className="status-dot" />
        {wsStatus === "connected" ? "Live" : wsStatus === "connecting" ? "Connecting…" : "Disconnected"}
      </span>
    </div>
  );
}
