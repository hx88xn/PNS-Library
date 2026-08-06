"""In-process ingest jobs.

Ingesting a 1,100-page rulebook takes tens of minutes, so the upload request
cannot wait for it. A job runs in the background and the client polls its
progress.

Deliberately in-memory rather than a queue table: a single-node air-gapped
deployment has no second worker to coordinate with, and a restart mid-ingest
should abandon the job rather than resume something half-indexed. Documents
that completed are already in SQLite; the rest can be re-uploaded.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Phase = Literal["queued", "parsing", "embedding", "indexing", "done", "failed"]


@dataclass
class FileProgress:
    name: str
    status: Literal["pending", "working", "indexed", "skipped", "failed"] = "pending"
    chunks: int = 0
    pages: int | None = None
    detail: str = ""


@dataclass
class Job:
    id: str
    files: list[FileProgress]
    phase: Phase = "queued"
    current: str = ""
    chunks_done: int = 0
    chunks_total: int = 0
    rate: float = 0.0
    eta_seconds: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        elapsed = (self.finished_at or time.time()) - self.started_at
        return {
            "id": self.id,
            "phase": self.phase,
            "current": self.current,
            "chunks_done": self.chunks_done,
            "chunks_total": self.chunks_total,
            "rate": round(self.rate, 1),
            "eta_seconds": round(self.eta_seconds),
            "elapsed_seconds": round(elapsed),
            "error": self.error,
            "files": [
                {
                    "name": f.name,
                    "status": f.status,
                    "chunks": f.chunks,
                    "pages": f.pages,
                    "detail": f.detail,
                }
                for f in self.files
            ],
            "totals": {
                "indexed": sum(1 for f in self.files if f.status == "indexed"),
                "skipped": sum(1 for f in self.files if f.status == "skipped"),
                "failed": sum(1 for f in self.files if f.status == "failed"),
                "chunks": sum(f.chunks for f in self.files),
            },
        }


class JobStore:
    """Holds recent jobs. Bounded, because this process is long-lived."""

    MAX_JOBS = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []

    def create(self, paths: list[Path]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12],
                  files=[FileProgress(name=p.name) for p in paths])
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self.MAX_JOBS:
                self._jobs.pop(self._order.pop(0), None)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def active(self) -> Job | None:
        """The running job, if any. Only one runs at a time — concurrent
        ingests would contend for the same embedding model and the same FAISS
        index, and neither benefits from the parallelism."""
        with self._lock:
            for job_id in reversed(self._order):
                job = self._jobs[job_id]
                if job.phase not in ("done", "failed"):
                    return job
        return None

    def recent(self, limit: int = 5) -> list[Job]:
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order[-limit:])]
