"""
Graph construction from AT Protocol firehose events.

Extracts repost, quote-post, and reply relationships from raw post records.
Builds a per-cluster directed graph using networkx: nodes = author DIDs,
edges = repost/quote/reply actions with timestamps.

The graph can be reconstructed from Postgres at any time via load_cluster_graph().
"""

from __future__ import annotations

import logging
from datetime import datetime

import networkx as nx

from graph.db import get_edges_for_cluster, insert_edge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Edge extraction from raw firehose records
# ---------------------------------------------------------------------------

def extract_interactions(post: dict) -> list[dict]:
    """
    Given a parsed post dict (from firehose.py), return a list of interaction
    dicts describing repost/quote/reply relationships it implies.

    Each interaction: {type, source_did, target_did, source_post, target_post}
    """
    raw = post.get("raw_json", {})
    source_did = post["author_did"]
    source_post = post["post_id"]
    interactions = []

    # Reply: raw_json.reply.parent.uri  →  reply edge to parent author
    reply = raw.get("reply")
    if isinstance(reply, dict):
        parent = reply.get("parent", {})
        parent_uri = parent.get("uri") if isinstance(parent, dict) else None
        if parent_uri:
            target_did = _did_from_at_uri(parent_uri)
            if target_did and target_did != source_did:
                interactions.append({
                    "type": "reply",
                    "source_did": source_did,
                    "target_did": target_did,
                    "source_post": source_post,
                    "target_post": parent_uri,
                })

    # Quote / embed: raw_json.embed.$type == app.bsky.embed.record
    embed = raw.get("embed")
    if isinstance(embed, dict):
        embed_type = embed.get("$type", "")
        if "embed.record" in embed_type:
            record = embed.get("record", {})
            quoted_uri = record.get("uri") if isinstance(record, dict) else None
            if quoted_uri:
                target_did = _did_from_at_uri(quoted_uri)
                if target_did and target_did != source_did:
                    interactions.append({
                        "type": "quote",
                        "source_did": source_did,
                        "target_did": target_did,
                        "source_post": source_post,
                        "target_post": quoted_uri,
                    })

    return interactions


def _did_from_at_uri(at_uri: str) -> str | None:
    """Extract DID from an AT URI like at://did:plc:xxx/app.bsky.feed.post/rkey."""
    try:
        parts = at_uri.replace("at://", "").split("/")
        did = parts[0]
        return did if did.startswith("did:") else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Persist interactions and assign to cluster
# ---------------------------------------------------------------------------

def record_interactions(conn, post: dict, cluster_id: str) -> int:
    """
    Extract interactions from a post and write edges to graph_edges.
    Returns the number of edges inserted.
    """
    interactions = extract_interactions(post)
    for ia in interactions:
        insert_edge(
            conn,
            cluster_id=cluster_id,
            source_did=ia["source_did"],
            target_did=ia["target_did"],
            edge_type=ia["type"],
            source_post=ia["source_post"],
            target_post=ia["target_post"],
        )
        logger.debug(
            "Edge: %s -[%s]-> %s (cluster %s)",
            ia["source_did"][:20], ia["type"], ia["target_did"][:20], cluster_id[:8],
        )
    return len(interactions)


# ---------------------------------------------------------------------------
# Build networkx graph from persisted edges
# ---------------------------------------------------------------------------

def load_cluster_graph(conn, cluster_id: str) -> nx.DiGraph:
    """
    Reconstruct the interaction graph for a cluster from Postgres.
    Nodes = author DIDs, edges = {type, source_post, target_post, created_at}.
    """
    edges = get_edges_for_cluster(conn, cluster_id)
    G = nx.DiGraph()
    for e in edges:
        G.add_edge(
            e["source_did"],
            e["target_did"],
            type=e["edge_type"],
            source_post=e["source_post"],
            target_post=e["target_post"],
            created_at=e["created_at"],
        )
    return G


def graph_to_dict(G: nx.DiGraph) -> dict:
    """Serialise a networkx graph to a JSON-friendly dict for the frontend."""
    return {
        "nodes": [{"id": n} for n in G.nodes()],
        "links": [
            {
                "source": u,
                "target": v,
                "type": d.get("type"),
                "created_at": d.get("created_at"),
            }
            for u, v, d in G.edges(data=True)
        ],
    }
