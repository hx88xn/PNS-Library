"""Browsing and searching the index.

The Retriever tab depends on the split here: an empty search box lists the
whole corpus, and a query narrows it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

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
    app_state: AppState = Depends(state),
    user: dict = Depends(current_user),
) -> SearchResponse:
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
        query=q,
    )


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
