"""
Capture ~500 real firehose events into fixtures/firehose_sample.json.

Run once:  python -m ingestion.capture_fixture
"""

import json
import logging
from pathlib import Path

from ingestion.firehose import stream_posts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TARGET = 500
FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "firehose_sample.json"


def main():
    logger.info("Capturing %d posts from firehose → %s", TARGET, FIXTURE_PATH)
    posts = []
    for post in stream_posts(stop_after=TARGET):
        # created_at is a datetime; serialise to ISO string for JSON
        serialisable = dict(post)
        serialisable["created_at"] = post["created_at"].isoformat()
        posts.append(serialisable)
        if len(posts) % 50 == 0:
            logger.info("Captured %d / %d", len(posts), TARGET)

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(posts, ensure_ascii=False, indent=2))
    logger.info("Saved %d posts to %s", len(posts), FIXTURE_PATH)


if __name__ == "__main__":
    main()
