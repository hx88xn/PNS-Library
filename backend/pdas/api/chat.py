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
from ..core.prompts import NO_CONTEXT_REPLY, SYSTEM_PROMPT, build_user_message
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

    # Nothing retrieved: say so directly rather than asking the model to
    # improvise a refusal it might not honour.
    if not hits:
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
            detail = (
                f"{app_state.settings.llm_model} used its entire token budget "
                "reasoning and produced no answer. Raise PDAS_MAX_TOKENS, or use "
                "a model that does not emit reasoning traces."
            )
        else:
            detail = f"{app_state.settings.llm_model} returned an empty response."
        yield _sse("error", {"detail": detail})
        return

    citations = [
        Citation(
            id=chunk["id"],
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
