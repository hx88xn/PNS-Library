"""FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, chat, chunks, documents, health, ingest, suggestions
from .config import get_settings
from .state import build_state, get_state, set_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    set_state(build_state())
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
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(chunks.router, prefix="/api", tags=["chunks"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(suggestions.router, prefix="/api", tags=["chat"])
