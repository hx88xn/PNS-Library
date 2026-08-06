"""Browsing and searching the index.

The Retriever tab depends on the split here: an empty search box lists the
whole corpus, and a query narrows it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from ..core.bm25 import tokenize
from ..core.retrieval import retrieve
from ..db import row_to_chunk
from ..schemas import Chunk, ChunkListResponse, Collection, SearchHit, SearchResponse
from ..state import AppState
from .deps import current_user, state

router = APIRouter()

# Display names for the collections a document can be filed under. Ingestion
# assigns the id; this is the label the sidebar shows.
COLLECTION_LABELS = {
    "nsr": "Naval Staff Requirements",
    "hyd": "Hydrostatics & Stability",
    "str": "Structural Design",
    "prop": "Propulsion & Machinery",
    "sur": "Survivability",
    "std": "Standards & Rules",
    "drw": "Drawings",
    "uncategorised": "Uncategorised",
}


@router.get("/chunks", response_model=ChunkListResponse)
def list_chunks(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    collection: str = "all",
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> ChunkListResponse:
    where, params = ("", [])
    if collection != "all":
        where, params = ("WHERE collection = ?", [collection])

    total = app_state.conn.execute(
        f"SELECT COUNT(*) AS n FROM chunks {where}", params
    ).fetchone()["n"]

    rows = app_state.conn.execute(
        f"SELECT * FROM chunks {where} ORDER BY doc, ordinal LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    return ChunkListResponse(
        results=[Chunk(**row_to_chunk(row)) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query("", description="Empty returns nothing; use /chunks to browse"),
    collection: str = "all",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    mode: str = Query("ranked", pattern="^(ranked|all)$"),
    app_state: AppState = Depends(state),
    user: dict = Depends(current_user),
) -> SearchResponse:
    # mode=all bypasses ranking and returns every chunk literally containing
    # the terms, in document order. Ranked mode answers "what is most relevant";
    # this answers "where does this appear", which is what you need when
    # checking whether a document was ingested completely.
    if mode == "all":
        return _literal_search(app_state, q, collection, limit, offset, user)

    hits = await retrieve(
        query=q,
        conn=app_state.conn,
        store=app_state.store,
        sparse=app_state.sparse,
        ollama=app_state.ollama,
        settings=app_state.settings,
        collection=collection,
        limit=limit,
    )

    if hits:
        _log_query(app_state, user["service_no"], "search", q, [h.chunk["id"] for h in hits[:10]])

    # Normalise to 0..1 for the relevance bar. RRF scores are tiny and have no
    # absolute meaning, so the top hit anchors the scale.
    top = hits[0].score if hits else 1.0
    return SearchResponse(
        results=[
            SearchHit(
                chunk=Chunk(**hit.chunk),
                relevance=min(1.0, hit.score / top) if top else 0.0,
                matched_terms=hit.matched_terms,
            )
            for hit in hits
        ],
        total=len(hits),
        corpus_matches=_literal_matches(app_state, q, collection),
        occurrences=_occurrences(app_state, q, collection),
        query=q,
    )


def _literal_search(
    app_state: AppState,
    query: str,
    collection: str,
    limit: int,
    offset: int,
    user: dict,
) -> SearchResponse:
    """Every chunk containing all the query terms, in document order."""
    terms = [t for t in tokenize(query) if len(t) > 1]
    if not terms:
        return SearchResponse(results=[], total=0, corpus_matches=0, query=query)

    clauses = " AND ".join("lower(text) LIKE ?" for _ in terms)
    params: list = [f"%{t.lower()}%" for t in terms]
    where = f"WHERE {clauses}"
    if collection != "all":
        where += " AND collection = ?"
        params.append(collection)

    total = app_state.conn.execute(
        f"SELECT COUNT(*) AS n FROM chunks {where}", params
    ).fetchone()["n"]

    rows = app_state.conn.execute(
        f"SELECT * FROM chunks {where} ORDER BY doc, ordinal LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    if rows:
        _log_query(app_state, user["service_no"], "search", query,
                   [r["id"] for r in rows[:10]])

    return SearchResponse(
        results=[
            SearchHit(
                chunk=Chunk(**row_to_chunk(row)),
                # No ranking here, so no relevance to report. A bar filled from
                # a meaningless number would be worse than none.
                relevance=0.0,
                matched_terms=terms,
            )
            for row in rows
        ],
        total=total,
        corpus_matches=total,
        query=query,
    )


def _occurrences(app_state: AppState, query: str, collection: str) -> int | None:
    """How many times the query appears in the SOURCE documents.

    Counted against the stored original text, not the chunks. Chunks overlap by
    80 tokens so a criterion split across a boundary stays findable from both
    sides — which means text in the overlap is stored twice, and counting a
    term across chunks overstates the document by around 20% (measured). That
    error runs in the reassuring direction for anyone checking whether a file
    was ingested completely, so the count comes from what the parser actually
    read.

    Returns None when no source text is stored — documents ingested before this
    was recorded would otherwise silently contribute zero.
    """
    needle = query.strip().lower()
    if len(needle) < 2:
        return None

    stored, total = app_state.conn.execute(
        "SELECT (SELECT COUNT(*) FROM document_text) AS stored, "
        "       (SELECT COUNT(*) FROM documents WHERE status = 'indexed') AS total"
    ).fetchone()
    if total == 0 or stored < total:
        return None

    sql = (
        "SELECT SUM((length(lower(t.text)) - "
        "            length(replace(lower(t.text), ?, ''))) / ?) AS n "
        "FROM document_text t"
    )
    params: list = [needle, len(needle)]
    if collection != "all":
        sql += " JOIN documents d ON d.id = t.document_id WHERE d.collection = ?"
        params.append(collection)

    return app_state.conn.execute(sql, params).fetchone()["n"] or 0


def _literal_matches(app_state: AppState, query: str, collection: str) -> int | None:
    """How many chunks in the whole corpus literally contain every query term.

    Ranked results are capped by the retrieval pool, so `total` is "the best N
    we found", not "how many exist" — searching a 9,000-chunk index for a
    common term showed 30 when 105 chunks contained it. Reporting only the
    ranked count reads as completeness and quietly understates the corpus,
    which matters when the search is being used to check what was ingested.

    Returns None when the query has no literal terms to count.
    """
    terms = [t for t in tokenize(query) if len(t) > 1]
    if not terms:
        return None

    clauses = " AND ".join("lower(text) LIKE ?" for _ in terms)
    params: list = [f"%{t.lower()}%" for t in terms]

    sql = f"SELECT COUNT(*) AS n FROM chunks WHERE {clauses}"
    if collection != "all":
        sql += " AND collection = ?"
        params.append(collection)

    return app_state.conn.execute(sql, params).fetchone()["n"]


@router.get("/collections", response_model=list[Collection])
def collections(
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> list[Collection]:
    rows = app_state.conn.execute(
        "SELECT collection, COUNT(*) AS n FROM chunks GROUP BY collection ORDER BY collection"
    ).fetchall()

    return [
        Collection(
            id=row["collection"],
            label=COLLECTION_LABELS.get(row["collection"], row["collection"].title()),
            count=row["n"],
        )
        for row in rows
    ]


def _log_query(
    app_state: AppState, service_no: str, kind: str, query: str, chunk_ids: list[str]
) -> None:
    app_state.conn.execute(
        "INSERT INTO query_log(service_no, kind, query, chunk_ids, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (
            service_no,
            kind,
            query,
            json.dumps(chunk_ids),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    app_state.conn.commit()
