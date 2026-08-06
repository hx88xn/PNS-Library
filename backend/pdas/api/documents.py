from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

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


@router.delete("/documents/{document_id}")
async def remove(
    document_id: int,
    app_state: AppState = Depends(state),
    user: dict = Depends(current_user),
) -> dict:
    """Remove one document and everything derived from it.

    FAISS's IndexFlatIP cannot delete a row without renumbering every vector
    after it, which would silently invalidate the `vector_ordinal` of every
    remaining chunk. So the rows go, and the index is rebuilt from what is
    left. On a corpus this size that costs seconds and removes an entire class
    of "the search returned the wrong passage" bug.
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an administrator can remove documents.",
        )

    row = app_state.conn.execute(
        "SELECT filename, stored_path, chunk_count FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such document.")

    app_state.conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
    app_state.conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    app_state.conn.commit()

    if row["stored_path"]:
        Path(row["stored_path"]).unlink(missing_ok=True)

    from ..core.ingest import reindex

    remaining = await reindex(
        conn=app_state.conn,
        store=app_state.store,
        sparse=app_state.sparse,
        ollama=app_state.ollama,
        settings=app_state.settings,
    )

    return {
        "removed": row["filename"],
        "chunks_removed": row["chunk_count"],
        "chunks_remaining": remaining,
    }
