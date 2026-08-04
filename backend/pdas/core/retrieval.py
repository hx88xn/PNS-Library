"""Hybrid retrieval: dense + sparse, fused with Reciprocal Rank Fusion.

Dense search finds passages that mean the same thing in different words.
Sparse search finds `A-60`, `NES-109`, `GZ` and `SDO/NA/STAB-014` — the exact
tokens a design office actually searches for, which embeddings routinely miss.
Neither alone is sufficient on this corpus.

RRF fuses them without needing the two score scales to be comparable, which
they are not: cosine similarity sits in [-1, 1] and BM25 is unbounded.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..config import Settings
from ..db import row_to_chunk
from .bm25 import SparseIndex, tokenize
from .ollama import OllamaClient
from .store import VectorStore


@dataclass
class Retrieved:
    chunk: dict
    score: float
    """Fused RRF score. Only meaningful relative to others in the same result set."""
    matched_terms: list[str]


async def retrieve(
    *,
    query: str,
    conn: sqlite3.Connection,
    store: VectorStore,
    sparse: SparseIndex,
    ollama: OllamaClient,
    settings: Settings,
    collection: str = "all",
    limit: int = 50,
) -> list[Retrieved]:
    """Rank chunks against a query. An empty query returns nothing — callers
    wanting the whole corpus should list chunks instead."""
    if not query.strip():
        return []

    dense_ranking = await _dense(query, store, ollama, conn, settings)
    sparse_ranking = sparse.search(query, settings.sparse_k)

    fused = _rrf([[cid for cid, _ in dense_ranking], [cid for cid, _ in sparse_ranking]], settings.rrf_k)
    if not fused:
        return []

    rows = _load_chunks(conn, [cid for cid, _ in fused], collection)
    terms = _matched_terms(query, rows)

    results = [
        Retrieved(chunk=row_to_chunk(rows[cid]), score=score, matched_terms=terms[cid])
        for cid, score in fused
        if cid in rows
    ]
    return results[:limit]


async def _dense(
    query: str,
    store: VectorStore,
    ollama: OllamaClient,
    conn: sqlite3.Connection,
    settings: Settings,
) -> list[tuple[str, float]]:
    if not store.ready:
        return []

    embedding = (await ollama.embed([query]))[0]
    neighbours = store.search(embedding, settings.dense_k)
    if not neighbours:
        return []

    # Trim to the shoulder of this query's own score curve. Without this the
    # index returns dense_k neighbours for every query however unrelated, and a
    # search for a term appearing in one chunk comes back with two dozen.
    best = neighbours[0][1]
    floor = best * settings.dense_relative_floor
    neighbours = [(ordinal, score) for ordinal, score in neighbours if score >= floor]

    ordinals = [ordinal for ordinal, _ in neighbours]
    placeholders = ",".join("?" * len(ordinals))
    rows = conn.execute(
        f"SELECT id, vector_ordinal FROM chunks WHERE vector_ordinal IN ({placeholders})",
        ordinals,
    ).fetchall()

    by_ordinal = {row["vector_ordinal"]: row["id"] for row in rows}
    return [
        (by_ordinal[ordinal], score)
        for ordinal, score in neighbours
        if ordinal in by_ordinal
    ]


def _rrf(rankings: list[list[str]], k: int) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: each list contributes 1/(k + rank).

    k damps the influence of top positions so one ranker cannot dominate on
    the strength of a single confident hit.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


def _load_chunks(
    conn: sqlite3.Connection, chunk_ids: list[str], collection: str
) -> dict[str, sqlite3.Row]:
    if not chunk_ids:
        return {}

    placeholders = ",".join("?" * len(chunk_ids))
    sql = f"SELECT * FROM chunks WHERE id IN ({placeholders})"
    params: list = list(chunk_ids)

    if collection != "all":
        sql += " AND collection = ?"
        params.append(collection)

    return {row["id"]: row for row in conn.execute(sql, params).fetchall()}


def _matched_terms(query: str, rows: dict[str, sqlite3.Row]) -> dict[str, list[str]]:
    """Which query terms actually appear in each chunk.

    The client highlights these. Reporting only terms genuinely present avoids
    marking up a chunk that matched purely on semantic similarity, which would
    imply a textual match that isn't there.
    """
    query_terms = {t for t in tokenize(query) if len(t) > 1}
    matched: dict[str, list[str]] = {}

    for chunk_id, row in rows.items():
        haystack = " ".join(
            filter(None, (row["doc"], row["title"], row["section"], row["tags"], row["text"]))
        ).lower()
        matched[chunk_id] = sorted(term for term in query_terms if term in haystack)

    return matched
