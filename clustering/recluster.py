"""
Periodic re-clustering job.

Runs every RECLUSTER_INTERVAL_SECONDS (default 10 min) as a background thread.
For each cluster:
  - Recompute true centroid from member embeddings.
  - Check every pair of clusters: if centroids are >= MERGE_THRESHOLD similar, merge.
  - For large clusters, check intra-cluster cohesion; if any member is < SPLIT_THRESHOLD
    from the centroid, consider splitting into two groups via simple bisection.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from clustering.config import CLUSTER_SIMILARITY_THRESHOLD, RECLUSTER_INTERVAL_SECONDS
from clustering.db import (
    get_all_clusters_with_posts,
    get_post_embeddings,
    merge_clusters,
    split_cluster,
    update_cluster_centroid,
)
from clustering.embeddings import cosine_similarity
from ingestion.db import get_connection

logger = logging.getLogger(__name__)

# Merge two clusters if their centroids are above this (stricter than assignment)
MERGE_THRESHOLD = CLUSTER_SIMILARITY_THRESHOLD + 0.05

# Split a cluster if any member is below this similarity to the centroid
SPLIT_THRESHOLD = CLUSTER_SIMILARITY_THRESHOLD - 0.15

# Minimum cluster size to consider splitting
MIN_SPLIT_SIZE = 6


def _recompute_centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    centroid = np.mean(embeddings, axis=0)
    norm = np.linalg.norm(centroid)
    return centroid / norm if norm > 0 else centroid


def run_once(conn) -> None:
    clusters = get_all_clusters_with_posts(conn)
    if not clusters:
        return

    logger.info("Re-clustering: %d clusters", len(clusters))

    # Step 1: recompute centroids from actual member embeddings
    for c in clusters:
        embeddings_map = get_post_embeddings(conn, c["post_ids"])
        if not embeddings_map:
            continue
        vecs = list(embeddings_map.values())
        new_centroid = _recompute_centroid(vecs)
        update_cluster_centroid(conn, c["cluster_id"], new_centroid, len(vecs))
        c["centroid"] = new_centroid
        c["embeddings"] = embeddings_map

    # Step 2: merge clusters whose centroids are very similar
    merged: set[str] = set()
    for i, ca in enumerate(clusters):
        if ca["cluster_id"] in merged:
            continue
        for cb in clusters[i + 1:]:
            if cb["cluster_id"] in merged:
                continue
            sim = cosine_similarity(ca["centroid"], cb["centroid"])
            if sim >= MERGE_THRESHOLD:
                all_vecs = list(ca.get("embeddings", {}).values()) + list(cb.get("embeddings", {}).values())
                new_centroid = _recompute_centroid(all_vecs) if all_vecs else ca["centroid"]
                post_count = ca["post_count"] + cb["post_count"]
                logger.info(
                    "Merging cluster %s into %s (centroid sim=%.3f)",
                    cb["cluster_id"], ca["cluster_id"], sim,
                )
                merge_clusters(conn, ca["cluster_id"], cb["cluster_id"], new_centroid, post_count)
                merged.add(cb["cluster_id"])

    # Step 3: split clusters with low intra-cluster cohesion
    for c in clusters:
        if c["cluster_id"] in merged:
            continue
        embs = c.get("embeddings", {})
        if len(embs) < MIN_SPLIT_SIZE:
            continue
        centroid = c["centroid"]
        outliers = {pid for pid, vec in embs.items()
                    if cosine_similarity(vec, centroid) < SPLIT_THRESHOLD}
        if not outliers or len(outliers) >= len(embs):
            continue

        group_a = [pid for pid in embs if pid not in outliers]
        group_b = list(outliers)
        vecs_a = [embs[p] for p in group_a]
        vecs_b = [embs[p] for p in group_b]
        centroid_a = _recompute_centroid(vecs_a)
        centroid_b = _recompute_centroid(vecs_b)

        logger.info(
            "Splitting cluster %s: %d core / %d outliers",
            c["cluster_id"], len(group_a), len(group_b),
        )
        split_cluster(conn, c["cluster_id"], group_a, group_b, centroid_a, centroid_b)


def run_loop(stop_event: threading.Event) -> None:
    """Run the re-clustering job on a fixed interval until stop_event is set."""
    while not stop_event.wait(timeout=RECLUSTER_INTERVAL_SECONDS):
        conn = get_connection()
        try:
            run_once(conn)
        except Exception as exc:
            logger.error("Re-clustering error: %s", exc)
        finally:
            conn.close()


def start_background(stop_event: threading.Event | None = None) -> threading.Thread:
    """Start the re-clustering loop as a daemon thread. Returns the thread."""
    if stop_event is None:
        stop_event = threading.Event()
    t = threading.Thread(target=run_loop, args=(stop_event,), daemon=True, name="recluster")
    t.start()
    logger.info("Re-clustering background job started (interval=%ds)", RECLUSTER_INTERVAL_SECONDS)
    return t
