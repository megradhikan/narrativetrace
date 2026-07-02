"""
Singleton wrapper around a sentence-transformers model.
Lazy-loads on first use so import is fast.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from clustering.config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
    return SentenceTransformer(EMBEDDING_MODEL)


def embed(text: str) -> np.ndarray:
    """Return a unit-normalised embedding vector for the given text."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


def embed_batch(texts: list[str]) -> list[np.ndarray]:
    """Embed a list of texts in one forward pass."""
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.astype(np.float32) for v in vecs]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two unit-normalised vectors."""
    return float(np.dot(a, b))
