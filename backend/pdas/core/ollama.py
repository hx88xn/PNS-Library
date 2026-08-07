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
        try:
            response = await self._client.get("/api/ps")
            response.raise_for_status()
        except httpx.HTTPError:
            return []  # a missing /api/ps is not worth failing a page over
        return [m["name"] for m in response.json().get("models", [])]

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
        on_meta: Callable[[dict[str, Any]], None] | None = None,
    ) -> AsyncIterator[str]:
        """Yield answer text as it is produced.

        Reasoning models split their output: deliberation goes to
        `message.thinking` and the answer to `message.content`. Only content is
        yielded. `on_meta` receives {done_reason, content_chars, thinking_chars}
        once the stream ends, which is how the caller can tell "the model had
        nothing to say" apart from "the model spent its whole budget thinking".
        """
        settings = self._settings
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
                "num_predict": settings.max_tokens if max_tokens is None else max_tokens,
            },
        }

        # Ask the model not to deliberate. Note this is a request, not a
        # guarantee: some model/Ollama combinations accept `think: false`
        # without error and reason anyway. The budget below is what actually
        # protects us — see num_predict in Settings.
        if self._disable_thinking:
            payload["think"] = False

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
