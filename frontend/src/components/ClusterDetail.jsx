import { useState, useEffect } from "react";
import { fetchCluster } from "../api";

export default function ClusterDetail({ clusterId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
    fetchCluster(clusterId)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [clusterId]);

  return (
    <div className="cluster-detail-overlay" onClick={onClose}>
      <div className="cluster-detail-panel" onClick={(e) => e.stopPropagation()}>
        <div className="detail-header">
          <h2>Cluster detail</h2>
          <button className="close-btn" onClick={onClose} aria-label="Close">×</button>
        </div>

        {error && <div className="error-banner">⚠ {error}</div>}
        {!data && !error && <div className="detail-loading">Loading…</div>}

        {data && (
          <>
            <div className="detail-meta">
              <span>{data.post_count} posts</span>
              {data.topic && <span>Topic: <strong>{data.topic}</strong></span>}
              {data.topic_score && <span>Confidence: {(data.topic_score * 100).toFixed(0)}%</span>}
            </div>
            <ul className="post-list">
              {data.posts.map((p) => (
                <li key={p.post_id} className="post-item">
                  <div className="post-item-text">{p.text}</div>
                  <div className="post-item-meta">
                    {p.author_did} · {new Date(p.created_at).toLocaleString()}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
