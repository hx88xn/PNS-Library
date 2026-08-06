"""Ingestion: parse, chunk, embed, index.

Ingestion quality is the ceiling on the whole system — retrieval cannot recover
what the parser mangled — so failures are recorded per document rather than
aborting the run, and `pdas ingest` reports them at the end.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import time
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from .bm25 import SparseIndex
from .chunking import chunk_blocks
from .ollama import OllamaClient
from .parsers import cad, office, pdf
from .parsers.base import ParsedDocument, ParserError, suffix_of
from .store import VectorStore

SUPPORTED = {"pdf", "docx", "xlsx", "dxf"}
EMBED_BATCH = 32

# Route a document to a collection by what its reference or name says it is.
# Deliberately transparent: an operator can see why a document landed where it
# did, and override with --collection.
COLLECTION_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hyd", re.compile(r"stab|hydro|seakeep|hull|resist|buoyan", re.I)),
    ("str", re.compile(r"struct|scant|strength|weld|plating|frame", re.I)),
    ("prop", re.compile(r"prop|machin|codag|codad|engine|shaft|gearbox", re.I)),
    ("sur", re.compile(r"surviv|damage|dc|shock|signature|nbcd|rcs|citadel", re.I)),
    ("std", re.compile(r"\bnes\b|\biso\b|\bstd\b|standard|rule|spec", re.I)),
    ("nsr", re.compile(r"\bnsr\b|staff|requirement|concept|mission", re.I)),
]


@dataclass
class IngestResult:
    ingested: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    chunks_added: int = 0


def parse_file(path: Path) -> ParsedDocument:
    fmt = suffix_of(path)
    if fmt == "pdf":
        return pdf.parse(path)
    if fmt == "docx":
        return office.parse_docx(path)
    if fmt == "xlsx":
        return office.parse_xlsx(path)
    if fmt == "dxf":
        return cad.parse(path)
    if fmt == "dwg":
        raise ParserError(
            "DWG cannot be read directly. Convert to DXF or plot to PDF first."
        )
    raise ParserError(f"Unsupported format: .{fmt}")


def classify(doc_ref: str | None, title: str | None, filename: str) -> str:
    haystack = " ".join(filter(None, (doc_ref, title, filename)))
    for collection, pattern in COLLECTION_RULES:
        if pattern.search(haystack):
            return collection
    return "uncategorised"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def collect_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if suffix_of(root) in SUPPORTED | {"dwg"} else []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and suffix_of(path) in SUPPORTED | {"dwg"}
    )


async def ingest_paths(
    paths: list[Path],
    *,
    conn: sqlite3.Connection,
    store: VectorStore,
    sparse: SparseIndex,
    ollama: OllamaClient,
    settings: Settings,
    collection_override: str | None = None,
    classification: str = "RESTRICTED",
    on_progress=None,
    on_chunk_progress=None,
    on_file_start=None,
) -> IngestResult:
    result = IngestResult()

    files: list[Path] = []
    for path in paths:
        files.extend(collect_files(path))

    for path in files:
        if on_file_start:
            on_file_start(path.name)
        try:
            added = await _ingest_one(
                path,
                conn=conn,
                store=store,
                ollama=ollama,
                settings=settings,
                collection_override=collection_override,
                classification=classification,
                on_chunk_progress=on_chunk_progress,
            )
        except _AlreadyIngested as exc:
            result.skipped.append((path.name, str(exc)))
        except Exception as exc:
            # One bad file must not abandon the rest of the run. Failures are
            # recorded per document and reported at the end.
            conn.rollback()
            result.failed.append((path.name, str(exc)))
            _record_failure(conn, path, str(exc))
        else:
            result.ingested.append(path.name)
            result.chunks_added += added

        if on_progress:
            on_progress(path.name, result)

    if result.chunks_added:
        store.save(conn, settings.embed_model)
        sparse.build(conn)

    return result


class _AlreadyIngested(RuntimeError):
    pass


async def _ingest_one(
    path: Path,
    *,
    conn: sqlite3.Connection,
    store: VectorStore,
    ollama: OllamaClient,
    settings: Settings,
    collection_override: str | None,
    classification: str,
    on_chunk_progress=None,
) -> int:
    digest = sha256_of(path)
    existing = conn.execute(
        "SELECT id, status FROM documents WHERE sha256 = ?", (digest,)
    ).fetchone()
    if existing and existing["status"] == "indexed":
        raise _AlreadyIngested("already indexed (identical content)")

    parsed = parse_file(path)
    chunks = chunk_blocks(
        parsed.blocks,
        target_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        kind=parsed.kind,
    )
    if not chunks:
        raise ParserError("No extractable text — is this a scanned document?")

    collection = collection_override or classify(parsed.doc_ref, parsed.title, path.name)
    doc_ref = parsed.doc_ref or path.stem
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    stored = settings.documents_dir / f"{digest[:16]}{path.suffix.lower()}"
    if not stored.exists():
        shutil.copy2(path, stored)

    conn.execute(
        "INSERT INTO documents(filename, stored_path, sha256, format, doc_ref, title, "
        "revision, collection, classification, pages, chunk_count, status, ingested_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?) "
        "ON CONFLICT(sha256) DO UPDATE SET status='pending', error=NULL",
        (
            path.name,
            str(stored),
            digest,
            suffix_of(path),
            doc_ref,
            parsed.title,
            parsed.revision,
            collection,
            classification,
            parsed.pages,
            now,
        ),
    )
    # lastrowid is unreliable through ON CONFLICT DO UPDATE; look it up.
    document_id = conn.execute(
        "SELECT id FROM documents WHERE sha256 = ?", (digest,)
    ).fetchone()["id"]

    # Re-ingesting replaces the previous chunks for this document.
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

    # Embedding dominates the runtime — measured at ~7 chunks/sec on a GPU and
    # 1–2 on CPU, so a 1,100-page document is tens of minutes. Report progress
    # per batch; without it a large file looks indistinguishable from a hang.
    texts = [chunk.text for chunk in chunks]
    vectors: list[list[float]] = []
    started = time.monotonic()

    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(await ollama.embed(texts[start : start + EMBED_BATCH]))
        if on_chunk_progress:
            done = min(start + EMBED_BATCH, len(texts))
            elapsed = time.monotonic() - started
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (len(texts) - done) / rate if rate > 0 else 0
            on_chunk_progress(done, len(texts), rate, remaining)

    ordinals = store.add(vectors)

    for chunk, vector_ordinal in zip(chunks, ordinals):
        conn.execute(
            "INSERT INTO chunks(id, document_id, ordinal, vector_ordinal, doc, title, "
            "section, page, revision, collection, classification, tags, text, token_count) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"{digest[:8]}-{chunk.ordinal:04d}",
                document_id,
                chunk.ordinal,
                vector_ordinal,
                doc_ref,
                _chunk_title(parsed.title, chunk.section),
                chunk.section,
                chunk.page,
                parsed.revision,
                collection,
                classification,
                json.dumps(_tags(chunk.text)),
                chunk.text,
                chunk.token_count,
            ),
        )

    conn.execute(
        "UPDATE documents SET chunk_count = ?, status = 'indexed', error = NULL WHERE id = ?",
        (len(chunks), document_id),
    )
    conn.commit()
    return len(chunks)


def _chunk_title(document_title: str | None, section: str) -> str:
    if section and document_title and section != document_title:
        return f"{document_title} — {section}"[:200]
    return (section or document_title or "Untitled")[:200]


_TAG_PATTERNS = [
    ("stability", re.compile(r"\bstabilit|righting arm|\bgz\b|metacentr", re.I)),
    ("damage control", re.compile(r"damage control|flooding|watertight|subdivision", re.I)),
    ("scantlings", re.compile(r"scantling|plating|section modulus|stiffener", re.I)),
    ("propulsion", re.compile(r"propuls|propeller|gearbox|shaft|gas turbine", re.I)),
    ("signature", re.compile(r"radar cross|infrared|signature|acoustic", re.I)),
    ("seakeeping", re.compile(r"seakeep|roll|pitch|sea state|motion", re.I)),
    ("structure", re.compile(r"bulkhead|frame|girder|deck|hull girder", re.I)),
    ("corrosion", re.compile(r"corros|cathodic|coating|anode", re.I)),
]


def _tags(text: str) -> list[str]:
    """Topic tags for the chunk card. Derived, not authored — they only need to
    be good enough to click as a filter."""
    return [tag for tag, pattern in _TAG_PATTERNS if pattern.search(text)][:4]


def _record_failure(conn: sqlite3.Connection, path: Path, error: str) -> None:
    conn.execute(
        "INSERT INTO documents(filename, stored_path, sha256, format, collection, "
        "classification, status, error, ingested_at) "
        "VALUES(?, '', ?, ?, 'uncategorised', 'UNCLASSIFIED', 'failed', ?, ?) "
        "ON CONFLICT(sha256) DO UPDATE SET status='failed', error=excluded.error",
        (
            path.name,
            f"failed:{path.name}",
            suffix_of(path),
            error[:500],
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


async def reindex(
    *,
    conn: sqlite3.Connection,
    store: VectorStore,
    sparse: SparseIndex,
    ollama: OllamaClient,
    settings: Settings,
) -> int:
    """Rebuild the vector index from stored chunk text.

    Needed after changing the embedding model — vectors from the old model are
    meaningless in the new model's space, and searching across the two returns
    confident nonsense.
    """
    rows = conn.execute("SELECT id, text FROM chunks ORDER BY rowid").fetchall()
    if not rows:
        return 0

    # Detect the dimension from the model itself rather than hardcoding it, so
    # swapping bge-m3 for something else needs no code change.
    probe = await ollama.embed([rows[0]["text"]])
    store.reset(len(probe[0]))

    total = 0
    for start in range(0, len(rows), EMBED_BATCH):
        batch = rows[start : start + EMBED_BATCH]
        vectors = await ollama.embed([row["text"] for row in batch])
        ordinals = store.add(vectors)
        for row, ordinal in zip(batch, ordinals):
            conn.execute(
                "UPDATE chunks SET vector_ordinal = ? WHERE id = ?", (ordinal, row["id"])
            )
        total += len(batch)

    conn.commit()
    store.save(conn, settings.embed_model)
    sparse.build(conn)
    return total
