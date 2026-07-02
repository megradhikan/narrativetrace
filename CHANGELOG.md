# Changelog

## v0.1.0 — Firehose ingestion

- Connect to AT Protocol firehose via `atproto` SDK, filtering to `app.bsky.feed.post` create events only
- Persist raw posts to Postgres (`posts` table: `post_id`, `author_did`, `text`, `created_at`, `raw_json`)
- Exponential-backoff reconnection on dropped WebSocket connections (base 1s, max 60s)
- Fixture-capture script (`python -m ingestion.capture_fixture`) records ~500 real events for offline testing
- `pytest` test suite runs against the recorded fixture — no live network required in CI
- CLI entrypoint `python -m ingestion.run` logs post count and rate per minute
