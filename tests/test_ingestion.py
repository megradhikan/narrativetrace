"""
Ingestion tests using the recorded fixture — no live network dependency.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "firehose_sample.json"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_posts():
    if not FIXTURE_PATH.exists():
        pytest.skip(
            f"Fixture file not found at {FIXTURE_PATH}. "
            "Run `python -m ingestion.capture_fixture` once to generate it."
        )
    data = json.loads(FIXTURE_PATH.read_text())
    return data


# ---------------------------------------------------------------------------
# Schema / content tests
# ---------------------------------------------------------------------------

class TestFixtureSchema:
    def test_fixture_has_enough_posts(self, sample_posts):
        assert len(sample_posts) >= 100, (
            f"Fixture only has {len(sample_posts)} posts; expected >= 100"
        )

    def test_required_fields_present(self, sample_posts):
        required = {"post_id", "author_did", "text", "created_at", "raw_json"}
        for post in sample_posts:
            missing = required - post.keys()
            assert not missing, f"Post missing fields {missing}: {post}"

    def test_post_ids_are_unique(self, sample_posts):
        ids = [p["post_id"] for p in sample_posts]
        assert len(ids) == len(set(ids)), "Duplicate post_ids found in fixture"

    def test_text_is_non_empty_string(self, sample_posts):
        for post in sample_posts:
            assert isinstance(post["text"], str), f"text is not a str: {post}"
            assert post["text"].strip(), f"text is empty/whitespace: {post}"

    def test_author_did_looks_like_did(self, sample_posts):
        for post in sample_posts:
            assert post["author_did"].startswith("did:"), (
                f"author_did doesn't look like a DID: {post['author_did']}"
            )

    def test_created_at_is_parseable_iso(self, sample_posts):
        for post in sample_posts:
            dt = datetime.fromisoformat(post["created_at"])
            assert dt.tzinfo is not None, f"created_at has no timezone: {post}"

    def test_raw_json_contains_type(self, sample_posts):
        for post in sample_posts:
            rj = post["raw_json"]
            assert isinstance(rj, dict), "raw_json is not a dict"
            assert "$type" in rj, f"raw_json missing $type: {rj}"


# ---------------------------------------------------------------------------
# DB insertion tests (mocked connection)
# ---------------------------------------------------------------------------

class TestDbInsert:
    def test_insert_post_executes_upsert(self):
        from ingestion.db import insert_post

        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value

        insert_post(
            conn,
            post_id="did:plc:abc/rkey123",
            author_did="did:plc:abc",
            text="hello world",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            raw_json={"$type": "app.bsky.feed.post", "text": "hello world"},
        )

        assert cur.execute.called
        sql = cur.execute.call_args[0][0]
        assert "INSERT INTO posts" in sql
        assert "ON CONFLICT" in sql
        conn.commit.assert_called_once()

    def test_init_db_creates_table(self):
        from ingestion.db import init_db

        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value

        with patch("ingestion.db.get_connection", return_value=conn):
            init_db()

        sql = cur.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS posts" in sql
        conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Reconnection / config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_reconnect_delays_configured(self):
        from ingestion import config
        assert config.RECONNECT_BASE_DELAY > 0
        assert config.RECONNECT_MAX_DELAY > config.RECONNECT_BASE_DELAY

    def test_database_url_has_default(self):
        from ingestion import config
        assert config.DATABASE_URL.startswith("postgresql://")


# ---------------------------------------------------------------------------
# Post-filtering tests (posts-only, no likes/follows)
# ---------------------------------------------------------------------------

class TestPostFiltering:
    """Verify that only app.bsky.feed.post records appear in the fixture."""

    def test_all_fixture_posts_have_correct_lexicon(self, sample_posts):
        for post in sample_posts:
            rtype = post["raw_json"].get("$type")
            assert rtype == "app.bsky.feed.post", (
                f"Non-post record leaked into fixture: $type={rtype}"
            )
