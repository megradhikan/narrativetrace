"""
Background job that classifies untagged clusters with a topic label.

Runs every CLASSIFY_INTERVAL_SECONDS. For each cluster without a topic,
fetches a sample of its post texts and runs zero-shot classification.
"""

from __future__ import annotations

import logging
import threading
import time

import psycopg2.extras

from clustering.classifier import classify_cluster
from ingestion.db import get_connection

logger = logging.getLogger(__name__)

CLASSIFY_INTERVAL_SECONDS = int(__import__("os").environ.get("CLASSIFY_INTERVAL_SECONDS", "30"))


def init_topic_columns(conn=None) -> None:
    owned = conn is None
    if owned:
        conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE clusters ADD COLUMN IF NOT EXISTS topic TEXT;")
            cur.execute("ALTER TABLE clusters ADD COLUMN IF NOT EXISTS topic_score FLOAT;")
        conn.commit()
    finally:
        if owned:
            conn.close()


def classify_pending(conn) -> int:
    """Classify all clusters that don't yet have a topic. Returns count classified."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT c.cluster_id,
                   array_agg(p.text ORDER BY p.created_at ASC) AS texts
            FROM clusters c
            JOIN cluster_posts cp USING (cluster_id)
            JOIN posts p USING (post_id)
            WHERE c.topic IS NULL
            GROUP BY c.cluster_id
        """)
        rows = cur.fetchall()

    count = 0
    for row in rows:
        texts = [t for t in (row["texts"] or []) if t]
        if not texts:
            continue
        label, score = classify_cluster(texts)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE clusters SET topic = %s, topic_score = %s WHERE cluster_id = %s",
                (label, score, row["cluster_id"]),
            )
        conn.commit()
        count += 1
        logger.debug("Cluster %s → topic=%s (%.2f)", row["cluster_id"], label, score)

    if count:
        logger.info("Classified %d clusters", count)
    return count


def run_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(timeout=CLASSIFY_INTERVAL_SECONDS):
        conn = get_connection()
        try:
            classify_pending(conn)
        except Exception as exc:
            logger.error("Classification job error: %s", exc)
        finally:
            conn.close()


def start_background(stop_event: threading.Event | None = None) -> threading.Thread:
    if stop_event is None:
        stop_event = threading.Event()
    t = threading.Thread(target=run_loop, args=(stop_event,), daemon=True, name="classify")
    t.start()
    logger.info("Classification background job started (interval=%ds)", CLASSIFY_INTERVAL_SECONDS)
    return t
