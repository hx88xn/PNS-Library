"""Common types for document parsers.

A parser turns a file into `Block`s — a run of text with a locator that can be
cited. The locator is what lets an answer say "p.55" and be checkable, so
parsers must never invent or approximate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Block:
    text: str
    page: int | None = None
    """1-based page for PDFs; None where the format has no pages."""
    section: str = ""
    """Nearest preceding heading, or a sheet/cell locator."""
    heading_level: int = 0
    """0 = body text, 1..6 = a heading. Drives chunk boundaries."""


@dataclass
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    title: str | None = None
    doc_ref: str | None = None
    """Document or drawing number, if the file declares one."""
    revision: str | None = None
    pages: int | None = None
    kind: str = "text"
    """text | drawing — drawings are indexed as metadata, not prose."""


class ParserError(RuntimeError):
    pass


def suffix_of(path: Path) -> str:
    return path.suffix.lower().lstrip(".")
