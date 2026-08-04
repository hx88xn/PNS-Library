from __future__ import annotations

from fastapi import APIRouter, Depends

from ..schemas import DocumentRecord
from ..state import AppState
from .deps import current_user, state

router = APIRouter()


@router.get("/documents", response_model=list[DocumentRecord])
def documents(
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> list[DocumentRecord]:
    rows = app_state.conn.execute(
        "SELECT id, filename, format, doc_ref, title, revision, collection, "
        "classification, pages, chunk_count, status, error, ingested_at "
        "FROM documents ORDER BY ingested_at DESC, filename"
    ).fetchall()

    return [DocumentRecord(**dict(row)) for row in rows]
