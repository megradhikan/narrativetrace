import { useEffect, useRef, useState, useCallback } from "react";
import ForceGraph2D from "react-force-graph-2d";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_BASE = BASE.replace(/^http/, "ws");

export default function GraphView({ clusterId }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [wsStatus, setWsStatus] = useState("connecting");
  const wsRef = useRef(null);
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 400 });

  // Track container size
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ width, height: Math.max(height, 300) });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // WebSocket connection
  useEffect(() => {
    if (!clusterId) return;
    const ws = new WebSocket(`${WS_BASE}/ws/clusters/${clusterId}/graph`);
    wsRef.current = ws;
    setWsStatus("connecting");

    ws.onopen = () => setWsStatus("connected");
    ws.onclose = () => setWsStatus("disconnected");
    ws.onerror = () => setWsStatus("disconnected");

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.type === "graph_snapshot") {
        setGraphData({ nodes: msg.nodes || [], links: msg.links || [] });
      } else if (msg.type === "graph_edge") {
        const edge = msg.edge;
        setGraphData((prev) => {
          const nodeIds = new Set(prev.nodes.map((n) => n.id));
          const newNodes = [...prev.nodes];
          if (!nodeIds.has(edge.source_did)) newNodes.push({ id: edge.source_did });
          if (!nodeIds.has(edge.target_did)) newNodes.push({ id: edge.target_did });
          return {
            nodes: newNodes,
            links: [...prev.links, {
              source: edge.source_did,
              target: edge.target_did,
              type: edge.edge_type,
            }],
          };
        });
      }
    };

    return () => ws.close();
  }, [clusterId]);

  const EDGE_COLORS = { reply: "#6366f1", quote: "#f59e0b", repost: "#10b981" };

  return (
    <div className="graph-view" ref={containerRef}>
      <div className="graph-header">
        <span className="graph-title">Interaction graph</span>
        <span className={`firehose-status ${wsStatus}`}>
          <span className="status-dot" />
          {wsStatus === "connected" ? "Live" : wsStatus === "connecting" ? "Connecting…" : "Disconnected"}
        </span>
        <span className="graph-counts">
          {graphData.nodes.length} authors · {graphData.links.length} interactions
        </span>
      </div>
      {graphData.nodes.length === 0 ? (
        <div className="graph-empty">No interactions yet for this cluster.</div>
      ) : (
        <ForceGraph2D
          width={dimensions.width}
          height={dimensions.height}
          graphData={graphData}
          nodeLabel="id"
          nodeRelSize={5}
          nodeColor={() => "#7c3aed"}
          linkColor={(link) => EDGE_COLORS[link.type] || "#9ca3af"}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkLabel="type"
          backgroundColor="transparent"
        />
      )}
      <div className="graph-legend">
        {Object.entries(EDGE_COLORS).map(([type, color]) => (
          <span key={type} className="legend-item">
            <span className="legend-dot" style={{ background: color }} />
            {type}
          </span>
        ))}
      </div>
    </div>
  );
}
