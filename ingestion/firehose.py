"""
AT Protocol firehose consumer.

Connects to the Bluesky firehose, filters text post-create events,
and yields parsed post dicts. Handles reconnection with exponential backoff.
"""

import logging
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Iterator

from atproto import CAR, FirehoseSubscribeReposClient, parse_subscribe_repos_message
from atproto_client.models.utils import get_or_create as model_from_data

from ingestion.config import RECONNECT_BASE_DELAY, RECONNECT_MAX_DELAY

logger = logging.getLogger(__name__)

POST_LEXICON = "app.bsky.feed.post"

_SENTINEL = object()


def _extract_posts(message) -> list[dict]:
    """Parse a raw firehose message frame; return list of post dicts (may be empty)."""
    try:
        commit = parse_subscribe_repos_message(message)
    except Exception:
        return []

    if not hasattr(commit, "ops") or not hasattr(commit, "blocks"):
        return []

    # Decode the CAR archive embedded in the commit to get actual record bytes
    try:
        car = CAR.from_bytes(commit.blocks)
    except Exception:
        return []

    repo_did = getattr(commit, "repo", "") or getattr(commit, "did", "")
    posts = []

    for op in commit.ops:
        if op.action != "create":
            continue
        if not op.path.startswith("app.bsky.feed.post/"):
            continue
        if op.cid is None:
            continue

        # Look up the record block by CID
        raw_block = car.blocks.get(op.cid)
        if raw_block is None:
            continue

        # raw_block is a dict decoded from IPLD/CBOR
        if not isinstance(raw_block, dict):
            continue

        record_type = raw_block.get("$type")
        if record_type != POST_LEXICON:
            continue

        text = raw_block.get("text")
        if not isinstance(text, str) or not text.strip():
            continue

        created_at_raw = raw_block.get("createdAt")
        try:
            created_at = datetime.fromisoformat(
                str(created_at_raw).replace("Z", "+00:00")
            )
        except (ValueError, AttributeError, TypeError):
            created_at = datetime.now(timezone.utc)

        rkey = op.path.split("/")[-1]
        post_id = f"{repo_did}/{rkey}"

        # Make raw_json serialisable (remove CID objects etc.)
        raw_json = {
            "$type": POST_LEXICON,
            "text": text,
            "createdAt": created_at_raw,
            "_repo": repo_did,
            "_rkey": rkey,
        }
        # Include langs/facets/reply if present
        for extra in ("langs", "reply", "facets", "embed"):
            if extra in raw_block:
                try:
                    # Only include if JSON-serialisable
                    import json
                    json.dumps(raw_block[extra])
                    raw_json[extra] = raw_block[extra]
                except (TypeError, ValueError):
                    pass

        posts.append({
            "post_id": post_id,
            "author_did": repo_did,
            "text": text,
            "created_at": created_at,
            "raw_json": raw_json,
        })

    return posts


def stream_posts(stop_after: int | None = None) -> Iterator[dict]:
    """
    Yields parsed post dicts from the AT Protocol firehose.
    Reconnects with exponential backoff on failure.

    stop_after: stop after yielding this many posts (used for fixture capture).
    """
    delay = RECONNECT_BASE_DELAY
    yielded = 0

    while True:
        q: queue.Queue = queue.Queue(maxsize=2000)
        client = FirehoseSubscribeReposClient()

        def on_message(message) -> None:
            for post in _extract_posts(message):
                try:
                    q.put_nowait(post)
                except queue.Full:
                    pass  # drop rather than block the firehose thread

        error_holder: list[Exception] = []

        def run_client():
            try:
                client.start(on_message)
            except Exception as exc:
                error_holder.append(exc)
            finally:
                q.put(_SENTINEL)

        t = threading.Thread(target=run_client, daemon=True)
        t.start()
        logger.info("Connecting to firehose")

        try:
            while True:
                try:
                    item = q.get(timeout=30)
                except queue.Empty:
                    logger.warning("No messages for 30s, reconnecting")
                    client.stop()
                    break

                if item is _SENTINEL:
                    if error_holder:
                        raise error_holder[0]
                    return  # clean stop

                yield item
                yielded += 1
                delay = RECONNECT_BASE_DELAY  # reset on success

                if stop_after is not None and yielded >= stop_after:
                    client.stop()
                    t.join(timeout=5)
                    return

        except Exception as exc:
            logger.warning("Firehose error: %s — reconnecting in %.1fs", exc, delay)
            try:
                client.stop()
            except Exception:
                pass
            t.join(timeout=5)
            time.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
