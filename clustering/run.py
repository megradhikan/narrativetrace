"""
CLI entrypoint for v0.2: python -m clustering.run

Streams posts from the firehose, embeds them, and clusters them incrementally.
Also starts the background re-clustering job.

Usage:
    python -m clustering.run
"""

import logging
import signal
import threading
import time

from ingestion.db import get_connection, init_db, insert_post
from ingestion.firehose import stream_posts
from clustering.clusterer import process_post
from clustering.db import init_cluster_tables
from clustering.recluster import start_background
from graph.db import init_graph_tables
from graph.builder import record_interactions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_running = True
_stop_event = threading.Event()


def _handle_signal(signum, frame):
    global _running
    logger.info("Shutting down...")
    _running = False
    _stop_event.set()


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Initialising database tables...")
    conn = get_connection()
    init_db(conn)
    init_cluster_tables(conn)
    init_graph_tables(conn)
    conn.close()

    logger.info("Starting re-clustering background job...")
    start_background(_stop_event)

    conn = get_connection()
    count = 0
    window_start = time.monotonic()

    try:
        for post in stream_posts():
            if not _running:
                break

            insert_post(
                conn,
                post_id=post["post_id"],
                author_did=post["author_did"],
                text=post["text"],
                created_at=post["created_at"],
                raw_json=post["raw_json"],
            )

            cluster_id = process_post(conn, post["post_id"], post["text"])
            record_interactions(conn, post, cluster_id)
            count += 1

            elapsed = time.monotonic() - window_start
            if elapsed >= 60:
                logger.info(
                    "Posts processed: %d | Rate: %.1f/min",
                    count, count / (elapsed / 60),
                )
                window_start = time.monotonic()
    finally:
        conn.close()
        logger.info("Done. Total posts processed: %d", count)


if __name__ == "__main__":
    main()
