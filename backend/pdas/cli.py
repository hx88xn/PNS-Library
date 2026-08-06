"""Command line: pdas ingest / reindex / adduser / serve / status.

Ingestion runs from here rather than through the web UI. On an air-gapped box
documents arrive as a directory copied off removable media, and a CLI that can
be scripted and logged suits that better than a browser upload.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Optional

import typer

from .config import get_settings
from .core import ingest as ingest_core
from .core.ollama import OllamaError
from .core.security import create_user
from .state import build_state

app = typer.Typer(help="Platform Design Assistance System — Ship Design Office", add_completion=False)


@app.command()
def ingest(
    paths: list[Path] = typer.Argument(..., help="Files or directories to ingest"),
    collection: Optional[str] = typer.Option(
        None, "--collection", "-c", help="Override the auto-assigned collection"
    ),
    classification: str = typer.Option("RESTRICTED", "--classification"),
) -> None:
    """Parse, chunk, embed and index documents."""
    # A path that does not exist used to report "Indexed 0 documents" and exit
    # 0, which reads as "your files had nothing in them". The usual cause is a
    # Windows path under WSL — D:\dir\file.pdf instead of /mnt/d/dir/file.pdf.
    missing = [p for p in paths if not p.exists()]
    if missing:
        typer.secho("Path does not exist:", fg=typer.colors.RED, err=True)
        for path in missing:
            typer.echo(f"  {path}", err=True)
            text = str(path)
            if "\\" in text or (len(text) > 1 and text[1] == ":"):
                drive = text[0].lower()
                converted = text[2:].replace("\\", "/").lstrip("/")
                typer.secho(
                    f"  That is a Windows path. Under WSL, use:\n"
                    f"      /mnt/{drive}/{converted}",
                    fg=typer.colors.YELLOW,
                    err=True,
                )
        raise typer.Exit(code=1)

    state = build_state()

    async def run() -> ingest_core.IngestResult:
        def progress(name: str, result: ingest_core.IngestResult) -> None:
            done = len(result.ingested) + len(result.failed) + len(result.skipped)
            # \r from the chunk line leaves the cursor mid-line; clear it first.
            typer.echo(f"\r\033[K  [{done}] {name}")

        def chunk_progress(done: int, total: int, rate: float, remaining: float) -> None:
            # Overwrite one line rather than scrolling. A 1,100-page document is
            # thousands of batches, and a wall of output hides the summary.
            mins, secs = divmod(int(remaining), 60)
            eta = f"{mins}m{secs:02d}s" if mins else f"{secs}s"
            typer.echo(
                f"\r\033[K      embedding {done}/{total} chunks "
                f"({rate:.1f}/s, ~{eta} left)",
                nl=False,
            )

        return await ingest_core.ingest_paths(
            list(paths),
            conn=state.conn,
            store=state.store,
            sparse=state.sparse,
            ollama=state.ollama,
            settings=state.settings,
            collection_override=collection,
            classification=classification,
            on_progress=progress,
            on_chunk_progress=chunk_progress,
        )

    try:
        result = asyncio.run(run())
    except OllamaError as exc:
        typer.secho(f"\n{exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.echo("")
    typer.secho(
        f"Indexed {len(result.ingested)} document(s), {result.chunks_added} chunks.",
        fg=typer.colors.GREEN,
    )
    if result.skipped:
        typer.echo(f"Skipped {len(result.skipped)}:")
        for name, reason in result.skipped:
            typer.echo(f"  {name}: {reason}")
    if result.failed:
        typer.secho(f"Failed {len(result.failed)}:", fg=typer.colors.YELLOW)
        for name, reason in result.failed:
            typer.echo(f"  {name}: {reason}")
        raise typer.Exit(code=1)


@app.command()
def reindex() -> None:
    """Rebuild the vector index. Required after changing the embedding model."""
    state = build_state()

    async def run() -> int:
        return await ingest_core.reindex(
            conn=state.conn,
            store=state.store,
            sparse=state.sparse,
            ollama=state.ollama,
            settings=state.settings,
        )

    try:
        count = asyncio.run(run())
    except OllamaError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.secho(f"Re-embedded {count} chunks.", fg=typer.colors.GREEN)


@app.command()
def clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation"),
) -> None:
    """Empty the index — every document, chunk and vector. Accounts are kept.

    For starting an ingestion test from a known-empty state. Stored copies of
    the source files go too, so nothing is left half-referenced.
    """
    state = build_state()
    counts = state.conn.execute(
        "SELECT (SELECT COUNT(*) FROM documents) AS d, (SELECT COUNT(*) FROM chunks) AS c"
    ).fetchone()

    if counts["d"] == 0 and counts["c"] == 0:
        typer.echo("Already empty.")
        return

    typer.echo(f"This deletes {counts['d']} document(s) and {counts['c']} chunk(s).")
    typer.echo(f"Accounts and settings are kept. Data dir: {state.settings.data_dir}")
    if not yes:
        typer.confirm("Continue?", abort=True)

    state.conn.execute("DELETE FROM chunks")
    state.conn.execute("DELETE FROM documents")
    state.conn.execute("DELETE FROM meta WHERE key IN ('embed_model','embed_dim','index_size')")
    state.conn.commit()

    # The FAISS file must go too: leaving it would load vectors with no rows to
    # resolve them to, and health would report a size mismatch forever.
    state.settings.index_path.unlink(missing_ok=True)

    removed = 0
    if state.settings.documents_dir.exists():
        for stored in state.settings.documents_dir.iterdir():
            if stored.is_file():
                stored.unlink()
                removed += 1

    typer.secho(
        f"Cleared. Removed {removed} stored file(s) and the vector index.",
        fg=typer.colors.GREEN,
    )
    typer.echo("Restart the service so it reloads an empty index: systemctl restart pdas")


@app.command()
def adduser(
    service_no: str = typer.Argument(..., help="e.g. PN-40218"),
    name: Optional[str] = typer.Option(None, "--name"),
    role: str = typer.Option("user", "--role", help="user | admin"),
) -> None:
    """Create a local account. This is the only way to issue credentials."""
    state = build_state()
    password = typer.prompt("Passphrase", hide_input=True, confirmation_prompt=True)

    if len(password) < 8:
        typer.secho("Passphrase must be at least 8 characters.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    try:
        create_user(state.conn, service_no, password, name, role)
    except sqlite3.IntegrityError:
        typer.secho(f"{service_no.upper()} already exists.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    typer.secho(f"Created {service_no.upper()} ({role}).", fg=typer.colors.GREEN)


@app.command()
def status() -> None:
    """Report what is indexed and whether the models are reachable."""
    state = build_state()

    async def models() -> list[str]:
        try:
            return await state.ollama.list_models()
        except OllamaError as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            return []

    available = asyncio.run(models())
    counts = state.conn.execute(
        "SELECT (SELECT COUNT(*) FROM documents) AS d, (SELECT COUNT(*) FROM chunks) AS c"
    ).fetchone()

    settings = state.settings
    typer.echo(f"Data dir      {settings.data_dir.resolve()}")
    typer.echo(f"Documents     {counts['d']}")
    typer.echo(f"Chunks        {counts['c']}")
    typer.echo(f"Index vectors {state.store.size} (dim {state.store.dim})")
    typer.echo(f"BM25 entries  {state.sparse.size}")
    typer.echo(f"LLM           {settings.llm_model} {_mark(settings.llm_model, available)}")
    typer.echo(f"Embeddings    {settings.embed_model} {_mark(settings.embed_model, available)}")
    if state.index_error:
        typer.secho(f"Index error   {state.index_error}", fg=typer.colors.RED)


@app.command()
def serve(
    host: Optional[str] = typer.Option(None, "--host"),
    port: Optional[int] = typer.Option(None, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Run the API server."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "pdas.main:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


def _mark(name: str, available: list[str]) -> str:
    wanted = name if ":" in name else f"{name}:latest"
    return "✓" if wanted in available else "✗ not pulled"


if __name__ == "__main__":
    app()
