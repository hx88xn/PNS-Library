"""SQLite storage.

Holds document records, chunk text and metadata, users, and a query log.
Vectors live in the FAISS index alongside; `chunks.vector_ordinal` is the row's
position in that index, which is how a search result gets back to its text.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    filename      TEXT    NOT NULL,
    stored_path   TEXT    NOT NULL,
    sha256        TEXT    NOT NULL UNIQUE,
    format        TEXT    NOT NULL,          -- pdf | docx | xlsx | dxf
    doc_ref       TEXT,                      -- e.g. SDO/NA/STAB-014
    title         TEXT,
    revision      TEXT,
    collection    TEXT    NOT NULL DEFAULT 'uncategorised',
    classification TEXT   NOT NULL DEFAULT 'UNCLASSIFIED',
    pages         INTEGER,
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    status        TEXT    NOT NULL DEFAULT 'pending',  -- pending|indexed|failed
    error         TEXT,
    ingested_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id             TEXT    PRIMARY KEY,      -- stable, e.g. C-0417
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal        INTEGER NOT NULL,         -- position within the document
    vector_ordinal INTEGER,                  -- row in the FAISS index
    doc            TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    section        TEXT,
    page           INTEGER,
    revision       TEXT,
    collection     TEXT    NOT NULL,
    classification TEXT    NOT NULL,
    tags           TEXT    NOT NULL DEFAULT '[]',   -- JSON array
    text           TEXT    NOT NULL,
    token_count    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_document   ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_vector ON chunks(vector_ordinal)
    WHERE vector_ordinal IS NOT NULL;

-- The source's own text, as the parsing library saw it, before chunking.
-- Kept so occurrence counts can be reported against the DOCUMENT rather than
-- the index: chunks overlap by design, so counting a term across chunks
-- overstates the document by around 20 percent -- and that error runs in the
-- reassuring direction for anyone checking whether a file was fully ingested.
CREATE TABLE IF NOT EXISTS document_text (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    text        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    service_no    TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    display_name  TEXT,
    role          TEXT    NOT NULL DEFAULT 'user',   -- user | admin
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL
);

-- Kept for accreditation: who asked what, and which passages were served.
CREATE TABLE IF NOT EXISTS query_log (
    id          INTEGER PRIMARY KEY,
    service_no  TEXT,
    kind        TEXT    NOT NULL,            -- search | chat
    query       TEXT    NOT NULL,
    chunk_ids   TEXT    NOT NULL DEFAULT '[]',
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);

-- Index metadata: embedding model and dimension the FAISS index was built with.
-- A mismatch here means the index must be rebuilt, and we refuse to serve
-- against it rather than return silently wrong neighbours.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── meta helpers ─────────────────────────────────────────────────────────


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def row_to_chunk(row: sqlite3.Row) -> dict[str, Any]:
    """Map a chunks row to the shape the frontend already renders."""
    return {
        "id": row["id"],
        "doc": row["doc"],
        "title": row["title"],
        "section": row["section"] or "",
        "page": row["page"],
        "revision": row["revision"] or "",
        "collection": row["collection"],
        "classification": row["classification"],
        "tags": json.loads(row["tags"]),
        "text": row["text"],
    }
