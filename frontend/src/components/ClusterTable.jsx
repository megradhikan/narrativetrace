const TOPIC_COLORS = {
  politics: { bg: "#dbeafe", text: "#1d4ed8" },
  health: { bg: "#d1fae5", text: "#065f46" },
  finance: { bg: "#fef3c7", text: "#92400e" },
  "natural disaster": { bg: "#fee2e2", text: "#991b1b" },
  entertainment: { bg: "#ede9fe", text: "#5b21b6" },
  other: { bg: "#f3f4f6", text: "#374151" },
};

function TopicBadge({ topic }) {
  if (!topic) return <span style={{ color: "#9ca3af", fontSize: 12 }}>unclassified</span>;
  const c = TOPIC_COLORS[topic] || TOPIC_COLORS.other;
  return (
    <span
      className="topic-badge"
      style={{ background: c.bg, color: c.text }}
    >
      {topic}
    </span>
  );
}

function timeAgo(dateStr) {
  const diff = Math.floor((Date.now() - new Date(dateStr)) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function ClusterTable({ clusters, onSelect, selectedId }) {
  return (
    <table className="cluster-table">
      <thead>
        <tr>
          <th style={{ width: "55%" }}>Sample post</th>
          <th>Topic</th>
          <th>Posts</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {clusters.map((c) => (
          <tr
            key={c.cluster_id}
            className={c.cluster_id === selectedId ? "selected" : ""}
            onClick={() => onSelect(c)}
          >
            <td>
              <div className="sample-text">
                <span className="sample-text-truncated">
                  {c.sample_text || <em style={{ color: "#9ca3af" }}>No text</em>}
                </span>
              </div>
            </td>
            <td><TopicBadge topic={c.topic} /></td>
            <td><span className="post-count">{c.post_count}</span></td>
            <td><span className="updated-at">{c.updated_at ? timeAgo(c.updated_at) : "—"}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
