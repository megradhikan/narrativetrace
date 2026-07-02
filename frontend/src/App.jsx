import { useState, useEffect, useCallback } from "react";
import { fetchClusters, fetchTopics } from "./api";
import ClusterTable from "./components/ClusterTable";
import TopicFilter from "./components/TopicFilter";
import ClusterDetail from "./components/ClusterDetail";
import "./App.css";

const POLL_INTERVAL_MS = 5000;

export default function App() {
  const [clusters, setClusters] = useState([]);
  const [topics, setTopics] = useState([]);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const loadClusters = useCallback(async () => {
    try {
      const data = await fetchClusters(selectedTopic);
      setClusters(data);
      setLastRefresh(new Date());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedTopic]);

  const loadTopics = useCallback(async () => {
    try {
      const data = await fetchTopics();
      setTopics(data);
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    loadClusters();
    loadTopics();
    const interval = setInterval(() => {
      loadClusters();
      loadTopics();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadClusters, loadTopics]);

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>NarrativeTrace</h1>
          <span className="subtitle">Live claim cluster monitor · Bluesky / AT Protocol</span>
        </div>
        <div className="header-right">
          {lastRefresh && (
            <span className="last-refresh">Updated {lastRefresh.toLocaleTimeString()}</span>
          )}
          <span className="cluster-count">{clusters.length} active clusters</span>
        </div>
      </header>

      <div className="disclaimer">
        ⚠ NarrativeTrace surfaces coordination signals for human review only — it does not determine truth or label content as disinformation.
      </div>

      <div className="app-body">
        <aside className="sidebar">
          <TopicFilter
            topics={topics}
            selected={selectedTopic}
            onChange={(t) => { setSelectedTopic(t); setSelectedCluster(null); }}
          />
        </aside>

        <main className="main-content">
          {error && <div className="error-banner">⚠ {error}</div>}
          {loading && clusters.length === 0 ? (
            <div className="loading">Loading clusters…</div>
          ) : clusters.length === 0 ? (
            <div className="empty">No active clusters{selectedTopic ? ` for topic "${selectedTopic}"` : ""}.</div>
          ) : (
            <ClusterTable
              clusters={clusters}
              onSelect={setSelectedCluster}
              selectedId={selectedCluster?.cluster_id}
            />
          )}
        </main>
      </div>

      {selectedCluster && (
        <ClusterDetail
          clusterId={selectedCluster.cluster_id}
          onClose={() => setSelectedCluster(null)}
        />
      )}
    </div>
  );
}
