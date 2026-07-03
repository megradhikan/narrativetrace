"""
Background job: runs coordination detection across all active clusters
every DETECTION_INTERVAL_SECONDS (default 60s).
"""

from __future__ import annotations

import logging
import threading
import time

import psycopg2.extras

from coordination.config import DETECTION_INTERVAL_SECONDS
from coordination.detector import check_cluster
from ingestion.db import get_connection

logger = logging.getLogger(__name__)


def run_once(conn) -> int:
    """Check all active clusters. Returns total alerts created."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT cluster_id FROM clusters
            WHERE updated_at > NOW() - INTERVAL '24 hours'
              AND post_count >= 3
        """)
        cluster_ids = [r["cluster_id"] for r in cur.fetchall()]

    total = 0
    for cid in cluster_ids:
        try:
            alerts = check_cluster(conn, cid)
            total += len(alerts)
        except Exception as exc:
            logger.error("Detection error for cluster %s: %s", cid[:8], exc)
    return total


def run_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(timeout=DETECTION_INTERVAL_SECONDS):
        conn = get_connection()
        try:
            n = run_once(conn)
            if n:
                logger.info("Coordination detection: %d new alert(s)", n)
        except Exception as exc:
            logger.error("Detection loop error: %s", exc)
        finally:
            conn.close()


def start_background(stop_event: threading.Event | None = None) -> threading.Thread:
    if stop_event is None:
        stop_event = threading.Event()
    t = threading.Thread(target=run_loop, args=(stop_event,), daemon=True, name="coordination")
    t.start()
    logger.info("Coordination detection job started (interval=%ds)", DETECTION_INTERVAL_SECONDS)
    return t
