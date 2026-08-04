"""FAISS vector index.

Exact search (IndexFlatIP over L2-normalised vectors, so inner product is
cosine). A design office library is thousands of chunks, not millions — an
approximate index would trade recall for a speedup nobody would notice.

The index and the SQLite `chunks` table are kept in lockstep by
`chunks.vector_ordinal`, which is the row's position in the index.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import faiss
import numpy as np

from ..db import get_meta, set_meta


class IndexMismatch(RuntimeError):
    """The index was built with a different embedding model or dimension.

    Serving against it would return neighbours that look plausible and are
    meaningless, so we refuse and ask for a reindex instead.
    """


class VectorStore:
    def __init__(self, index_path: Path) -> None:
        self._path = index_path
        self._lock = threading.Lock()
        self._index: faiss.Index | None = None
        self._dim: int | None = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def load(self, conn: sqlite3.Connection, embed_model: str) -> None:
        """Load the index from disk, refusing if it was built differently."""
        stored_model = get_meta(conn, "embed_model")
        stored_dim = get_meta(conn, "embed_dim")

        if not self._path.exists():
            self._index = None
            self._dim = int(stored_dim) if stored_dim else None
            return

        if stored_model and stored_model != embed_model:
            raise IndexMismatch(
                f"Index was built with '{stored_model}' but the server is "
                f"configured for '{embed_model}'. Run `pdas reindex`."
            )

        with self._lock:
            self._index = faiss.read_index(str(self._path))
            self._dim = self._index.d

        if stored_dim and int(stored_dim) != self._dim:
            raise IndexMismatch(
                f"Index dimension {self._dim} does not match the recorded "
                f"dimension {stored_dim}. Run `pdas reindex`."
            )

    def reset(self, dim: int) -> None:
        with self._lock:
            self._index = faiss.IndexFlatIP(dim)
            self._dim = dim

    def save(self, conn: sqlite3.Connection, embed_model: str) -> None:
        with self._lock:
            if self._index is None:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            faiss.write_index(self._index, str(self._path))
            set_meta(conn, "embed_model", embed_model)
            set_meta(conn, "embed_dim", str(self._dim))
            set_meta(conn, "index_size", str(self._index.ntotal))
        conn.commit()

    # ── state ────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return 0 if self._index is None else self._index.ntotal

    @property
    def dim(self) -> int | None:
        return self._dim

    @property
    def ready(self) -> bool:
        return self._index is not None and self._index.ntotal > 0

    # ── operations ───────────────────────────────────────────────────────

    def add(self, vectors: list[list[float]]) -> list[int]:
        """Append vectors, returning the ordinal assigned to each."""
        if not vectors:
            return []

        matrix = _normalise(np.asarray(vectors, dtype=np.float32))

        with self._lock:
            if self._index is None:
                self._index = faiss.IndexFlatIP(matrix.shape[1])
                self._dim = matrix.shape[1]
            elif matrix.shape[1] != self._index.d:
                raise IndexMismatch(
                    f"Embedding dimension changed from {self._index.d} to "
                    f"{matrix.shape[1]}. Run `pdas reindex`."
                )

            start = self._index.ntotal
            self._index.add(matrix)
            return list(range(start, start + len(vectors)))

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        """Return (vector_ordinal, cosine similarity), best first."""
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []
            vector = _normalise(np.asarray([query], dtype=np.float32))
            k = min(k, self._index.ntotal)
            scores, ordinals = self._index.search(vector, k)

        return [
            (int(ordinal), float(score))
            for ordinal, score in zip(ordinals[0], scores[0])
            if ordinal != -1
        ]


def _normalise(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise in place so inner product equals cosine similarity."""
    faiss.normalize_L2(matrix)
    return matrix
