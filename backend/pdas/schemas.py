"""Wire formats.

`Chunk` matches the shape the Electron frontend already renders, so the card
and citation markup needed no changes when the dummy data was removed.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str
    document_id: int | None = None
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
    """Ranked results returned — capped by the retrieval pool, not a corpus count."""
    corpus_matches: int | None = None
    """Chunks anywhere in the index literally containing every query term.
    None when the query has no literal terms. Distinguishing this from `total`
    stops the UI implying the ranked list is exhaustive."""
    occurrences: int | None = None
    """Times the query appears in the SOURCE documents, not the chunks.
    Chunks overlap, so counting across them overstates the document by ~20%.
    None when any indexed document predates source-text capture."""
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
    document_id: int | None = None
    """Which document to open when the citation is clicked. Nullable because a
    chunk ingested before this was recorded has no document row to point at."""
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


class SuggestionResponse(BaseModel):
    suggestions: list[str]
    """Opening questions written from the indexed corpus, each verified to
    retrieve. Empty when nothing is indexed or none survived verification —
    the chat screen shows no openers rather than invented ones."""


class ModelInfo(BaseModel):
    name: str
    size: int | None = None
    """Bytes on disk. Not VRAM: a quantised model expands once loaded, and the
    KV cache is on top of that."""
    parameter_size: str | None = None
    quantization: str | None = None
    loaded: bool = False
    """Resident in VRAM right now, as opposed to merely present on disk."""


class ModelListResponse(BaseModel):
    current: str
    embed_model: str
    available: list[ModelInfo]
    busy: bool = False
    """A switch is in progress. The client disables the selector rather than
    letting a second request queue behind the first."""


class ModelSelectRequest(BaseModel):
    name: str
