"""
WebSocket and stats endpoint tests — mocked DB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with (
        patch("backend.main.get_connection"),
        patch("backend.main.init_db"),
        patch("backend.main.init_cluster_tables"),
        patch("backend.main.init_topic_columns"),
        patch("backend.main.init_graph_tables"),
        patch("backend.main.start_classify"),
    ):
        from backend.main import app
        with TestClient(app) as c:
            yield c


class TestStatsEndpoint:
    def test_stats_returns_expected_fields(self, client):
        mock_rows = [{"total": 1234}, {"cnt": 42}, {"cnt": 7}, {"cnt": 2}]
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.side_effect = mock_rows
        conn.cursor.return_value = cur

        with patch("backend.main.get_connection", return_value=conn):
            resp = client.get("/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_posts" in data
        assert "active_clusters" in data
        assert "posts_last_minute" in data
        assert "firehose_status" in data

    def test_stats_firehose_status_is_connected(self, client):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.side_effect = [{"total": 0}, {"cnt": 0}, {"cnt": 0}, {"cnt": 0}]
        conn.cursor.return_value = cur

        with patch("backend.main.get_connection", return_value=conn):
            resp = client.get("/stats")

        assert resp.json()["firehose_status"] == "connected"


class TestWebSocketClusters:
    def test_ws_clusters_sends_snapshot(self, client):
        mock_clusters = [
            {
                "cluster_id": "abc",
                "post_count": 5,
                "topic": "politics",
                "topic_score": 0.9,
                "updated_at": "2024-01-01T00:00:00+00:00",
                "sample_text": "hello",
            }
        ]
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall.return_value = mock_clusters
        conn.cursor.return_value = cur

        with patch("backend.main.get_connection", return_value=conn):
            with client.websocket_connect("/ws/clusters") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "clusters_snapshot"
                assert isinstance(msg["clusters"], list)

    def test_ws_graph_sends_snapshot(self, client):
        import networkx as nx
        empty_g = nx.DiGraph()

        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = {"cluster_id": "abc"}
        conn.cursor.return_value = cur

        with (
            patch("backend.main.get_connection", return_value=conn),
            patch("backend.main.load_cluster_graph", return_value=empty_g),
        ):
            with client.websocket_connect("/ws/clusters/abc/graph") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "graph_snapshot"
                assert "nodes" in msg
                assert "links" in msg

    def test_ws_graph_error_on_unknown_cluster(self, client):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchone.return_value = None
        conn.cursor.return_value = cur

        with patch("backend.main.get_connection", return_value=conn):
            with client.websocket_connect("/ws/clusters/nonexistent/graph") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "error"
                assert "not found" in msg["detail"].lower()
