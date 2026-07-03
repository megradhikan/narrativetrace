import { useState, useEffect, useRef } from "react";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const WS_BASE = BASE.replace(/^http/, "ws");

export function useClusterStream() {
  const [clusters, setClusters] = useState([]);
  const [wsStatus, setWsStatus] = useState("connecting");
  const wsRef = useRef(null);

  useEffect(() => {
    let reconnectTimer;

    function connect() {
      const ws = new WebSocket(`${WS_BASE}/ws/clusters`);
      wsRef.current = ws;
      setWsStatus("connecting");

      ws.onopen = () => setWsStatus("connected");

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === "clusters_snapshot") {
            setClusters(msg.clusters);
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        setWsStatus("disconnected");
        // Reconnect after 3s
        reconnectTimer = setTimeout(connect, 3000);
      };

      ws.onerror = () => ws.close();
    }

    connect();
    return () => {
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, []);

  return { clusters, wsStatus };
}
