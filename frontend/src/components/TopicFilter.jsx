const TOPIC_COLORS = {
  politics: "#3b82f6",
  health: "#10b981",
  finance: "#f59e0b",
  "natural disaster": "#ef4444",
  entertainment: "#8b5cf6",
  other: "#6b7280",
};

export default function TopicFilter({ topics, selected, onChange }) {
  return (
    <div className="topic-filter">
      <h3>Topics</h3>
      <button
        className={`topic-btn${selected === null ? " active" : ""}`}
        onClick={() => onChange(null)}
      >
        All topics
        <span className="topic-count">{topics.reduce((s, t) => s + t.cluster_count, 0)}</span>
      </button>
      {topics.map((t) => (
        <button
          key={t.topic}
          className={`topic-btn${selected === t.topic ? " active" : ""}`}
          onClick={() => onChange(selected === t.topic ? null : t.topic)}
          style={selected === t.topic ? { color: TOPIC_COLORS[t.topic] || "#6b7280" } : {}}
        >
          {t.topic}
          <span className="topic-count">{t.cluster_count}</span>
        </button>
      ))}
    </div>
  );
}
