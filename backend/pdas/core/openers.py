"""Opening questions for the empty chat screen, written from the real corpus.

The four suggestions used to be hard-coded, which made them a lie: they asked
about stability margins and frame spacing whether or not a single stability
document had ever been ingested. Clicking one on a fresh index produced a
refusal, which is the worst possible first impression — the system looks broken
when it is in fact behaving correctly.

So they are generated. Passages are sampled across the indexed documents, the
model is asked for questions those passages answer, and **every candidate is
then run through the real retrieval path**. A suggestion that does not retrieve
its own subject is discarded rather than offered: the one guarantee worth making
about an opener is that clicking it produces an answer.

The result is cached against a corpus fingerprint, so this costs one generation
per ingest, not one per visit.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

from ..config import Settings
from .bm25 import SparseIndex, tokenize
from .ollama import OllamaClient, OllamaError
from .retrieval import retrieve
from .store import VectorStore

WANTED = 4
"""What the chat screen shows. Asking for more and filtering down is deliberate
— see CANDIDATES."""

CANDIDATES = 7
"""Questions requested from the model. Verification rejects some, and a second
generation round-trip to top up would double the cost of a cache miss."""

SAMPLE_PASSAGES = 6
"""Passages put in front of the model. Enough for variety across documents,
short of crowding out the instruction."""

PASSAGE_CHARS = 700
MAX_PER_DOC = 2
"""Spread the sample. Without this a 9,000-chunk document produces four
questions about itself and the rest of the library goes unmentioned."""

MIN_LEN, MAX_LEN = 25, 110
"""Openers are buttons. Longer than this and they wrap to three lines."""

MIN_TERM_COVERAGE = 0.7
"""Fraction of a question's content words that must appear in the passages
retrieved for it. Tuned on this corpus: real questions land at 0.8-1.0, while
plausible-sounding questions about subjects the library does not hold fall well
below — their distinguishing nouns are exactly the words that go missing."""

PROMPT = """\
You write opening questions for a warship design reference library.

Below are passages drawn from the documents currently indexed. Write {n} \
questions that these passages answer.

Rules:
- Each question must be answerable from the passages above. Do not invent a \
subject the passages do not cover.
- Use the documents' own vocabulary — the exact terms, codes and designations \
they use.
- Each on its own line. No numbering, no bullets, no preamble, no commentary.
- One sentence each, under {max_len} characters, beginning with a question \
word (What, Which, How, When) and ending in a question mark.
- Ask about different subjects; do not write {n} questions about one table.

Passages:

