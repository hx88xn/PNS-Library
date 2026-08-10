"""Ollama HTTP client.

This module and nothing else knows how the models are served. If Ollama is ever
swapped for llama-cpp-python or a llama.cpp server binary, only this file and
the two thin wrappers over it change.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

import httpx

from ..config import Settings


class OllamaError(RuntimeError):
    """Ollama is unreachable, or a model is not present on the box."""


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._disable_thinking = True
        self._gpu: bool | None = None
        """Whether the generation model is on the GPU. None until asked."""
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_host.rstrip("/"),
            timeout=httpx.Timeout(settings.ollama_timeout, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── introspection ────────────────────────────────────────────────────

    async def list_models(self) -> list[str]:
        return [m["name"] for m in await self.model_details()]

    async def model_details(self) -> list[dict[str, Any]]:
        """Every model on the box, with the size and family Ollama reports."""
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Cannot reach Ollama at {self._settings.ollama_host}. "
                "Is the service running?"
            ) from exc
        return response.json().get("models", [])

    async def loaded_models(self) -> list[str]:
        """What is resident in VRAM right now, as opposed to merely present."""
        return [m["name"] for m in await self._resident()]

    async def _resident(self) -> list[dict[str, Any]]:
        try:
            response = await self._client.get("/api/ps")
            response.raise_for_status()
        except httpx.HTTPError:
            return []  # a missing /api/ps is not worth failing a page over
        return response.json().get("models", [])

    async def on_gpu(self) -> bool:
        """Whether the generation model is actually running on the GPU.

        Deliberately not "is CUDA installed". Ollama reports `size_vram` beside
        `size` in /api/ps, which is the difference between a card being present
        and the weights being on it — and a partial offload, where the runtime
        is missing or the model does not fit, is precisely the case that looks
        like a working GPU and performs like a CPU.

        A model split across both is treated as CPU. Reasoning on a partial
        offload is slower than not reasoning at all.

        Cached: this decides a per-request flag, and an extra HTTP round trip on
        every question to re-answer a question about the hardware is waste. The
        cache is dropped whenever a model is loaded or evicted, which is the
        only thing that can change the answer.
        """
        if self._gpu is not None:
            return self._gpu

        wanted = self._qualify(self._settings.llm_model)
        self._gpu = False
        for entry in await self._resident():
            if self._qualify(entry.get("name", "")) != wanted:
                continue
            total = entry.get("size") or 0
            vram = entry.get("size_vram") or 0
            # 95%, not 100%: Ollama leaves a little of the KV cache in host
            # memory even on a full offload, and a model that is 99% on the
            # card is on the card.
            self._gpu = bool(total) and vram / total >= 0.95
            break
        return self._gpu

    def forget_placement(self) -> None:
        """Drop the cached GPU answer. Called whenever residency changes."""
        self._gpu = None

    @staticmethod
    def _qualify(name: str) -> str:
        return name if ":" in name else f"{name}:latest"

    # ── residency ────────────────────────────────────────────────────────

    async def unload(self, model: str, timeout: float = 30.0) -> bool:
        """Evict a model and wait until the memory is actually released.

        keep_alive 0 is Ollama's word for "now", but the request returns when
        the eviction is *accepted*, not when it is done. Returning at that point
        let the caller start the next load while the outgoing model was still
        resident — both in memory at once, which on a memory-tight box is the
        one condition a load cannot survive.

        So this polls /api/ps until the model is gone. Returns whether it
        actually went: a caller about to load something large needs to know,
        and a false here is far more useful than an exception, since there is
        nothing sensible to do about it other than proceed and hope.
        """
        self.forget_placement()
        qualified = model if ":" in model else f"{model}:latest"

        try:
            await self._client.post(
                "/api/generate", json={"model": model, "keep_alive": 0}
            )
        except httpx.HTTPError:
            pass  # already gone, or never loaded — the poll below settles it

        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            resident = {m if ":" in m else f"{m}:latest" for m in await self.loaded_models()}
            if qualified not in resident:
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.4)

    async def load(self, model: str) -> None:
        """Bring a model into VRAM and pin it.

        An empty prompt is Ollama's load-only request: it reads the weights and
        returns without generating. Given a long timeout because a cold 4B off
        a slow disk is tens of seconds, and the caller is a user who has just
        chosen it from a menu and is watching.
        """
        self.forget_placement()
        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "keep_alive": self._settings.keep_alive,
                },
                timeout=httpx.Timeout(600.0, connect=5.0),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Could not load {model}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Could not load {model}: {exc}") from exc

    async def has_model(self, name: str) -> bool:
        """True if the tag is present. Ollama reports 'qwen3.5:4b' for a model
        pulled as 'qwen3.5:4b', but bare names imply ':latest'."""
        wanted = name if ":" in name else f"{name}:latest"
        return wanted in await self.list_models()

    # ── embeddings ───────────────────────────────────────────────────────

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self._client.post(
                "/api/embed",
                json={
                    "model": self._settings.embed_model,
                    "input": texts,
                    "keep_alive": self._settings.keep_alive,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OllamaError(
                f"Embedding failed with {self._settings.embed_model}: "
                f"{exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Embedding request failed: {exc}") from exc

        embeddings = response.json().get("embeddings")
        if not embeddings or len(embeddings) != len(texts):
            raise OllamaError(
                f"Expected {len(texts)} embeddings, got "
                f"{0 if not embeddings else len(embeddings)}"
            )
        return embeddings

    # ── generation ───────────────────────────────────────────────────────

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
        on_meta: Callable[[dict[str, Any]], None] | None = None,
    ) -> AsyncIterator[str]:
        """Yield answer text as it is produced.

        Reasoning models split their output: deliberation goes to
        `message.thinking` and the answer to `message.content`. Only content is
        yielded. `on_meta` receives {done_reason, content_chars, thinking_chars}
        once the stream ends, which is how the caller can tell "the model had
        nothing to say" apart from "the model spent its whole budget thinking".

        `think` is tri-state. True and False are the user's explicit choice.
        None means decide from the hardware: deliberation is worth having when
        the weights are on the GPU and is a minute of staring at a spinner when
        they are not.
        """
        settings = self._settings
        reasoning = await self.on_gpu() if think is None else think
        payload: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "stream": True,
            # Re-pins on every call. Without it Ollama reverts this model to the
            # five-minute default and the next question pays a cold load.
            "keep_alive": settings.keep_alive,
            "options": {
                "temperature": settings.temperature if temperature is None else temperature,
                "num_ctx": settings.num_ctx,
                # Thinking is spent out of the same budget as the answer, so
                # a reasoning turn needs a bigger one. Left at the default a
                # hard question deliberates its way to an empty bubble — the
                # failure the note on Settings.max_tokens records.
                "num_predict": (
                    max_tokens
                    if max_tokens is not None
                    else settings.reasoning_max_tokens
                    if reasoning
                    else settings.max_tokens
                ),
            },
        }

        # A request, not a guarantee, in both directions: some model/Ollama
        # combinations accept `think` and ignore it, and a model that does no
        # reasoning at all will not start because it was asked to. The budget
        # above is what actually protects against a runaway deliberation.
        if self._disable_thinking:
            payload["think"] = reasoning

        try:
            async for chunk in self._stream_chat(payload, on_meta):
                yield chunk
        except _ThinkingUnsupported:
            self._disable_thinking = False  # don't pay for this again
            payload.pop("think", None)
            async for chunk in self._stream_chat(payload, on_meta):
                yield chunk

    async def _stream_chat(
        self, payload: dict[str, Any], on_meta: Callable[[dict[str, Any]], None] | None
    ) -> AsyncIterator[str]:
        content_chars = 0
        thinking_chars = 0
        done_reason = None

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    if "think" in body.lower() and "think" in payload:
                        raise _ThinkingUnsupported
                    raise OllamaError(f"Generation failed: {body[:200]}")

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    message = event.get("message", {})
                    thinking_chars += len(message.get("thinking") or "")

                    chunk = message.get("content", "")
                    if chunk:
                        content_chars += len(chunk)
                        yield chunk

                    if event.get("done"):
                        done_reason = event.get("done_reason")
                        break
        except httpx.HTTPError as exc:
            raise OllamaError(f"Generation request failed: {exc}") from exc
        finally:
            if on_meta:
                on_meta(
                    {
                        "done_reason": done_reason,
                        "content_chars": content_chars,
                        "thinking_chars": thinking_chars,
                    }
                )


class _ThinkingUnsupported(Exception):
    """Internal: the model rejects the `think` option."""
