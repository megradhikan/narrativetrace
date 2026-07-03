const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function fetchClusters(topic = null) {
  const url = new URL(`${BASE}/clusters`);
  if (topic) url.searchParams.set("topic", topic);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET /clusters failed: ${res.status}`);
  return res.json();
}

export async function fetchCluster(id) {
  const res = await fetch(`${BASE}/clusters/${id}`);
  if (!res.ok) throw new Error(`GET /clusters/${id} failed: ${res.status}`);
  return res.json();
}

export async function fetchTopics() {
  const res = await fetch(`${BASE}/topics`);
  if (!res.ok) throw new Error(`GET /topics failed: ${res.status}`);
  return res.json();
}

export async function fetchStats() {
  const res = await fetch(`${BASE}/stats`);
  if (!res.ok) throw new Error(`GET /stats failed: ${res.status}`);
  return res.json();
}

export async function fetchAlerts() {
  const res = await fetch(`${BASE}/alerts`);
  if (!res.ok) throw new Error(`GET /alerts failed: ${res.status}`);
  return res.json();
}
