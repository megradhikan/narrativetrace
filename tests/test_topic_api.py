"""
Tests for v0.3: topic classification and FastAPI endpoints.
All DB and model calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Classifier unit tests
# ---------------------------------------------------------------------------

class TestClassifier:
    def test_classify_returns_known_label(self):
        """Classifier output must be one of the candidate labels."""
        from clustering.classifier import CANDIDATE_LABELS, classify_cluster

        label, score = classify_cluster([
            "The government announced new spending on healthcare reforms.",
            "Officials unveiled a major health policy overhaul today.",
        ])
        assert label in CANDIDATE_LABELS
        assert 0.0 <= score <= 1.0

    def test_classify_empty_texts_returns_other(self):
        from clustering.classifier import classify_cluster
        label, score = classify_cluster([])
        assert label == "other"
        assert score == 0.0

    def test_classify_politics_texts(self):
        from clustering.classifier import classify_cluster
        label, _ = classify_cluster([
            "Senate votes to pass new immigration bill after lengthy debate.",
            "Congress reaches deal on federal budget ahead of deadline.",
        ])
        assert label == "politics"

    def test_classify_health_texts(self):
        from clustering.classifier import classify_cluster
        label, _ = classify_cluster([
            "CDC issues new guidance on flu vaccine recommendations for winter.",
            "Hospitals report surge in respiratory illness across northern states.",
        ])
        assert label == "health"


# ---------------------------------------------------------------------------
# FastAPI endpoint tests (mocked DB)
# ---------------------------------------------------------------------------

MOCK_CLUSTERS = [
    {
        "cluster_id": "abc-123",
        "post_count": 10,
        "topic": "politics",
        "topic_score": 0.91,
        "updated_at": "2024-01-01T12:00:00+00:00",
        "sample_text": "Government announces new policy.",
    },
    {
        "cluster_id": "def-456",
        "post_count": 5,
        "topic": "health",
        "topic_score": 0.85,
        "updated_at": "2024-01-01T11:00:00+00:00",
        "sample_text": "New health guidelines released.",
    },
]

MOCK_CLUSTER_DETAIL = {
    **MOCK_CLUSTERS[0],
    "posts": [
        {
            "post_id": "did:plc:x/r1",
            "author_did": "did:plc:x",
            "text": "Government announces new policy.",
            "created_at": "2024-01-01T12:00:00+00:00",
        }
    ],
}


@pytest.fixture
def client():
    with (
        patch("backend.main.get_connection"),
        patch("backend.main.init_db"),
        patch("backend.main.init_cluster_tables"),
        patch("backend.main.init_topic_columns"),
        patch("backend.main.start_classify"),
    ):
        from backend.main import app
        with TestClient(app) as c:
            yield c


class TestClustersEndpoint:
    def test_list_clusters_returns_200(self, client):
        with patch("backend.main.get_connection") as mock_conn:
            conn = _mock_conn_returning(MOCK_CLUSTERS)
            mock_conn.return_value = conn
            resp = client.get("/clusters")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_filter_by_topic(self, client):
        with patch("backend.main.get_connection") as mock_conn:
            filtered = [c for c in MOCK_CLUSTERS if c["topic"] == "politics"]
            mock_conn.return_value = _mock_conn_returning(filtered)
            resp = client.get("/clusters?topic=politics")
        assert resp.status_code == 200

    def test_get_cluster_detail_200(self, client):
        with patch("backend.main.get_connection") as mock_conn:
            mock_conn.return_value = _mock_conn_for_detail(
                MOCK_CLUSTERS[0], MOCK_CLUSTER_DETAIL["posts"]
            )
            resp = client.get("/clusters/abc-123")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cluster_id"] == "abc-123"
        assert "posts" in body

    def test_get_cluster_404(self, client):
        with patch("backend.main.get_connection") as mock_conn:
            mock_conn.return_value = _mock_conn_for_detail(None, [])
            resp = client.get("/clusters/nonexistent")
        assert resp.status_code == 404

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_topics_endpoint(self, client):
        topics = [{"topic": "politics", "cluster_count": 3}]
        with patch("backend.main.get_connection") as mock_conn:
            mock_conn.return_value = _mock_conn_returning(topics)
            resp = client.get("/topics")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_conn_returning(rows):
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [dict(r) for r in rows]
    conn.cursor.return_value = cur
    return conn


def _mock_conn_for_detail(cluster_row, posts):
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = dict(cluster_row) if cluster_row else None
    cur.fetchall.return_value = [dict(p) for p in posts]
    conn.cursor.return_value = cur
    return conn
