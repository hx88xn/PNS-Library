from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from ..schemas import DocumentRecord
from ..state import AppState
from .deps import current_user, state

router = APIRouter()

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".dxf": "image/vnd.dxf",
}


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


@router.get("/documents/{document_id}/file")
def source_file(
    document_id: int,
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> FileResponse:
    """The original file as it was uploaded.

    This is what the Documents tab renders and what a citation opens. Serving
    the source rather than the extracted text is the point: a reader checking a
    figure needs to see the table it came from, not the parser's reading of it.

    The corpus is RESTRICTED, so this is behind the same bearer token as
    everything else — the client fetches it and hands the viewer a blob rather
    than pointing an <iframe> at a URL it could not authenticate.
    """
    row = app_state.conn.execute(
        "SELECT filename, stored_path FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such document.")

    if not row["stored_path"]:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"{row['filename']} was indexed before source files were kept.",
        )

    path = Path(row["stored_path"])
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"The stored copy of {row['filename']} is missing from disk.",
        )

    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=row["filename"],
        headers={"Content-Disposition": f'inline; filename="{row["filename"]}"'},
    )


@router.get("/documents/{document_id}/text")
def source_text(
    document_id: int,
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> dict:
    """The parser's reading of a document, for formats no viewer can render.

    DOCX, XLSX and DXF have no in-browser renderer worth shipping air-gapped,
    so the Documents tab falls back to showing exactly what was indexed. That
    is arguably more honest for those formats anyway: it is the text retrieval
    actually searches.
    """
    row = app_state.conn.execute(
        "SELECT d.filename, t.text FROM documents d "
        "LEFT JOIN document_text t ON t.document_id = d.id WHERE d.id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such document.")

    return {"filename": row["filename"], "text": row["text"] or ""}


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