{passages}"""


async def generate(
    *,
    conn: sqlite3.Connection,
    store: VectorStore,
    sparse: SparseIndex,
    ollama: OllamaClient,
    settings: Settings,
    collection: str = "all",
) -> list[str]:
    """Suggestions for this collection, from cache when the corpus is unchanged.

    Returns fewer than WANTED — including none at all — rather than padding with
    invented questions. An empty opener list is a fair report of an empty or
    unverifiable index.
    """
    fingerprint = _fingerprint(conn, collection)
    if fingerprint is None:  # nothing indexed
        return []

    cached = _read_cache(conn, collection, fingerprint)
    if cached is not None:
        return cached

    passages = _sample(conn, collection)
    if not passages:
        return []

    try:
        raw = await _ask(ollama, settings, passages)
    except OllamaError:
        return []  # the chat screen simply shows no openers

    candidates = _parse(raw)
    if not candidates:
        # Observed on a 4B: the whole budget goes to deliberation and the answer
        # comes back empty. It is intermittent, so one more attempt is worth
        # more than an empty screen until the next ingest.
        try:
            candidates = _parse(await _ask(ollama, settings, passages))
        except OllamaError:
            return []

    questions = await _verify(
        candidates,
        conn=conn,
        store=store,
        sparse=sparse,
        ollama=ollama,
        settings=settings,
        collection=collection,
    )

    # Only a non-empty set is cached. An empty one usually means the model or
    # the embedder was briefly unavailable, and caching that would keep the
    # screen bare until the next ingest.
    if questions:
        _write_cache(conn, collection, fingerprint, questions)
    return questions


# ── corpus sampling ──────────────────────────────────────────────────────


def _fingerprint(conn: sqlite3.Connection, collection: str) -> str | None:
    """Identifies the corpus state. Changes when chunks are added or removed."""
    where, params = ("", [])
    if collection != "all":
        where, params = ("WHERE collection = ?", [collection])

    row = conn.execute(
        f"SELECT COUNT(*) AS n, COALESCE(MAX(rowid), 0) AS hi FROM chunks {where}",
        params,
    ).fetchone()

    return f"{row['n']}:{row['hi']}" if row["n"] else None


def _sample(conn: sqlite3.Connection, collection: str) -> list[sqlite3.Row]:
    """A spread of substantial passages across the indexed documents."""
    where = "WHERE length(text) > 400"
    params: list = []
    if collection != "all":
        where += " AND collection = ?"
        params.append(collection)

    rows = conn.execute(
        f"SELECT doc, section, page, text FROM chunks {where} "
        "ORDER BY RANDOM() LIMIT ?",
        [*params, SAMPLE_PASSAGES * 6],
    ).fetchall()

    picked: list[sqlite3.Row] = []
    per_doc: dict[str, int] = {}
    for row in rows:
        if per_doc.get(row["doc"], 0) >= MAX_PER_DOC:
            continue
        per_doc[row["doc"]] = per_doc.get(row["doc"], 0) + 1
        picked.append(row)
        if len(picked) == SAMPLE_PASSAGES:
            break

    return picked


def _format(rows: list[sqlite3.Row]) -> str:
    parts = []
    for i, row in enumerate(rows, 1):
        where = row["doc"]
        if row["section"]:
            where += f" — {row['section']}"
        if row["page"] is not None:
            where += f" (p. {row['page']})"
        parts.append(f"[{i}] {where}\n{row['text'][:PASSAGE_CHARS].strip()}")
    return "\n\n".join(parts)


# ── generation ───────────────────────────────────────────────────────────


async def _ask(ollama: OllamaClient, settings: Settings, rows: list[sqlite3.Row]) -> str:
    prompt = PROMPT.format(n=CANDIDATES, max_len=MAX_LEN, passages=_format(rows))

    out: list[str] = []
    async for token in ollama.chat_stream(
        [{"role": "user", "content": prompt}],
        # Some variety across regenerations, well short of drifting off-corpus.
        temperature=0.6,
        # The full budget, not a small one sized to seven short questions.
        # Reasoning models spend it on `message.thinking` first: measured on
        # qwen3-vl:4b, a 512-token cap produced 2,487 characters of
        # deliberation and zero characters of answer.
        max_tokens=None,
    ):
        out.append(token)

    return "".join(out)


_LEAD = re.compile(r'^\s*(?:[-*•]|\d+[.)])?\s*["“]?')
_TRAIL = re.compile(r'["”]?\s*$')


def _parse(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []

    for line in raw.splitlines():
        question = _TRAIL.sub("", _LEAD.sub("", line)).strip()

        # A question mark is the cheap test for "this is a question and not the
        # model's preamble about what it is doing".
        if not question.endswith("?") or not (MIN_LEN <= len(question) <= MAX_LEN):
            continue

        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(question)

    return out


# ── verification ─────────────────────────────────────────────────────────


async def _verify(
    candidates: list[str],
    *,
    conn: sqlite3.Connection,
    store: VectorStore,
    sparse: SparseIndex,
    ollama: OllamaClient,
    settings: Settings,
    collection: str,
) -> list[str]:
    """Keep only the questions the retriever can actually answer.

    The bar is deliberately higher than the one /api/chat uses to choose between
    a grounded answer and the front desk. That one asks for a single shared
    term, which is enough to route a user's own question but far too loose to
    vouch for one we are about to put on a button: "What is the galley
    ventilation rate for a cruise liner?" shares *ventilation* and *rate* with
    this corpus, retrieves passages, and is then correctly refused — a refusal
    the user did not ask for and cannot explain.

    So the test is term coverage: most of the question's content words must
    actually appear in the passages retrieved for it. A question whose subject
    is absent fails on the words that name that subject.
    """
    kept: list[str] = []

    for question in candidates:
        if len(kept) == WANTED:
            break

        terms = {t for t in tokenize(question) if len(t) > 1}
        if not terms:
            continue

        try:
            hits = await retrieve(
                query=question,
                conn=conn,
                store=store,
                sparse=sparse,
                ollama=ollama,
                settings=settings,
                collection=collection,
                limit=5,
            )
        except OllamaError:
            break

        found: set[str] = set()
        for hit in hits:
            found.update(hit.matched_terms)

        if len(found) / len(terms) >= MIN_TERM_COVERAGE:
            kept.append(question)

    return kept


# ── cache ────────────────────────────────────────────────────────────────


def _read_cache(
    conn: sqlite3.Connection, collection: str, fingerprint: str
) -> list[str] | None:
    row = conn.execute(
        "SELECT questions FROM suggestions WHERE collection = ? AND fingerprint = ?",
        (collection, fingerprint),
    ).fetchone()
    if row is None:
        return None

    try:
        return json.loads(row["questions"])
    except json.JSONDecodeError:
        return None


def _write_cache(
    conn: sqlite3.Connection, collection: str, fingerprint: str, questions: list[str]
) -> None:
    conn.execute(
        "INSERT INTO suggestions(collection, fingerprint, questions, created_at) "
        "VALUES(?, ?, ?, ?) ON CONFLICT(collection) DO UPDATE SET "
        "fingerprint = excluded.fingerprint, questions = excluded.questions, "
        "created_at = excluded.created_at",
        (
            collection,
            fingerprint,
            json.dumps(questions),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
