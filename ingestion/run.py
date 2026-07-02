"""
CLI entrypoint: python -m ingestion.run

Streams posts from the AT Protocol firehose and persists them to Postgres.
Logs post count per minute to stdout.
"""

import logging
import signal
import sys
import time

from ingestion.db import get_connection, init_db, insert_post
from ingestion.firehose import stream_posts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_running = True


def _handle_signal(signum, frame):
    global _running
    logger.info("Shutting down...")
    _running = False


def main():
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Initialising database...")
    init_db()

    conn = get_connection()
    logger.info("Starting firehose ingestion. Press Ctrl-C to stop.")

    count = 0
    window_start = time.monotonic()
    window_count = 0

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
            count += 1
            window_count += 1

            elapsed = time.monotonic() - window_start
            if elapsed >= 60:
                rate = window_count / elapsed * 60
                logger.info(
                    "Posts this minute: %d  |  Total ingested: %d  |  Rate: %.1f posts/min",
                    window_count,
                    count,
                    rate,
                )
                window_count = 0
                window_start = time.monotonic()

    finally:
        conn.close()
        logger.info("Ingestion stopped. Total posts persisted: %d", count)


if __name__ == "__main__":
    main()
