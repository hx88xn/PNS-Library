"""Turn parsed blocks into retrievable chunks.

Boundaries follow the document's own structure: a chunk never spans a heading,
because a passage that straddles two clauses cites neither correctly. Within a
section, blocks accumulate to a token budget with an overlap so a criterion
split across the boundary is still findable from both sides.

Token counts are approximated at 4 characters per token. Precise counting would
mean shipping a tokenizer for a model that may be swapped; the budget only
needs to be roughly right, and erring small is safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parsers.base import Block

CHARS_PER_TOKEN = 4

MIN_CHUNK_CHARS = 160
"""Below this a chunk is a fragment, not a passage.

Two consecutive headings ("SECTION 2" then "Hull Structural Design") used to
emit a 9-character chunk carrying no information. Retrieved, it tells the model
nothing; embedded, it is a near-duplicate of every other heading in the
document and pollutes the dense index. Fragments are merged forward into the
passage they introduce.
"""


@dataclass
class Chunk:
    text: str
    section: str
    page: int | None
    ordinal: int
    token_count: int


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_blocks(
    blocks: list[Block],
    *,
    target_tokens: int = 500,
    overlap_tokens: int = 80,
    kind: str = "text",
) -> list[Chunk]:
    if not blocks:
        return []

    # A drawing is a record, not prose: one chunk per block keeps the title
    # block and each layer independently retrievable.
    if kind == "drawing":
        return [
            Chunk(
                text=block.text,
                section=block.section,
                page=block.page,
                ordinal=index,
                token_count=estimate_tokens(block.text),
            )
            for index, block in enumerate(block for block in blocks if block.text.strip())
        ]

    chunks: list[Chunk] = []
    buffer: list[Block] = []
    buffer_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens, ordinal
        if not buffer:
            return
        text = _join(buffer)
        if text.strip():
            chunks.append(
                Chunk(
                    text=text,
                    section=buffer[0].section,
                    page=buffer[0].page,
                    ordinal=ordinal,
                    token_count=estimate_tokens(text),
                )
            )
            ordinal += 1
        buffer, buffer_tokens = _carry_over(buffer, overlap_tokens)

    for block in blocks:
        tokens = estimate_tokens(block.text)

        # A heading starts a new chunk, and leads it.
        if block.heading_level:
            flush()
            buffer, buffer_tokens = [], 0

        # A single block over budget becomes its own chunk, split on sentences.
        if tokens > target_tokens:
            flush()
            buffer, buffer_tokens = [], 0
            for piece in _split_long(block, target_tokens):
                chunks.append(
                    Chunk(
                        text=piece,
                        section=block.section,
                        page=block.page,
                        ordinal=ordinal,
                        token_count=estimate_tokens(piece),
                    )
                )
                ordinal += 1
            continue

        if buffer_tokens + tokens > target_tokens:
            flush()

        buffer.append(block)
        buffer_tokens += tokens

    # Final flush without carrying overlap forward.
    if buffer:
        text = _join(buffer)
        if text.strip():
            chunks.append(
                Chunk(
                    text=text,
                    section=buffer[0].section,
                    page=buffer[0].page,
                    ordinal=ordinal,
                    token_count=estimate_tokens(text),
                )
            )

    return _merge_fragments(chunks)


def _merge_fragments(chunks: list[Chunk]) -> list[Chunk]:
    """Fold sub-threshold chunks into the passage they introduce.

    A heading split from its body is worse than useless: it embeds to something
    close to every other heading in the document, so it competes for retrieval
    slots while carrying no answer.
    """
    if not chunks:
        return chunks

    merged: list[Chunk] = []
    carry: Chunk | None = None

    for chunk in chunks:
        if carry is not None:
            chunk = Chunk(
                text=f"{carry.text}\n{chunk.text}",
                # Keep the heading's own section and page: it is the more
                # precise locator, and it is what a citation should point at.
                section=carry.section or chunk.section,
                page=carry.page if carry.page is not None else chunk.page,
                ordinal=chunk.ordinal,
                token_count=estimate_tokens(f"{carry.text}\n{chunk.text}"),
            )
            carry = None

        if len(chunk.text) < MIN_CHUNK_CHARS:
            carry = chunk
            continue

        merged.append(chunk)

    # A trailing fragment has nothing to merge into; append it to the previous
    # chunk rather than dropping content.
    if carry is not None:
        if merged:
            last = merged[-1]
            merged[-1] = Chunk(
                text=f"{last.text}\n{carry.text}",
                section=last.section,
                page=last.page,
                ordinal=last.ordinal,
                token_count=estimate_tokens(f"{last.text}\n{carry.text}"),
            )
        else:
            merged.append(carry)

    return [
        Chunk(
            text=c.text, section=c.section, page=c.page,
            ordinal=i, token_count=c.token_count,
        )
        for i, c in enumerate(merged)
    ]


def _join(blocks: list[Block]) -> str:
    return "\n".join(block.text.strip() for block in blocks if block.text.strip())


def _carry_over(blocks: list[Block], overlap_tokens: int) -> tuple[list[Block], int]:
    """Keep trailing blocks worth roughly `overlap_tokens` for the next chunk."""
    if overlap_tokens <= 0:
        return [], 0

    carried: list[Block] = []
    total = 0
    for block in reversed(blocks):
        if block.heading_level:
            break
        tokens = estimate_tokens(block.text)
        if total + tokens > overlap_tokens:
            break
        carried.insert(0, block)
        total += tokens

    return carried, total


_SENTENCE = re.compile(r"(?<=[.;:])\s+")


def _split_long(block: Block, target_tokens: int) -> list[str]:
    """Split an oversized block on sentence boundaries, never mid-figure."""
    budget = target_tokens * CHARS_PER_TOKEN
    sentences = _SENTENCE.split(block.text)

    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > budget:
            pieces.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()

    if current.strip():
        pieces.append(current.strip())

    # A single sentence longer than the budget: hard-split rather than drop it.
    output: list[str] = []
    for piece in pieces:
        while len(piece) > budget * 1.5:
            output.append(piece[:budget])
            piece = piece[budget:]
        if piece.strip():
            output.append(piece)

    return output
