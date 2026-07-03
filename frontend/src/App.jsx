import { useState, useEffect, useCallback } from "react";
import { fetchTopics, fetchStats } from "./api";
import { useClusterStream } from "./hooks/useClusterStream";
import ClusterTable from "./components/ClusterTable";
import TopicFilter from "./components/TopicFilter";
import ClusterDetail from "./components/ClusterDetail";
import StatsBar from "./components/StatsBar";
import "./App.css";

const TOPIC_POLL_MS = 10000;
const STATS_POLL_MS = 5000;

export default function App() {
  const { clusters: allClusters, wsStatus } = useClusterStream();
  const [topics, setTopics] = useState([]);
  const [stats, setStats] = useState(null);
  const [selectedTopic, setSelectedTopic] = useState(null);
  const [selectedCluster, setSelectedCluster] = useState(null);

  const visibleClusters = selectedTopic
    ? allClusters.filter((c) => c.topic === selectedTopic)
    : allClusters;

  const loadTopics = useCallback(async () => {
    try { setTopics(await fetchTopics()); } catch { /* non-fatal */ }
  }, []);

  const loadStats = useCallback(async () => {
    try { setStats(await fetchStats()); } catch { /* non-fatal */ }
  }, []);

  useEffect(() => {
    loadTopics();
    loadStats();
    const t1 = setInterval(loadTopics, TOPIC_POLL_MS);
    const t2 = setInterval(loadStats, STATS_POLL_MS);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [loadTopics, loadStats]);

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>NarrativeTrace</h1>
          <span className="subtitle">Live claim cluster monitor · Bluesky / AT Protocol</span>
        </div>
      </header>

      <StatsBar stats={stats} wsStatus={wsStatus} />

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
          {visibleClusters.length === 0 ? (
            <div className="empty">
              {wsStatus === "connected"
                ? `No active clusters${selectedTopic ? ` for topic "${selectedTopic}"` : ""}.`
                : "Connecting to live stream…"}
            </div>
          ) : (
            <ClusterTable
              clusters={visibleClusters}
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
