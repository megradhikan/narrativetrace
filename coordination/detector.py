"""
Coordination signal detector.

Heuristic combining two signals:
  (a) Timing — multiple distinct accounts post near-identical claim text
      within a short configurable window (default 2 minutes).
  (b) Topology — those accounts have NO prior interaction overlap in the
      cluster's interaction graph (no shared edges).

A flag is only raised when BOTH signals are present. Every flag carries a
plain-language explanation string — never a bare boolean.

IMPORTANT: All UI copy and code comments must use the framing
"coordination signal — flagged for review". Never use "bot" or
"disinformation" anywhere in this module.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from itertools import combinations

import numpy as np
import psycopg2.extras

from clustering.embeddings import cosine_similarity
from coordination.config import (
    DETECTION_LOOKBACK_HOURS,
    MIN_ACCOUNTS_IN_WINDOW,
    NEAR_IDENTICAL_THRESHOLD,
    TIMING_WINDOW_SECONDS,
)
from coordination.db import alert_exists_for_cluster, insert_alert
from graph.builder import load_cluster_graph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core detection logic (pure — no DB dependency, easy to test)
# ---------------------------------------------------------------------------

def detect_timing_groups(
    posts: list[dict],
    window_seconds: int = TIMING_WINDOW_SECONDS,
    min_accounts: int = MIN_ACCOUNTS_IN_WINDOW,
    similarity_threshold: float = NEAR_IDENTICAL_THRESHOLD,
) -> list[dict]:
    """
    Given a list of post dicts with keys: post_id, author_did, created_at (datetime), embedding (np.ndarray),
    find groups of >= min_accounts distinct authors who posted near-identical content
    within window_seconds of each other.

    Returns a list of flagged groups, each a dict:
      {accounts: [did, ...], window_seconds: int, earliest: datetime, latest: datetime}
    """
    if len(posts) < min_accounts:
        return []

    # Sort by time
    sorted_posts = sorted(posts, key=lambda p: p["created_at"])
    flagged_groups = []
    used_indices: set[int] = set()

    for i, anchor in enumerate(sorted_posts):
        if i in used_indices:
            continue
        anchor_time = anchor["created_at"]
        anchor_emb = anchor["embedding"]
        window_end = anchor_time + timedelta(seconds=window_seconds)

        group = [anchor]
        group_dids = {anchor["author_did"]}

        for j, other in enumerate(sorted_posts):
            if j == i or j in used_indices:
                continue
            if other["created_at"] > window_end:
                break
            if other["author_did"] in group_dids:
                continue
            sim = cosine_similarity(anchor_emb, other["embedding"])
            if sim >= similarity_threshold:
                group.append(other)
                group_dids.add(other["author_did"])

        if len(group_dids) >= min_accounts:
            times = [p["created_at"] for p in group]
            flagged_groups.append({
                "accounts": list(group_dids),
                "window_seconds": int((max(times) - min(times)).total_seconds()) or 1,
                "earliest": min(times),
                "latest": max(times),
                "posts": group,
            })
            used_indices.update(
                sorted_posts.index(p) for p in group if p in sorted_posts
            )

    return flagged_groups


def has_network_overlap(graph, accounts: list[str]) -> bool:
    """
    Return True if any pair of accounts in the list share a prior interaction
    edge in the cluster graph (either direction).
    """
    account_set = set(accounts)
    for u, v in graph.edges():
        if u in account_set and v in account_set:
            return True
    return False


def build_explanation(accounts: list[str], window_seconds: int, overlap: bool) -> str:
    """
    Build a plain-language explanation string for the coordination signal.
    Never uses the words "bot" or "disinformation".
    """
    n = len(accounts)
    if window_seconds < 60:
        window_str = f"{window_seconds} second{'s' if window_seconds != 1 else ''}"
    else:
        mins = round(window_seconds / 60, 1)
        window_str = f"{mins} minute{'s' if mins != 1.0 else ''}"

    overlap_str = (
        "with no prior interaction overlap in the network"
        if not overlap
        else "some of whom have prior network overlap"
    )
    return (
        f"{n} accounts posted near-identical claims within {window_str}, "
        f"{overlap_str}. Coordination signal — flagged for review."
    )


# ---------------------------------------------------------------------------
# Full detection run against a cluster
# ---------------------------------------------------------------------------

def _fetch_cluster_posts_with_embeddings(conn, cluster_id: str, lookback_hours: int) -> list[dict]:
    """Fetch posts with embeddings for a cluster within the lookback window."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT p.post_id, p.author_did, p.created_at, p.embedding::text
            FROM posts p
            JOIN cluster_posts cp ON cp.post_id = p.post_id
            WHERE cp.cluster_id = %s
              AND p.embedding IS NOT NULL
              AND p.created_at > NOW() - INTERVAL '%s hours'
            ORDER BY p.created_at ASC
        """, (cluster_id, lookback_hours))
        rows = cur.fetchall()

    result = []
    for row in rows:
        emb = _pg_to_vec(row["embedding"])
        result.append({
            "post_id": row["post_id"],
            "author_did": row["author_did"],
            "created_at": row["created_at"].replace(tzinfo=timezone.utc)
                if row["created_at"].tzinfo is None else row["created_at"],
            "embedding": emb,
        })
    return result


def _pg_to_vec(pg_str: str) -> np.ndarray:
    inner = pg_str.strip("[]")
    return np.array([float(x) for x in inner.split(",")], dtype=np.float32)


def check_cluster(conn, cluster_id: str) -> list[int]:
    """
    Run coordination detection on a single cluster.
    Inserts alerts for any flagged groups (skipping clusters already flagged).
    Returns list of new alert_ids created.
    """
    if alert_exists_for_cluster(conn, cluster_id):
        return []

    posts = _fetch_cluster_posts_with_embeddings(conn, cluster_id, DETECTION_LOOKBACK_HOURS)
    if not posts:
        return []

    groups = detect_timing_groups(posts)
    if not groups:
        return []

    graph = load_cluster_graph(conn, cluster_id)
    alert_ids = []

    for group in groups:
        overlap = has_network_overlap(graph, group["accounts"])
        # Only flag when there is NO network overlap (pure coordination signal)
        if overlap:
            continue
        explanation = build_explanation(
            group["accounts"], group["window_seconds"], overlap=False
        )
        alert_id = insert_alert(
            conn,
            cluster_id=cluster_id,
            explanation=explanation,
            accounts=group["accounts"],
            timing_window_s=group["window_seconds"],
            has_overlap=False,
        )
        alert_ids.append(alert_id)
        logger.info(
            "Coordination signal: cluster=%s accounts=%d window=%ds alert_id=%d",
            cluster_id[:8], len(group["accounts"]), group["window_seconds"], alert_id,
        )

    return alert_ids
