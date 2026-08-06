"""Upload and ingest documents.

Upload returns immediately with a job id; the client polls
`GET /api/ingest/{id}` for progress. A large document takes tens of minutes,
which no HTTP request should be holding open.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from ..core import ingest as ingest_core
from ..core.jobs import Job
from ..core.ollama import OllamaError
from ..state import AppState
from .deps import current_user, state

router = APIRouter()

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".dxf"}
MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # a 1,100-page rulebook is ~40 MB


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def upload(
    files: list[UploadFile] = File(...),
    app_state: AppState = Depends(state),
    user: dict = Depends(current_user),
) -> dict:
    if app_state.jobs.active():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An ingest is already running. Wait for it to finish.",
        )

    staged: list[Path] = []
    staging = Path(tempfile.mkdtemp(prefix="pdas-upload-", dir=app_state.settings.data_dir))

    for upload_file in files:
        name = Path(upload_file.filename or "unnamed").name
        suffix = Path(name).suffix.lower()

        if suffix == ".dwg":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{name}: DWG cannot be read. Convert to DXF or plot to PDF first.",
            )
        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{name}: unsupported format. Accepts PDF, DOCX, XLSX, DXF.",
            )

        destination = staging / name
        size = 0
        with destination.open("wb") as handle:
            while chunk := await upload_file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    shutil.rmtree(staging, ignore_errors=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"{name} exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB.",
                    )
                handle.write(chunk)
        staged.append(destination)

    if not staged:
        shutil.rmtree(staging, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No files received.")

    job = app_state.jobs.create(staged)
    asyncio.create_task(_run(job, staged, staging, app_state))
    return {"job": job.as_dict()}


@router.get("/ingest/{job_id}")
def job_status(
    job_id: str,
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> dict:
    job = app_state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job.")
    return job.as_dict()


@router.get("/ingest")
def current_job(
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> dict:
    """The running job if there is one, else the most recent. Lets the panel
    show progress after a page reload or from a second client."""
    job = app_state.jobs.active()
    if job is None:
        recent = app_state.jobs.recent(1)
        job = recent[0] if recent else None
    return {"job": job.as_dict() if job else None}


async def _run(job: Job, paths: list[Path], staging: Path, app_state: AppState) -> None:
    by_name = {f.name: f for f in job.files}

    def on_progress(name: str, result: ingest_core.IngestResult) -> None:
        entry = by_name.get(name)
        if entry is None:
            return
        if name in result.ingested:
            entry.status = "indexed"
        elif any(name == n for n, _ in result.skipped):
            entry.status = "skipped"
            entry.detail = next(d for n, d in result.skipped if n == name)
        elif any(name == n for n, _ in result.failed):
            entry.status = "failed"
            entry.detail = next(d for n, d in result.failed if n == name)

    def on_chunk(done: int, total: int, rate: float, remaining: float) -> None:
        job.phase = "embedding"
        job.chunks_done = done
        job.chunks_total = total
        job.rate = rate
        job.eta_seconds = remaining
        entry = by_name.get(job.current)
        if entry is not None:
            entry.status = "working"
            entry.chunks = done

    try:
        job.phase = "parsing"
        for path in paths:
            job.current = path.name
        result = await ingest_core.ingest_paths(
            paths,
            conn=app_state.conn,
            store=app_state.store,
            sparse=app_state.sparse,
            ollama=app_state.ollama,
            settings=app_state.settings,
            on_progress=on_progress,
            on_chunk_progress=on_chunk,
            on_file_start=lambda name: setattr(job, "current", name),
        )
        job.phase = "done"
        for name in result.ingested:
            row = app_state.conn.execute(
                "SELECT chunk_count, pages FROM documents WHERE filename = ? "
                "ORDER BY id DESC LIMIT 1", (name,)
            ).fetchone()
            entry = by_name.get(name)
            if entry and row:
                entry.chunks = row["chunk_count"]
                entry.pages = row["pages"]
    except OllamaError as exc:
        job.phase = "failed"
        job.error = str(exc)
    except Exception as exc:  # never leave a job stuck in "embedding"
        job.phase = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        import time as _time

        job.finished_at = _time.time()
        job.current = ""
        shutil.rmtree(staging, ignore_errors=True)
