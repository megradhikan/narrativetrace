"""
DB helpers for coordination alerts.
"""

from __future__ import annotations

import psycopg2.extras
from ingestion.db import get_connection


def init_alerts_table(conn=None) -> None:
    owned = conn is None
    if owned:
        conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS coordination_alerts (
                    alert_id        BIGSERIAL PRIMARY KEY,
                    cluster_id      TEXT NOT NULL REFERENCES clusters(cluster_id),
                    explanation     TEXT NOT NULL,
                    accounts        TEXT[] NOT NULL,
                    timing_window_s INTEGER NOT NULL,
                    has_overlap     BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    resolved        BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_cluster
                ON coordination_alerts (cluster_id)
            """)
        conn.commit()
    finally:
        if owned:
            conn.close()


def insert_alert(conn, cluster_id: str, explanation: str, accounts: list[str],
                 timing_window_s: int, has_overlap: bool) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO coordination_alerts
                (cluster_id, explanation, accounts, timing_window_s, has_overlap)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING alert_id
        """, (cluster_id, explanation, accounts, timing_window_s, has_overlap))
        alert_id = cur.fetchone()[0]
    conn.commit()
    return alert_id


def get_alerts(conn, resolved: bool = False, limit: int = 50) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT a.alert_id, a.cluster_id, a.explanation, a.accounts,
                   a.timing_window_s, a.has_overlap, a.created_at::text, a.resolved,
                   c.topic, c.post_count,
                   (SELECT p.text FROM posts p
                    JOIN cluster_posts cp ON cp.post_id = p.post_id
                    WHERE cp.cluster_id = c.cluster_id
                    ORDER BY p.created_at ASC LIMIT 1) AS sample_text
            FROM coordination_alerts a
            JOIN clusters c USING (cluster_id)
            WHERE a.resolved = %s
            ORDER BY a.created_at DESC
            LIMIT %s
        """, (resolved, limit))
        return [dict(r) for r in cur.fetchall()]


def alert_exists_for_cluster(conn, cluster_id: str) -> bool:
    """Return True if an unresolved alert already exists for this cluster."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM coordination_alerts
            WHERE cluster_id = %s AND resolved = FALSE
            LIMIT 1
        """, (cluster_id,))
        return cur.fetchone() is not None
