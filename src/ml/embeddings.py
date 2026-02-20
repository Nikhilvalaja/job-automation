"""Embedding service for semantic similarity matching.

Uses OpenAI text-embedding-3-small for generating embeddings.
Falls back to a lightweight TF-IDF based similarity when OpenAI is unavailable.

Features:
- Batch embedding (up to 20 texts per request)
- SQLite-based embedding cache (never re-embed same text)
- Cosine similarity computation
- Graceful fallback to TF-IDF
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from pathlib import Path

import numpy as np

from src.config import PROJECT_ROOT, get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

CACHE_DB_PATH = PROJECT_ROOT / "data" / "embedding_cache.db"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536  # dimension for text-embedding-3-small
MAX_BATCH_SIZE = 20


# ---------------------------------------------------------------------------
# Embedding Cache (SQLite)
# ---------------------------------------------------------------------------

def _get_cache_db() -> sqlite3.Connection:
    """Get connection to embedding cache database."""
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_cache (
            text_hash TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def _text_hash(text: str) -> str:
    """Compute hash of text for cache key."""
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _pack_vector(vec: list[float]) -> bytes:
    """Pack a float vector into bytes for SQLite storage."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(data: bytes) -> np.ndarray:
    """Unpack bytes back into numpy array."""
    count = len(data) // 4  # 4 bytes per float
    return np.array(struct.unpack(f"{count}f", data), dtype=np.float32)


# ---------------------------------------------------------------------------
# OpenAI Embedding Client
# ---------------------------------------------------------------------------

class EmbeddingService:
    """Generates and caches text embeddings.

    Uses OpenAI if configured, falls back to TF-IDF.
    """

    def __init__(self) -> None:
        self._client = None
        settings = get_settings()
        if settings.openai_api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=settings.openai_api_key)
                logger.info("EmbeddingService: OpenAI configured")
            except ImportError:
                logger.warning("EmbeddingService: openai package not installed")

    def is_configured(self) -> bool:
        """Check if OpenAI is available for real embeddings."""
        return self._client is not None

    def embed_text(self, text: str) -> np.ndarray:
        """Get embedding for a single text.

        Checks cache first. If not cached, generates and caches.
        """
        if not text.strip():
            return np.zeros(EMBEDDING_DIM, dtype=np.float32)

        # Check cache
        h = _text_hash(text)
        cached = self._get_cached(h)
        if cached is not None:
            return cached

        # Generate embedding
        if self._client:
            vec = self._embed_openai([text])[0]
        else:
            vec = self._embed_tfidf(text)

        # Cache it
        self._cache_embedding(h, vec)
        return vec

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """Embed multiple texts efficiently.

        Checks cache for each, only sends uncached to API.
        """
        results: list[np.ndarray | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            if not text.strip():
                results[i] = np.zeros(EMBEDDING_DIM, dtype=np.float32)
                continue

            h = _text_hash(text)
            cached = self._get_cached(h)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Batch embed uncached texts
        if uncached_texts:
            if self._client:
                vectors = self._embed_openai(uncached_texts)
            else:
                vectors = [self._embed_tfidf(t) for t in uncached_texts]

            for idx, vec, text in zip(uncached_indices, vectors, uncached_texts):
                results[idx] = vec
                self._cache_embedding(_text_hash(text), vec)

        return [r if r is not None else np.zeros(EMBEDDING_DIM, dtype=np.float32) for r in results]

    def _embed_openai(self, texts: list[str]) -> list[np.ndarray]:
        """Call OpenAI embedding API in batches."""
        all_vectors: list[np.ndarray] = []

        for i in range(0, len(texts), MAX_BATCH_SIZE):
            batch = texts[i:i + MAX_BATCH_SIZE]
            # Truncate very long texts (API limit ~8191 tokens)
            batch = [t[:8000] for t in batch]

            try:
                response = self._client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=batch,
                )
                for item in response.data:
                    all_vectors.append(np.array(item.embedding, dtype=np.float32))
            except Exception as e:
                logger.error(f"OpenAI embedding failed: {e}")
                # Fallback for this batch
                all_vectors.extend([self._embed_tfidf(t) for t in batch])

        return all_vectors

    def _embed_tfidf(self, text: str) -> np.ndarray:
        """Lightweight fallback embedding using character n-gram hashing.

        Not as good as real embeddings but deterministic and free.
        Uses a simple feature hashing approach to generate a fixed-size vector.
        """
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
        if not text:
            return vec

        text_lower = text.lower()
        words = text_lower.split()

        # Hash each word and n-gram into the vector
        for word in words:
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % EMBEDDING_DIM
            sign = 1.0 if (h >> 17) % 2 == 0 else -1.0
            vec[idx] += sign

        # Also hash bigrams
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            h = int(hashlib.md5(bigram.encode()).hexdigest(), 16)
            idx = h % EMBEDDING_DIM
            sign = 1.0 if (h >> 17) % 2 == 0 else -1.0
            vec[idx] += sign * 0.5

        # Normalize to unit vector
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec

    def _get_cached(self, text_hash: str) -> np.ndarray | None:
        """Check cache for an embedding."""
        try:
            conn = _get_cache_db()
            row = conn.execute(
                "SELECT embedding FROM embedding_cache WHERE text_hash = ? AND model = ?",
                (text_hash, EMBEDDING_MODEL if self._client else "tfidf"),
            ).fetchone()
            conn.close()
            if row:
                return _unpack_vector(row[0])
        except Exception:
            pass
        return None

    def _cache_embedding(self, text_hash: str, vec: np.ndarray) -> None:
        """Cache an embedding."""
        try:
            conn = _get_cache_db()
            model = EMBEDDING_MODEL if self._client else "tfidf"
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache (text_hash, model, embedding) VALUES (?, ?, ?)",
                (text_hash, model, _pack_vector(vec.tolist())),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Failed to cache embedding: {e}")


# ---------------------------------------------------------------------------
# Cosine Similarity
# ---------------------------------------------------------------------------

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 if either vector is zero.

    >>> a = np.array([1.0, 0.0, 0.0])
    >>> b = np.array([1.0, 0.0, 0.0])
    >>> cosine_similarity(a, b)
    1.0

    >>> b = np.array([0.0, 1.0, 0.0])
    >>> cosine_similarity(a, b)
    0.0
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))
