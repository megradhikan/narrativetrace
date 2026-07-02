"""
Incremental clustering logic.

For each new post:
  1. Compute its embedding.
  2. Compare against centroids of active clusters (cosine similarity).
  3. If best match >= threshold, assign to that cluster and update centroid.
  4. Otherwise, create a new single-post cluster.

Centroid update: running mean — new_centroid = (old_centroid * n + embedding) / (n + 1).
"""

from __future__ import annotations

import logging

import numpy as np

from clustering.config import CLUSTER_ACTIVE_HOURS, CLUSTER_SIMILARITY_THRESHOLD
from clustering.db import (
    assign_post_to_cluster,
    create_cluster,
    get_active_clusters,
    save_embedding,
)
from clustering.embeddings import cosine_similarity, embed

logger = logging.getLogger(__name__)


def process_post(conn, post_id: str, text: str) -> str:
    """
    Embed the post, assign it to an existing cluster or create a new one.
    Returns the cluster_id the post was assigned to.
    """
    vec = embed(text)
    save_embedding(conn, post_id, vec)

    active = get_active_clusters(conn, CLUSTER_ACTIVE_HOURS)

    best_id: str | None = None
    best_sim: float = -1.0
    best_centroid: np.ndarray | None = None
    best_count: int = 0

    for cluster in active:
        sim = cosine_similarity(vec, cluster["centroid"])
        if sim > best_sim:
            best_sim = sim
            best_id = cluster["cluster_id"]
            best_centroid = cluster["centroid"]
            best_count = cluster["post_count"]

    if best_id is not None and best_sim >= CLUSTER_SIMILARITY_THRESHOLD:
        # Running-mean centroid update
        new_centroid = (best_centroid * best_count + vec) / (best_count + 1)
        norm = np.linalg.norm(new_centroid)
        if norm > 0:
            new_centroid = new_centroid / norm
        assign_post_to_cluster(conn, best_id, post_id, new_centroid)
        logger.debug(
            "Post %s → cluster %s (sim=%.3f)", post_id, best_id, best_sim
        )
        return best_id
    else:
        cluster_id = create_cluster(conn, post_id, vec)
        logger.debug("Post %s → new cluster %s", post_id, cluster_id)
        return cluster_id
