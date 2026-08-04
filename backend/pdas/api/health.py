"""Health and readiness.

Deliberately verbose. On an air-gapped box with no logs to tail remotely, this
endpoint is the whole diagnostic surface: it says which model is missing, or
that the index needs rebuilding, in words an operator can act on.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..core.ollama import OllamaError
from ..schemas import HealthResponse
from ..state import get_state

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    state = get_state()
    settings = state.settings
    problems: list[str] = []

    reachable = False
    llm_present = False
    embed_present = False

    try:
        available = set(await state.ollama.list_models())
        reachable = True

        def present(name: str) -> bool:
            return (name if ":" in name else f"{name}:latest") in available

        llm_present = present(settings.llm_model)
        embed_present = present(settings.embed_model)

        if not llm_present:
            problems.append(
                f"Model '{settings.llm_model}' is not loaded. "
                f"Run: ollama pull {settings.llm_model}"
            )
        if not embed_present:
            problems.append(
                f"Embedding model '{settings.embed_model}' is not loaded. "
                f"Run: ollama pull {settings.embed_model}"
            )
    except OllamaError as exc:
        problems.append(str(exc))

    counts = state.conn.execute(
        "SELECT (SELECT COUNT(*) FROM chunks)    AS chunks, "
        "       (SELECT COUNT(*) FROM documents) AS documents"
    ).fetchone()

    if state.index_error:
        problems.append(state.index_error)

    if counts["chunks"] == 0:
        problems.append("No documents ingested. Run: pdas ingest <path>")
    elif state.store.size != counts["chunks"]:
        problems.append(
            f"Index holds {state.store.size} vectors but the database has "
            f"{counts['chunks']} chunks. Run: pdas reindex"
        )

    return HealthResponse(
        status="ok" if not problems else "degraded",
        ollama_reachable=reachable,
        llm_model=settings.llm_model,
        llm_present=llm_present,
        embed_model=settings.embed_model,
        embed_present=embed_present,
        index_size=state.store.size,
        chunk_count=counts["chunks"],
        document_count=counts["documents"],
        index_error=state.index_error,
        problems=problems,
    )
