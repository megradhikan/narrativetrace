"""
Coordination detection tests.

Key acceptance criteria from PRD v0.5:
  1. Synthetic tight-timing posts trigger a flag.
  2. Organic, staggered posting over hours does NOT trigger a flag.
  3. Every flag carries a plain-language explanation string.
  4. Copy never uses "bot" or "disinformation".
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import networkx as nx
import numpy as np
import pytest

from clustering.embeddings import embed
from coordination.detector import (
    build_explanation,
    detect_timing_groups,
    has_network_overlap,
)
from coordination.config import TIMING_WINDOW_SECONDS, MIN_ACCOUNTS_IN_WINDOW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_posts(texts: list[str], dids: list[str], times: list[datetime]) -> list[dict]:
    return [
        {
            "post_id": f"{did}/r{i}",
            "author_did": did,
            "created_at": t,
            "embedding": embed(text),
        }
        for i, (text, did, t) in enumerate(zip(texts, dids, times))
    ]


NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Test 1 (PRD): Tight-timing coordination triggers a flag
# ---------------------------------------------------------------------------

COORDINATED_TEXT = "The election was stolen — the results are fraudulent."
COORDINATED_PARAPHRASES = [
    "The election was stolen — the results are fraudulent.",
    "Election results are fraudulent, the election was stolen.",
    "Results of the election are a fraud — it was stolen from the people.",
]

class TestCoordinatedPostingTriggersFlag:
    def test_three_accounts_in_30s_triggers(self):
        """3 accounts post near-identical text within 30 seconds → flag."""
        posts = _make_posts(
            texts=COORDINATED_PARAPHRASES,
            dids=["did:plc:a", "did:plc:b", "did:plc:c"],
            times=[NOW, NOW + timedelta(seconds=10), NOW + timedelta(seconds=25)],
        )
        groups = detect_timing_groups(posts, window_seconds=120, min_accounts=3)
        assert len(groups) >= 1, "Expected at least one flagged group"
        assert len(groups[0]["accounts"]) >= 3

    def test_four_accounts_within_window_triggers(self):
        """4 accounts within the window — should also flag."""
        texts = COORDINATED_PARAPHRASES + [
            "The stolen election — fraudulent results have been confirmed."
        ]
        posts = _make_posts(
            texts=texts,
            dids=["did:plc:a", "did:plc:b", "did:plc:c", "did:plc:d"],
            times=[NOW + timedelta(seconds=i * 15) for i in range(4)],
        )
        groups = detect_timing_groups(posts, window_seconds=120, min_accounts=3)
        assert len(groups) >= 1

    def test_flag_contains_all_accounts(self):
        posts = _make_posts(
            texts=COORDINATED_PARAPHRASES,
            dids=["did:plc:a", "did:plc:b", "did:plc:c"],
            times=[NOW, NOW + timedelta(seconds=5), NOW + timedelta(seconds=15)],
        )
        groups = detect_timing_groups(posts, window_seconds=120, min_accounts=3)
        assert len(groups) >= 1
        flagged_dids = set(groups[0]["accounts"])
        assert {"did:plc:a", "did:plc:b", "did:plc:c"}.issubset(flagged_dids)


# ---------------------------------------------------------------------------
# Test 2 (PRD): Organic staggered posting does NOT trigger a flag
# ---------------------------------------------------------------------------

ORGANIC_TEXTS = [
    "Climate scientists warn of accelerating ice melt in the Arctic.",
    "New report: Arctic ice melting faster than previously predicted.",
    "Scientists say Arctic sea ice is melting at an alarming rate.",
]

class TestOrganicPostingDoesNotTrigger:
    def test_staggered_over_hours_no_flag(self):
        """Same claim posted organically across 3 hours → no flag."""
        posts = _make_posts(
            texts=ORGANIC_TEXTS,
            dids=["did:plc:a", "did:plc:b", "did:plc:c"],
            times=[
                NOW,
                NOW + timedelta(hours=1),
                NOW + timedelta(hours=2, minutes=45),
            ],
        )
        groups = detect_timing_groups(posts, window_seconds=120, min_accounts=3)
        assert len(groups) == 0, f"Expected no flags for organic posting, got {groups}"

    def test_two_accounts_only_no_flag(self):
        """Only 2 accounts in window (below min_accounts=3) → no flag."""
        posts = _make_posts(
            texts=COORDINATED_PARAPHRASES[:2],
            dids=["did:plc:a", "did:plc:b"],
            times=[NOW, NOW + timedelta(seconds=10)],
        )
        groups = detect_timing_groups(posts, window_seconds=120, min_accounts=3)
        assert len(groups) == 0

    def test_unrelated_content_in_window_no_flag(self):
        """3 accounts posting different topics quickly → no flag (similarity too low)."""
        posts = _make_posts(
            texts=[
                "Scientists discover a new exoplanet with liquid water.",
                "Local sports team wins championship in dramatic finale.",
                "New recipe: how to make sourdough bread at home.",
            ],
            dids=["did:plc:a", "did:plc:b", "did:plc:c"],
            times=[NOW, NOW + timedelta(seconds=5), NOW + timedelta(seconds=10)],
        )
        groups = detect_timing_groups(posts, window_seconds=120, min_accounts=3)
        assert len(groups) == 0, "Unrelated posts should not be flagged"


# ---------------------------------------------------------------------------
# Network overlap check
# ---------------------------------------------------------------------------

class TestNetworkOverlap:
    def test_no_overlap_returns_false(self):
        G = nx.DiGraph()
        G.add_edge("did:plc:x", "did:plc:y")
        accounts = ["did:plc:a", "did:plc:b", "did:plc:c"]
        assert has_network_overlap(G, accounts) is False

    def test_shared_edge_returns_true(self):
        G = nx.DiGraph()
        G.add_edge("did:plc:a", "did:plc:b")
        assert has_network_overlap(G, ["did:plc:a", "did:plc:b", "did:plc:c"]) is True

    def test_empty_graph_no_overlap(self):
        assert has_network_overlap(nx.DiGraph(), ["did:plc:a", "did:plc:b"]) is False


# ---------------------------------------------------------------------------
# Explanation string requirements (PRD: never "bot" or "disinformation")
# ---------------------------------------------------------------------------

class TestExplanationString:
    def test_explanation_is_non_empty(self):
        explanation = build_explanation(["did:plc:a", "did:plc:b", "did:plc:c"], 30, False)
        assert isinstance(explanation, str)
        assert len(explanation) > 0

    def test_explanation_contains_account_count(self):
        explanation = build_explanation(["did:plc:a", "did:plc:b", "did:plc:c"], 30, False)
        assert "3" in explanation

    def test_explanation_contains_review_framing(self):
        """Must include 'flagged for review' — never a bare verdict."""
        explanation = build_explanation(["did:plc:a", "did:plc:b", "did:plc:c"], 30, False)
        assert "flagged for review" in explanation.lower()

    def test_explanation_never_says_bot(self):
        explanation = build_explanation(["did:plc:a", "did:plc:b", "did:plc:c"], 90, False)
        assert "bot" not in explanation.lower()

    def test_explanation_never_says_disinformation(self):
        explanation = build_explanation(["did:plc:a", "did:plc:b", "did:plc:c"], 90, False)
        assert "disinformation" not in explanation.lower()

    def test_explanation_shows_window_in_minutes(self):
        explanation = build_explanation(["a", "b", "c"], 120, False)
        assert "minute" in explanation

    def test_explanation_shows_window_in_seconds(self):
        explanation = build_explanation(["a", "b", "c"], 45, False)
        assert "second" in explanation

    def test_no_overlap_mentions_network(self):
        explanation = build_explanation(["a", "b", "c"], 30, overlap=False)
        assert "overlap" in explanation.lower()


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestCoordinationConfig:
    def test_timing_window_positive(self):
        assert TIMING_WINDOW_SECONDS > 0

    def test_min_accounts_at_least_two(self):
        assert MIN_ACCOUNTS_IN_WINDOW >= 2


# ---------------------------------------------------------------------------
# API: alerts endpoint
# ---------------------------------------------------------------------------

class TestAlertsEndpoint:
    @pytest.fixture
    def client(self):
        with (
            patch("backend.main.get_connection"),
            patch("backend.main.init_db"),
            patch("backend.main.init_cluster_tables"),
            patch("backend.main.init_topic_columns"),
            patch("backend.main.init_graph_tables"),
            patch("backend.main.init_alerts_table"),
            patch("backend.main.start_classify"),
            patch("backend.main.start_coordination"),
        ):
            from backend.main import app
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                yield c

    def test_alerts_returns_list(self, client):
        mock_alerts = [
            {
                "alert_id": 1,
                "cluster_id": "c1",
                "explanation": "3 accounts posted near-identical claims within 30 seconds, "
                               "with no prior interaction overlap in the network. "
                               "Coordination signal — flagged for review.",
                "accounts": ["did:plc:a", "did:plc:b", "did:plc:c"],
                "timing_window_s": 30,
                "has_overlap": False,
                "created_at": "2024-01-01T00:00:00+00:00",
                "resolved": False,
                "topic": "politics",
                "post_count": 5,
                "sample_text": "The election was stolen.",
            }
        ]
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: s
        cur.__exit__ = MagicMock(return_value=False)
        cur.fetchall.return_value = mock_alerts
        conn.cursor.return_value = cur

        with patch("backend.main.get_connection", return_value=conn):
            with patch("backend.main.get_alerts", return_value=mock_alerts):
                resp = client.get("/alerts")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["explanation"] is not None
        assert "flagged for review" in data[0]["explanation"].lower()
