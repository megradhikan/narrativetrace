# Changelog

## v0.5.0 — Coordination detection

- Coordination heuristic: timing (≥3 distinct accounts post near-identical text within configurable window, default 2 min) + topology (no prior interaction overlap in cluster graph) → coordination signal
- Every flag carries a mandatory plain-language explanation string (e.g. "3 accounts posted near-identical claims within 30 seconds, with no prior interaction overlap in the network. Coordination signal — flagged for review.")
- Words "bot" and "disinformation" are prohibited everywhere in this module (enforced by tests)
- `coordination_alerts` table persists all signals with explanation, accounts list, timing window, overlap flag
- Background detection job runs every 60s across all active clusters
- `GET /alerts` endpoint returns unresolved signals with explanation string (never a bare flag)
- `GET /stats` now includes `active_alerts` count
- AlertsPanel component: red-bordered section above cluster table, shows explanation + sample text, clicking navigates to cluster detail
- Flagged alert count shown in stats bar (only when > 0)
- 73/73 tests pass (20 new coordination tests: 3 timing-trigger, 3 organic-no-trigger, 3 overlap, 8 explanation-string, 2 config, 1 API)

## v0.4.0 — Live graph construction + real-time dashboard

- **Branch A — graph construction:** Extract repost/quote/reply edges from firehose records; persist to `graph_edges` table; reconstruct per-cluster `networkx.DiGraph` from Postgres at any time; `GET /clusters/{id}/graph` REST endpoint
- **Branch B — live dashboard:** WebSocket `GET /ws/clusters` pushes cluster snapshots every 3s; `GET /ws/clusters/{id}/graph` streams graph snapshots + incremental edge events; `GET /stats` endpoint (total posts, active clusters, posts/min); Stats bar with live connection indicator; `react-force-graph-2d` force-directed graph in cluster detail panel (updates live without page refresh); WebSocket reconnects automatically on drop
- 48/48 tests pass (20 new: 15 graph + 5 WebSocket/stats)

## v0.3.0 — Topic classification + static dashboard

- Zero-shot topic classification via `facebook/bart-large-mnli` assigns each cluster one of: politics, health, finance, natural disaster, entertainment, other
- Background classification job tags unclassified clusters every 30s (daemon thread, non-blocking)
- FastAPI backend with `GET /clusters` (filterable by topic), `GET /clusters/{id}`, `GET /topics`, `GET /health`
- React dashboard (Vite): topic sidebar filter, sortable cluster table with topic badges, polling every 5s, cluster detail slide-out panel
- 33/33 tests pass (10 new: 4 classifier unit tests + 6 API endpoint tests)

## v0.2.0 — Claim extraction + clustering

- Embed each post with `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim, unit-normalised)
- Store embeddings in Postgres via `pgvector` (`vector(384)` column on `posts`)
- Incremental clustering: cosine-similarity comparison against active cluster centroids; assign or create; running-mean centroid update
- Clustering threshold configurable via `CLUSTER_SIMILARITY_THRESHOLD` env var (default 0.75 — chosen to balance paraphrase recall vs. false merges)
- Periodic re-clustering job every 10 min (background daemon thread): recomputes true centroids, merges similar clusters, splits low-cohesion clusters; logs all events
- CLI report `python -m clustering.report` prints active clusters sorted by post count
- Combined entrypoint `python -m clustering.run` streams firehose → embeds → clusters + re-clustering job

## v0.1.0 — Firehose ingestion

- Connect to AT Protocol firehose via `atproto` SDK, filtering to `app.bsky.feed.post` create events only
- Persist raw posts to Postgres (`posts` table: `post_id`, `author_did`, `text`, `created_at`, `raw_json`)
- Exponential-backoff reconnection on dropped WebSocket connections (base 1s, max 60s)
- Fixture-capture script (`python -m ingestion.capture_fixture`) records ~500 real events for offline testing
- `pytest` test suite runs against the recorded fixture — no live network required in CI
- CLI entrypoint `python -m ingestion.run` logs post count and rate per minute
