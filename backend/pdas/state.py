"""Process-wide singletons, wired at startup and shared by every request."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .config import Settings, get_settings
from .core.bm25 import SparseIndex
from .core.ollama import OllamaClient
from .core.store import VectorStore
from .db import connect, init_db


@dataclass
class AppState:
    settings: Settings
    conn: sqlite3.Connection
    ollama: OllamaClient
    store: VectorStore
    sparse: SparseIndex
    index_error: str | None = field(default=None)
    """Set when the index refuses to load — surfaced by /api/health rather than
    crashing the server, so an operator can see why and run a reindex."""


_state: AppState | None = None


def build_state(settings: Settings | None = None) -> AppState:
    settings = settings or get_settings()
    settings.ensure_dirs()
    init_db(settings.db_path)

    conn = connect(settings.db_path)
    store = VectorStore(settings.index_path)
    sparse = SparseIndex()

    error: str | None = None
    try:
        store.load(conn, settings.embed_model)
    except Exception as exc:  # IndexMismatch, or a corrupt index file
        error = str(exc)

    sparse.build(conn)

    return AppState(
        settings=settings,
        conn=conn,
        ollama=OllamaClient(settings),
        store=store,
        sparse=sparse,
        index_error=error,
    )


def set_state(state: AppState) -> None:
    global _state
    _state = state


def get_state() -> AppState:
    if _state is None:
        raise RuntimeError("Application state is not initialised")
    return _state
