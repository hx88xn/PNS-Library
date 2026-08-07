"""FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, chat, chunks, documents, health, ingest, models, suggestions
from .config import get_settings
from .state import build_state, get_state, set_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state = build_state()
    # A model chosen through the UI outlives the process that chose it.
    models.restore(app_state)
    set_state(app_state)
    yield
    state = get_state()
    await state.ollama.aclose()
    state.conn.close()


app = FastAPI(
    title="PDAS",
    description="Platform Design Assistance System — Ship Design Office",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the PDF viewer downloads whole books to show page one.
    #
    # Cross-origin JavaScript may only read a short safelist of response
    # headers; everything else is invisible unless named here. Accept-Ranges
    # and Content-Range are not on that safelist, so pdf.js — which decides
    # whether to fetch by range purely by looking for Accept-Ranges on its
    # first response — saw nothing, concluded the server had no range support,
    # and fell back to fetching all 35 MB. The server was answering 206
    # correctly the whole time; the answer was simply unreadable.
    #
    # Only bites when the page and the API are on different origins, which is
    # exactly the deployed arrangement (pn.* against pn-be.*).
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(chunks.router, prefix="/api", tags=["chunks"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(suggestions.router, prefix="/api", tags=["chat"])
app.include_router(models.router, prefix="/api", tags=["models"])
