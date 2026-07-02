"""
Zero-shot topic classification for clusters.

Uses facebook/bart-large-mnli via the HF transformers zero-shot pipeline.
Assigns one topic label from CANDIDATE_LABELS to each cluster based on its
representative post texts.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from transformers import pipeline

logger = logging.getLogger(__name__)

CANDIDATE_LABELS = [
    "politics",
    "health",
    "finance",
    "natural disaster",
    "entertainment",
    "other",
]

CLASSIFICATION_MODEL = "facebook/bart-large-mnli"


@lru_cache(maxsize=1)
def _get_classifier():
    logger.info("Loading zero-shot classification model: %s", CLASSIFICATION_MODEL)
    return pipeline("zero-shot-classification", model=CLASSIFICATION_MODEL)


def classify_cluster(sample_texts: list[str]) -> tuple[str, float]:
    """
    Classify a cluster given a sample of its post texts.
    Returns (label, score).
    """
    if not sample_texts:
        return "other", 0.0

    # Join up to 5 representative texts for context
    combined = " | ".join(t[:200] for t in sample_texts[:5])
    classifier = _get_classifier()
    result = classifier(combined, candidate_labels=CANDIDATE_LABELS)
    return result["labels"][0], float(result["scores"][0])
