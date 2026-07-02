# Changelog

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
