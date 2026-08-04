"""Runtime configuration.

Every path and model name is settable through the environment so the same code
runs from a developer laptop and from /opt/pdas on the air-gapped server.
Prefix all environment variables with PDAS_, e.g. PDAS_OLLAMA_HOST.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PDAS_",
        env_file=".env",
        extra="ignore",
    )

    # ── Storage ──────────────────────────────────────────────────────────
    data_dir: Path = Path("var")
    """Holds the SQLite database, the FAISS index and ingested source files."""

    # ── Ollama ───────────────────────────────────────────────────────────
    ollama_host: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3.5:4b"
    embed_model: str = "bge-m3"
    """bge-m3 over mxbai-embed-large: chunks run ~500 tokens and mxbai truncates
    at 512, which would silently drop the tail of most passages. bge-m3 takes
    8192 and degrades gracefully if a non-English document ever appears."""
    ollama_timeout: float = 120.0

    # ── Generation ───────────────────────────────────────────────────────
    num_ctx: int = 16384
    """Context window. Must hold the retrieved passages plus the answer."""
    temperature: float = 0.1
    """Low: this is grounded extraction, not composition."""
    max_tokens: int = 2560
    """Generous on purpose.

    Reasoning models spend part of this budget on `message.thinking` before
    writing a single character of answer, and `think: false` is honoured by
    some model/Ollama combinations and silently ignored by others. Measured on
    qwen3-vl:4b, a trivial prompt burned 831 characters of deliberation and
    returned empty content at a 200-token cap — which surfaces as an assistant
    that replies with nothing at all. Leave headroom for both.
    """

    # ── Retrieval ────────────────────────────────────────────────────────
    dense_k: int = 24
    """Candidates from the vector index before fusion."""
    sparse_k: int = 24
    """Candidates from BM25 before fusion."""
    dense_relative_floor: float = 0.85
    """Keep dense hits scoring at least this fraction of the query's OWN best hit.

    Deliberately relative. Absolute cosine thresholds do not work on this
    corpus: measured against bge-m3, a nonsense query ("what colour should the
    wardroom curtains be") tops out at 0.391 while a precise real one ("A-60")
    tops out at 0.382. Any fixed cutoff either admits the nonsense or discards
    the real query. The shape of each query's own score curve is informative
    even though its absolute level is not.
    """
    rrf_k: int = 60
    """Reciprocal rank fusion constant. 60 is the value from the original paper."""
    context_chunks: int = 8
    """Passages handed to the model. The 4B's headroom is spent here."""

    # ── Chunking ─────────────────────────────────────────────────────────
    chunk_tokens: int = 500
    chunk_overlap_tokens: int = 80

    # ── Auth ─────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-before-deployment"
    jwt_ttl_minutes: int = 720
    """A design session runs all day; 12 hours avoids re-auth mid-review."""

    # ── Server ───────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = ["*"]
    """Electron renderers have an opaque origin, so this stays permissive.
    The network boundary is the air gap and the LAN, not CORS."""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pdas.db"

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index.faiss"

    @property
    def documents_dir(self) -> Path:
        """Copies of ingested source files, so a citation can be opened."""
        return self.data_dir / "documents"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
