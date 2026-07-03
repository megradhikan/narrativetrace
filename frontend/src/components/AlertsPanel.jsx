import { useState, useEffect } from "react";
import { fetchAlerts } from "../api";

export default function AlertsPanel({ onSelectCluster }) {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await fetchAlerts();
        if (!cancelled) setAlerts(data);
      } catch {
        // non-fatal
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const interval = setInterval(load, 10000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (loading) return null;
  if (alerts.length === 0) return null;

  return (
    <div className="alerts-panel">
      <div className="alerts-header">
        <span className="alerts-title">
          <span className="alert-icon">⚑</span>
          Coordination signals — flagged for review
        </span>
        <span className="alerts-count">{alerts.length}</span>
      </div>
      <ul className="alerts-list">
        {alerts.map((a) => (
          <li
            key={a.alert_id}
            className="alert-item"
            onClick={() => onSelectCluster({ cluster_id: a.cluster_id })}
          >
            <div className="alert-explanation">{a.explanation}</div>
            <div className="alert-meta">
              {a.topic && <span className="alert-topic">{a.topic}</span>}
              {a.sample_text && (
                <span className="alert-sample">
                  "{a.sample_text.slice(0, 80)}{a.sample_text.length > 80 ? "…" : ""}"
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
