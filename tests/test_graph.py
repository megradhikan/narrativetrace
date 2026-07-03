"""
Graph construction tests — no live DB or firehose.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import networkx as nx
import pytest

from graph.builder import (
    _did_from_at_uri,
    extract_interactions,
    graph_to_dict,
    load_cluster_graph,
    record_interactions,
)


# ---------------------------------------------------------------------------
# AT URI parsing
# ---------------------------------------------------------------------------

class TestDidFromAtUri:
    def test_extracts_did_plc(self):
        uri = "at://did:plc:abc123/app.bsky.feed.post/rkey"
        assert _did_from_at_uri(uri) == "did:plc:abc123"

    def test_extracts_did_web(self):
        uri = "at://did:web:example.com/app.bsky.feed.post/rkey"
        assert _did_from_at_uri(uri) == "did:web:example.com"

    def test_returns_none_for_handle(self):
        uri = "at://alice.bsky.social/app.bsky.feed.post/rkey"
        assert _did_from_at_uri(uri) is None

    def test_returns_none_for_garbage(self):
        assert _did_from_at_uri("not-a-uri") is None


# ---------------------------------------------------------------------------
# Interaction extraction
# ---------------------------------------------------------------------------

def _make_post(author_did, post_id, raw_json=None):
    return {
        "post_id": post_id,
        "author_did": author_did,
        "text": "hello",
        "raw_json": raw_json or {"$type": "app.bsky.feed.post"},
    }


class TestExtractInteractions:
    def test_no_interactions_for_plain_post(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r1")
        assert extract_interactions(post) == []

    def test_extracts_reply_edge(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r1", raw_json={
            "$type": "app.bsky.feed.post",
            "text": "replying",
            "reply": {
                "parent": {"uri": "at://did:plc:bob/app.bsky.feed.post/r0"},
                "root": {"uri": "at://did:plc:bob/app.bsky.feed.post/r0"},
            },
        })
        ias = extract_interactions(post)
        assert len(ias) == 1
        assert ias[0]["type"] == "reply"
        assert ias[0]["source_did"] == "did:plc:alice"
        assert ias[0]["target_did"] == "did:plc:bob"

    def test_extracts_quote_edge(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r2", raw_json={
            "$type": "app.bsky.feed.post",
            "text": "quoting",
            "embed": {
                "$type": "app.bsky.embed.record",
                "record": {"uri": "at://did:plc:carol/app.bsky.feed.post/r0"},
            },
        })
        ias = extract_interactions(post)
        assert len(ias) == 1
        assert ias[0]["type"] == "quote"
        assert ias[0]["target_did"] == "did:plc:carol"

    def test_skips_self_interactions(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r3", raw_json={
            "$type": "app.bsky.feed.post",
            "reply": {
                "parent": {"uri": "at://did:plc:alice/app.bsky.feed.post/r0"},
            },
        })
        # self-reply should be skipped
        assert extract_interactions(post) == []

    def test_skips_missing_parent_uri(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r4", raw_json={
            "$type": "app.bsky.feed.post",
            "reply": {"parent": {}},
        })
        assert extract_interactions(post) == []


# ---------------------------------------------------------------------------
# Graph construction from edges
# ---------------------------------------------------------------------------

class TestLoadClusterGraph:
    def test_builds_graph_from_edges(self):
        edges = [
            {"source_did": "did:plc:a", "target_did": "did:plc:b",
             "edge_type": "reply", "source_post": "a/r1", "target_post": "b/r0",
             "created_at": "2024-01-01T00:00:00+00:00"},
            {"source_did": "did:plc:c", "target_did": "did:plc:a",
             "edge_type": "quote", "source_post": "c/r1", "target_post": "a/r0",
             "created_at": "2024-01-01T00:01:00+00:00"},
        ]
        conn = MagicMock()
        with patch("graph.builder.get_edges_for_cluster", return_value=edges):
            G = load_cluster_graph(conn, "cluster-1")

        assert isinstance(G, nx.DiGraph)
        assert G.number_of_nodes() == 3
        assert G.number_of_edges() == 2
        assert G.has_edge("did:plc:a", "did:plc:b")
        assert G["did:plc:a"]["did:plc:b"]["type"] == "reply"

    def test_empty_graph_for_no_edges(self):
        conn = MagicMock()
        with patch("graph.builder.get_edges_for_cluster", return_value=[]):
            G = load_cluster_graph(conn, "cluster-empty")
        assert G.number_of_nodes() == 0
        assert G.number_of_edges() == 0


class TestGraphToDict:
    def test_serialises_nodes_and_links(self):
        G = nx.DiGraph()
        G.add_edge("did:plc:a", "did:plc:b", type="reply", created_at="2024-01-01")
        d = graph_to_dict(G)
        assert len(d["nodes"]) == 2
        assert len(d["links"]) == 1
        assert d["links"][0]["source"] == "did:plc:a"
        assert d["links"][0]["type"] == "reply"

    def test_empty_graph_serialises_cleanly(self):
        d = graph_to_dict(nx.DiGraph())
        assert d == {"nodes": [], "links": []}


# ---------------------------------------------------------------------------
# record_interactions wires through to insert_edge
# ---------------------------------------------------------------------------

class TestRecordInteractions:
    def test_inserts_reply_edge(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r1", raw_json={
            "$type": "app.bsky.feed.post",
            "reply": {"parent": {"uri": "at://did:plc:bob/app.bsky.feed.post/r0"}},
        })
        conn = MagicMock()
        with patch("graph.builder.insert_edge") as mock_insert:
            count = record_interactions(conn, post, "cluster-x")
        assert count == 1
        mock_insert.assert_called_once()
        kwargs = mock_insert.call_args[1] if mock_insert.call_args[1] else {}
        args = mock_insert.call_args[0]
        assert "reply" in str(args) or "reply" in str(kwargs)

    def test_no_edges_for_plain_post(self):
        post = _make_post("did:plc:alice", "did:plc:alice/r2")
        conn = MagicMock()
        with patch("graph.builder.insert_edge") as mock_insert:
            count = record_interactions(conn, post, "cluster-x")
        assert count == 0
        mock_insert.assert_not_called()
