"""Sparse (BM25) index.

Held in memory and rebuilt from SQLite at startup and after every ingest. The
corpus is small enough that rebuilding costs well under a second, which is far
simpler than maintaining an incremental structure.

This half of retrieval is what finds `A-60`, `NES-109`, `GZ` and `SDO/NA/STAB-014`
— exact tokens that dense embeddings routinely miss.
"""

from __future__ import annotations

import re
import sqlite3
import threading

from rank_bm25 import BM25Okapi

# Keep dots, slashes and hyphens: they are load-bearing in document references
# and standards numbers. Splitting `NES-109` into `nes` and `109` would lose
# exactly the specificity that makes BM25 worth running.
_TOKEN = re.compile(r"[a-z0-9]+(?:[./-][a-z0-9]+)*")

# Function words carry no retrieval signal but do carry BM25 score. Left in,
# a query like "what colour should the wardroom curtains be" matches most of
# the corpus on "the" and "be", and the client then highlights those words in
# every result — noise that reads like a bug.
#
# Compound tokens are matched whole ("a-60" is one token), so removing "a"
# here does not damage a standards reference.
STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those of in on at to for
    from by with without within into onto is are was were be been being am
    do does did have has had can could shall should will would may might must
    it its as not no nor so such there here when where which who whom whose
    what why how all any both each few more most other some only own same
    """.split()
)


def tokenize(text: str, *, keep_stopwords: bool = False) -> list[str]:
    tokens = _TOKEN.findall(text.lower())
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in STOPWORDS]


class SparseIndex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bm25: BM25Okapi | None = None
        self._chunk_ids: list[str] = []

    def build(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT id, doc, title, section, tags, text FROM chunks ORDER BY rowid"
        ).fetchall()

        chunk_ids: list[str] = []
        corpus: list[list[str]] = []
        for row in rows:
            chunk_ids.append(row["id"])
            # Index the metadata alongside the body: a search for a drawing
            # number should match the chunk that carries it.
            blob = " ".join(
                filter(None, (row["doc"], row["title"], row["section"], row["tags"], row["text"]))
            )
            corpus.append(tokenize(blob))

        with self._lock:
            self._chunk_ids = chunk_ids
            self._bm25 = BM25Okapi(corpus) if corpus else None

    @property
    def size(self) -> int:
        return len(self._chunk_ids)

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        """Return (chunk_id, score), best first, dropping zero-score hits."""
        tokens = tokenize(query)
        if not tokens:
            return []

        with self._lock:
            if self._bm25 is None:
                return []
            scores = self._bm25.get_scores(tokens)
            chunk_ids = self._chunk_ids

        ranked = sorted(
            ((chunk_ids[i], float(score)) for i, score in enumerate(scores) if score > 0),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return ranked[:k]
