"""Wire formats.

`Chunk` matches the shape the Electron frontend already renders, so the card
and citation markup needed no changes when the dummy data was removed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str
    doc: str
    title: str
    section: str = ""
    page: int | None = None
    revision: str = ""
    collection: str
    classification: str
    tags: list[str] = Field(default_factory=list)
    text: str


class SearchHit(BaseModel):
    chunk: Chunk
    relevance: float = Field(ge=0.0, le=1.0)
    matched_terms: list[str] = Field(default_factory=list)
    """Terms the client marks up. Highlighting stays client-side so the server
    never has to know how the text is rendered."""


class SearchResponse(BaseModel):
    results: list[SearchHit]
    total: int
    query: str


class ChunkListResponse(BaseModel):
    results: list[Chunk]
    total: int
    offset: int
    limit: int


class Collection(BaseModel):
    id: str
    label: str
    count: int


class ChatRequest(BaseModel):
    message: str
    collection: str = "all"
    history: list[dict[str, str]] = Field(default_factory=list)
    """Prior turns as {role, content}. Trimmed server-side to fit the window."""


class Citation(BaseModel):
    id: str
    doc: str
    section: str
    page: int | None
    revision: str
    title: str


class DocumentRecord(BaseModel):
    id: int
    filename: str
    format: str
    doc_ref: str | None
    title: str | None
    revision: str | None
    collection: str
    classification: str
    pages: int | None
    chunk_count: int
    status: str
    error: str | None
    ingested_at: str


class LoginRequest(BaseModel):
    service_no: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    service_no: str
    display_name: str | None = None
    role: str


class HealthResponse(BaseModel):
    status: str
    """ok | degraded — degraded means the API is up but cannot answer."""
    ollama_reachable: bool
    llm_model: str
    llm_present: bool
    embed_model: str
    embed_present: bool
    index_size: int
    chunk_count: int
    document_count: int
    index_error: str | None = None
    problems: list[str] = Field(default_factory=list)
