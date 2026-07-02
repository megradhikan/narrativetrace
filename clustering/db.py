"""
DB helpers for v0.2: embeddings, clusters, cluster membership.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import numpy as np
import psycopg2
import psycopg2.extras

from ingestion.db import get_connection

logger = logging.getLogger(__name__)


def init_cluster_tables(conn=None) -> None:
    owned = conn is None
    if owned:
        conn = get_connection()
    try:
        with conn.cursor() as cur:
            # pgvector extension (requires pgvector installed in Postgres)
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Store embedding alongside each post
            cur.execute("""
                ALTER TABLE posts
                ADD COLUMN IF NOT EXISTS embedding vector(384);
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS clusters (
                    cluster_id   TEXT PRIMARY KEY,
                    centroid     vector(384) NOT NULL,
                    post_count   INTEGER NOT NULL DEFAULT 0,
                    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS cluster_posts (
                    cluster_id  TEXT NOT NULL REFERENCES clusters(cluster_id),
                    post_id     TEXT NOT NULL REFERENCES posts(post_id),
                    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (cluster_id, post_id)
                )
            """)

            # Index for ANN search on cluster centroids
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_clusters_centroid
                ON clusters USING ivfflat (centroid vector_cosine_ops)
                WITH (lists = 10);
            """)

        conn.commit()
    finally:
        if owned:
            conn.close()


def save_embedding(conn, post_id: str, embedding: np.ndarray) -> None:
    vec_str = _vec_to_pg(embedding)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE posts SET embedding = %s WHERE post_id = %s",
            (vec_str, post_id),
        )
    conn.commit()


def get_active_clusters(conn, active_hours: int) -> list[dict]:
    """Return all clusters updated within the last active_hours hours."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT cluster_id, centroid::text, post_count, updated_at
            FROM clusters
            WHERE updated_at > NOW() - INTERVAL '%s hours'
            ORDER BY post_count DESC
        """, (active_hours,))
        rows = cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["centroid"] = _pg_to_vec(d["centroid"])
        result.append(d)
    return result


def create_cluster(conn, post_id: str, centroid: np.ndarray) -> str:
    cluster_id = str(uuid.uuid4())
    vec_str = _vec_to_pg(centroid)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO clusters (cluster_id, centroid, post_count)
            VALUES (%s, %s, 1)
            """,
            (cluster_id, vec_str),
        )
        cur.execute(
            "INSERT INTO cluster_posts (cluster_id, post_id) VALUES (%s, %s)",
            (cluster_id, post_id),
        )
    conn.commit()
    return cluster_id


def assign_post_to_cluster(conn, cluster_id: str, post_id: str, new_centroid: np.ndarray) -> None:
    vec_str = _vec_to_pg(new_centroid)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cluster_posts (cluster_id, post_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (cluster_id, post_id),
        )
        cur.execute(
            """
            UPDATE clusters
            SET centroid = %s, post_count = post_count + 1, updated_at = NOW()
            WHERE cluster_id = %s
            """,
            (vec_str, cluster_id),
        )
    conn.commit()


def get_all_clusters_with_posts(conn) -> list[dict]:
    """Fetch all clusters with their post texts for re-clustering."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.cluster_id, c.centroid::text, c.post_count,
                   array_agg(cp.post_id) AS post_ids
            FROM clusters c
            JOIN cluster_posts cp USING (cluster_id)
            GROUP BY c.cluster_id, c.centroid, c.post_count
        """)
        rows = cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["centroid"] = _pg_to_vec(d["centroid"])
        result.append(d)
    return result


def get_post_embeddings(conn, post_ids: list[str]) -> dict[str, np.ndarray]:
    """Return {post_id: embedding} for the given post_ids (those with embeddings)."""
    if not post_ids:
        return {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT post_id, embedding::text FROM posts WHERE post_id = ANY(%s) AND embedding IS NOT NULL",
            (post_ids,),
        )
        rows = cur.fetchall()
    return {row["post_id"]: _pg_to_vec(row["embedding"]) for row in rows}


def update_cluster_centroid(conn, cluster_id: str, centroid: np.ndarray, post_count: int) -> None:
    vec_str = _vec_to_pg(centroid)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE clusters
            SET centroid = %s, post_count = %s, updated_at = NOW()
            WHERE cluster_id = %s
            """,
            (vec_str, post_count, cluster_id),
        )
    conn.commit()


def merge_clusters(conn, keep_id: str, drop_id: str, new_centroid: np.ndarray, post_count: int) -> None:
    vec_str = _vec_to_pg(new_centroid)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE cluster_posts SET cluster_id = %s WHERE cluster_id = %s",
            (keep_id, drop_id),
        )
        cur.execute("DELETE FROM clusters WHERE cluster_id = %s", (drop_id,))
        cur.execute(
            """
            UPDATE clusters
            SET centroid = %s, post_count = %s, updated_at = NOW()
            WHERE cluster_id = %s
            """,
            (vec_str, post_count, keep_id),
        )
    conn.commit()


def split_cluster(conn, cluster_id: str, group_a: list[str], group_b: list[str],
                  centroid_a: np.ndarray, centroid_b: np.ndarray) -> str:
    """Split cluster_id: keep group_a in it, create new cluster for group_b."""
    new_id = str(uuid.uuid4())
    vec_a = _vec_to_pg(centroid_a)
    vec_b = _vec_to_pg(centroid_b)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE clusters SET centroid = %s, post_count = %s, updated_at = NOW()
            WHERE cluster_id = %s
            """,
            (vec_a, len(group_a), cluster_id),
        )
        cur.execute(
            "INSERT INTO clusters (cluster_id, centroid, post_count) VALUES (%s, %s, %s)",
            (new_id, vec_b, len(group_b)),
        )
        cur.execute(
            "UPDATE cluster_posts SET cluster_id = %s WHERE cluster_id = %s AND post_id = ANY(%s)",
            (new_id, cluster_id, group_b),
        )
    conn.commit()
    return new_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vec_to_pg(vec: np.ndarray) -> str:
    return "[" + ",".join(str(x) for x in vec.tolist()) + "]"


def _pg_to_vec(pg_str: str) -> np.ndarray:
    inner = pg_str.strip("[]")
    return np.array([float(x) for x in inner.split(",")], dtype=np.float32)
