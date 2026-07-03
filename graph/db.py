"""
DB helpers for graph edges.

Each edge represents a social interaction (repost, quote, reply) between two
author DIDs within a cluster. Edges are persisted so the graph survives restarts.
"""

from __future__ import annotations

import psycopg2.extras
from ingestion.db import get_connection


def init_graph_tables(conn=None) -> None:
    owned = conn is None
    if owned:
        conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS graph_edges (
                    edge_id       BIGSERIAL PRIMARY KEY,
                    cluster_id    TEXT NOT NULL REFERENCES clusters(cluster_id),
                    source_did    TEXT NOT NULL,
                    target_did    TEXT NOT NULL,
                    edge_type     TEXT NOT NULL CHECK (edge_type IN ('repost','quote','reply')),
                    source_post   TEXT,
                    target_post   TEXT,
                    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_graph_edges_cluster
                ON graph_edges (cluster_id)
            """)
        conn.commit()
    finally:
        if owned:
            conn.close()


def insert_edge(conn, cluster_id: str, source_did: str, target_did: str,
                edge_type: str, source_post: str | None = None,
                target_post: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO graph_edges
                (cluster_id, source_did, target_did, edge_type, source_post, target_post)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cluster_id, source_did, target_did, edge_type, source_post, target_post))
    conn.commit()


def get_edges_for_cluster(conn, cluster_id: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT source_did, target_did, edge_type, source_post, target_post, created_at::text
            FROM graph_edges
            WHERE cluster_id = %s
            ORDER BY created_at ASC
        """, (cluster_id,))
        return [dict(r) for r in cur.fetchall()]


def get_all_cluster_edges(conn) -> dict[str, list[dict]]:
    """Return all edges grouped by cluster_id."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT cluster_id, source_did, target_did, edge_type,
                   source_post, target_post, created_at::text
            FROM graph_edges
            ORDER BY cluster_id, created_at ASC
        """)
        rows = cur.fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        cid = row["cluster_id"]
        result.setdefault(cid, []).append(dict(row))
    return result
