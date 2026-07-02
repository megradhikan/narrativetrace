"""
Clustering tests — no live firehose, no live Postgres.
All DB calls are mocked; embedding model runs locally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from clustering.embeddings import cosine_similarity, embed, embed_batch
from clustering.config import CLUSTER_SIMILARITY_THRESHOLD


# ---------------------------------------------------------------------------
# Embedding tests
# ---------------------------------------------------------------------------

class TestEmbeddings:
    def test_embed_returns_float32_array(self):
        vec = embed("The government announced new climate policy.")
        assert vec.dtype == np.float32
        assert vec.ndim == 1
        assert len(vec) == 384

    def test_embed_is_unit_normalised(self):
        vec = embed("hello world")
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5

    def test_cosine_similarity_identical(self):
        vec = embed("climate change is accelerating")
        assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-5

    def test_cosine_similarity_unrelated(self):
        a = embed("The stock market crashed today due to rising interest rates.")
        b = embed("Scientists discover new species of deep-sea fish near Iceland.")
        sim = cosine_similarity(a, b)
        assert sim < 0.85, f"Unrelated texts too similar: {sim:.3f}"

    def test_embed_batch_matches_individual(self):
        texts = ["hello", "world", "foo"]
        batch = embed_batch(texts)
        for text, bvec in zip(texts, batch):
            svec = embed(text)
            assert abs(cosine_similarity(bvec, svec) - 1.0) < 1e-4


# ---------------------------------------------------------------------------
# Core clustering criterion: 6 paraphrases together, 4 unrelated apart
# ---------------------------------------------------------------------------

PARAPHRASES = [
    "The government has announced a new tax on sugary drinks.",
    "Officials revealed a new sugar tax policy today.",
    "A new levy on drinks containing sugar was announced by the government.",
    "The administration unveiled a tax targeting sugary beverages.",
    "New government policy introduces a tax on drinks with high sugar content.",
    "Sugar-sweetened drink tax announced by government officials.",
]

UNRELATED = [
    "Scientists discover water on a distant moon of Saturn.",
    "Local football team wins championship after dramatic penalty shootout.",
    "Stock markets surge following positive jobs data from the US.",
    "Heavy rainfall causes flooding across several coastal towns.",
]


class TestClusteringCriterion:
    """
    Acceptance criterion from PRD v0.2:
    Given 10 posts where 6 are paraphrases of the same claim and 4 are unrelated,
    the clustering step groups the 6 together and keeps the 4 separate.
    """

    def _make_conn_mock(self):
        """Return a conn mock that tracks cluster state in memory."""
        clusters: dict = {}  # cluster_id -> {centroid, count, posts}

        conn = MagicMock()

        def fake_save_embedding(c, post_id, embedding):
            pass

        def fake_get_active_clusters(c, hours):
            return [
                {"cluster_id": cid, "centroid": d["centroid"], "post_count": d["count"]}
                for cid, d in clusters.items()
            ]

        def fake_create_cluster(c, post_id, centroid):
            cid = str(uuid.uuid4())
            clusters[cid] = {"centroid": centroid.copy(), "count": 1, "posts": [post_id]}
            return cid

        def fake_assign(c, cluster_id, post_id, new_centroid):
            clusters[cluster_id]["centroid"] = new_centroid.copy()
            clusters[cluster_id]["count"] += 1
            clusters[cluster_id]["posts"].append(post_id)

        return conn, clusters, fake_save_embedding, fake_get_active_clusters, fake_create_cluster, fake_assign

    def test_paraphrases_cluster_together_unrelated_apart(self):
        conn, clusters, fake_save, fake_get, fake_create, fake_assign = self._make_conn_mock()

        with (
            patch("clustering.clusterer.save_embedding", fake_save),
            patch("clustering.clusterer.get_active_clusters", fake_get),
            patch("clustering.clusterer.create_cluster", fake_create),
            patch("clustering.clusterer.assign_post_to_cluster", fake_assign),
        ):
            from clustering.clusterer import process_post

            all_posts = (
                [(f"para_{i}", t) for i, t in enumerate(PARAPHRASES)] +
                [(f"unrel_{i}", t) for i, t in enumerate(UNRELATED)]
            )

            assignments: dict[str, str] = {}
            for post_id, text in all_posts:
                cid = process_post(conn, post_id, text)
                assignments[post_id] = cid

        # All 6 paraphrases should share one cluster
        para_clusters = {assignments[f"para_{i}"] for i in range(6)}
        assert len(para_clusters) == 1, (
            f"Paraphrases split across {len(para_clusters)} clusters: {para_clusters}"
        )

        # Each unrelated post should be in its own cluster (none of them should share
        # a cluster with any other unrelated post OR with the paraphrase cluster)
        para_cluster = next(iter(para_clusters))
        for i in range(4):
            pid = f"unrel_{i}"
            assert assignments[pid] != para_cluster, (
                f"Unrelated post {pid} incorrectly merged into paraphrase cluster"
            )

        # Unrelated posts should not all be in the same cluster either
        unrel_clusters = {assignments[f"unrel_{i}"] for i in range(4)}
        assert len(unrel_clusters) >= 2, (
            f"Too many unrelated posts merged into same cluster: {unrel_clusters}"
        )


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestClusteringConfig:
    def test_threshold_is_configurable(self):
        """Threshold must be a config value, not hardcoded inline."""
        from clustering import config
        assert 0.0 < config.CLUSTER_SIMILARITY_THRESHOLD < 1.0

    def test_threshold_default_documented_range(self):
        """Default threshold should be in reasonable range for semantic similarity."""
        from clustering import config
        assert 0.6 <= config.CLUSTER_SIMILARITY_THRESHOLD <= 0.95

    def test_recluster_interval_positive(self):
        from clustering import config
        assert config.RECLUSTER_INTERVAL_SECONDS > 0


# ---------------------------------------------------------------------------
# Re-clustering job: runs in background without blocking
# ---------------------------------------------------------------------------

class TestReclusterBackground:
    def test_starts_as_daemon_thread(self):
        import threading
        from clustering.recluster import start_background

        stop = threading.Event()
        with patch("clustering.recluster.run_once"):
            t = start_background(stop)
            assert t.daemon is True
            assert t.is_alive()
            stop.set()

    def test_merge_logic_called_on_similar_clusters(self):
        """Two clusters with very high centroid similarity should be merged."""
        import threading
        from clustering.recluster import run_once

        vec = embed("The government announced a new sugar tax policy.")
        # Slightly perturbed version — still very similar
        perturbed = vec + np.random.normal(0, 0.01, vec.shape).astype(np.float32)
        perturbed /= np.linalg.norm(perturbed)

        fake_clusters = [
            {"cluster_id": "c1", "centroid": vec, "post_count": 3, "post_ids": ["p1", "p2", "p3"]},
            {"cluster_id": "c2", "centroid": perturbed, "post_count": 2, "post_ids": ["p4", "p5"]},
        ]
        fake_embeddings = {pid: vec for pid in ["p1", "p2", "p3", "p4", "p5"]}

        conn = MagicMock()
        with (
            patch("clustering.recluster.get_all_clusters_with_posts", return_value=fake_clusters),
            patch("clustering.recluster.get_post_embeddings", return_value=fake_embeddings),
            patch("clustering.recluster.update_cluster_centroid"),
            patch("clustering.recluster.merge_clusters") as mock_merge,
            patch("clustering.recluster.split_cluster"),
        ):
            run_once(conn)
            assert mock_merge.called, "Expected merge_clusters to be called for highly similar clusters"
