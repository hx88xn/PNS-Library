"""Grounded chat over the indexed corpus, streamed as Server-Sent Events.

Event sequence:
    event: token     data: {"text": "..."}         zero or more
    event: citations data: {"citations": [...]}    once, after the tokens
    event: done      data: {}                      terminates the stream
    event: error     data: {"detail": "..."}       instead of done, on failure
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ..core.ollama import OllamaError
from ..core.prompts import (
    NO_CONTEXT_PROMPT,
    NO_CONTEXT_REPLY,
    SYSTEM_PROMPT,
    build_user_message,
    index_summary,
)
from ..core.retrieval import retrieve
from ..schemas import ChatRequest, Citation
from ..state import AppState
from .deps import current_user, state

router = APIRouter()

MAX_HISTORY_TURNS = 6
"""Prior turns kept. The context window is spent on retrieved passages, which
are worth more here than a long conversational memory."""


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/chat")
async def chat(
    request: ChatRequest,
    app_state: AppState = Depends(state),
    user: dict = Depends(current_user),
) -> StreamingResponse:
    return StreamingResponse(
        _generate(request, app_state, user["service_no"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # don't let a proxy hold the stream
        },
    )


async def _generate(
    request: ChatRequest, app_state: AppState, service_no: str
) -> AsyncIterator[str]:
    question = request.message.strip()
    if not question:
        yield _sse("error", {"detail": "Ask a question to search the library."})
        return

    try:
        hits = await retrieve(
            query=question,
            conn=app_state.conn,
            store=app_state.store,
            sparse=app_state.sparse,
            ollama=app_state.ollama,
            settings=app_state.settings,
            collection=request.collection,
            limit=app_state.settings.context_chunks,
        )
    except OllamaError as exc:
        yield _sse("error", {"detail": str(exc)})
        return

    # Dense search always returns its k nearest neighbours, however unrelated
    # the query — so "hello" comes back with eight passages and the grounded
    # prompt dutifully recites plating thicknesses at someone saying hello.
    #
    # Treat a result set where NO chunk shares a single content word with the
    # query as a non-question. Sparse retrieval is the discriminator: a real
    # query about this corpus nearly always shares a term with it, while a
    # greeting or an off-subject question shares none.
    lexical_overlap = any(hit.matched_terms for hit in hits)

    # Greetings, "what can you do", or a question the corpus does not touch.
    # Answer as the front desk, on a prompt that has no passages and is
    # forbidden from stating any technical fact. The grounding guarantee is
    # unchanged: nothing substantive is produced without a citation.
    if not hits or not lexical_overlap:
        messages = [
            {"role": "system", "content": NO_CONTEXT_PROMPT},
            {"role": "system", "content": _corpus_summary(app_state)},
            *_trim_history(request.history),
            {"role": "user", "content": question},
        ]

        produced = 0
        try:
            # Hard cap. Nothing said here needs length, and a low ceiling keeps
            # a greeting feeling instant instead of streaming a paragraph.
            async for token in app_state.ollama.chat_stream(messages, max_tokens=256):
                produced += len(token)
                yield _sse("token", {"text": token})
        except OllamaError:
            produced = 0  # fall through to the canned reply

        if produced == 0:
            yield _sse("token", {"text": NO_CONTEXT_REPLY})

        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        _log(app_state, service_no, question, [])
        return

    chunks = [hit.chunk for hit in hits]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_trim_history(request.history),
        {"role": "user", "content": build_user_message(question, chunks)},
    ]

    meta: dict = {}
    try:
        async for token in app_state.ollama.chat_stream(messages, on_meta=meta.update):
            yield _sse("token", {"text": token})
    except OllamaError as exc:
        yield _sse("error", {"detail": str(exc)})
        return

    # A reasoning model can spend its whole budget on `message.thinking` and
    # return no answer. Left alone that shows as an empty bubble, which reads
    # as a broken interface rather than a fixable configuration problem.
    if meta.get("content_chars", 0) == 0:
        if meta.get("thinking_chars", 0) > 0:
            # Deliberately does not suggest raising PDAS_MAX_TOKENS. Thinking
            # and answer draw on one budget (num_predict), and a model that
            # overruns it does not converge if given more: measured on
            # qwen3-vl:4b against this corpus, 2560 tokens produced 9,935
            # characters of deliberation and 6144 produced 21,852 — both with
            # zero answer. The budget is not the fault; the model is.
            detail = (
                f"{app_state.settings.llm_model} spent its whole token budget "
                "reasoning and produced no answer. It ignores the request not "
                "to deliberate, and raising PDAS_MAX_TOKENS will not fix that. "
                "Set PDAS_LLM_MODEL to a model that honours it."
            )
        else:
            detail = f"{app_state.settings.llm_model} returned an empty response."
        yield _sse("error", {"detail": detail})
        return

    citations = [
        Citation(
            id=chunk["id"],
            document_id=chunk.get("document_id"),
            doc=chunk["doc"],
            section=chunk.get("section") or "",
            page=chunk.get("page"),
            revision=chunk.get("revision") or "",
            title=chunk["title"],
        ).model_dump()
        for chunk in chunks
    ]
    yield _sse("citations", {"citations": citations})
    yield _sse("done", {})

    _log(app_state, service_no, question, [c["id"] for c in chunks])


def _corpus_summary(app_state: AppState) -> str:
    """What the library actually holds, so the front desk answers from data."""
    from .chunks import COLLECTION_LABELS

    rows = app_state.conn.execute(
        "SELECT collection, COUNT(*) AS n FROM chunks GROUP BY collection ORDER BY n DESC"
    ).fetchall()
    counts = app_state.conn.execute(
        "SELECT (SELECT COUNT(*) FROM documents WHERE status='indexed') AS d, "
        "       (SELECT COUNT(*) FROM chunks) AS c"
    ).fetchone()

    collections = [
        (COLLECTION_LABELS.get(row["collection"], row["collection"]), row["n"]) for row in rows
    ]
    return index_summary(collections, counts["d"], counts["c"])


def _trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("role") in {"user", "assistant"} and m.get("content")
    ]
    return turns[-MAX_HISTORY_TURNS:]


def _log(app_state: AppState, service_no: str, question: str, chunk_ids: list[str]) -> None:
    app_state.conn.execute(
        "INSERT INTO query_log(service_no, kind, query, chunk_ids, created_at) "
        "VALUES(?, 'chat', ?, ?, ?)",
        (
            service_no,
            question,
            json.dumps(chunk_ids),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    app_state.conn.commit()
