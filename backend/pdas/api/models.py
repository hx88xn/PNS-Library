"""Choosing the generation model at runtime.

The server holds ONE generation model in VRAM at a time. That is not a
simplification, it is the hardware: the target box is an RTX 4060 with about
6.5 GB usable once Windows has taken its share, and a 4B at Q4_K_M with a 16k
context is ~3.7 GB against the embedder's ~0.7 GB. A second generation model
does not fit, and letting Ollama page them in and out on demand turns a
question into a thirty-second disk read at random.

So selecting a model is an explicit, serialised operation: evict the old one,
load the new one, and only then report success.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.ollama import OllamaError
from ..schemas import ModelInfo, ModelListResponse, ModelSelectRequest
from ..state import AppState
from .deps import current_user, state

router = APIRouter()

# One switch at a time. Two concurrent selections would race on which model is
# left resident, and the loser's answer would come from the wrong weights.
_switching = asyncio.Lock()

MODEL_KEY = "llm_model"
"""Where the choice is persisted, so a restart does not silently revert to the
configured default while the operator believes their selection stands."""


@router.get("/models", response_model=ModelListResponse)
async def models(
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> ModelListResponse:
    settings = app_state.settings

    try:
        details = await app_state.ollama.model_details()
        loaded = set(await app_state.ollama.loaded_models())
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    embed = _qualify(settings.embed_model)

    available = [
        ModelInfo(
            name=entry["name"],
            size=entry.get("size"),
            parameter_size=(entry.get("details") or {}).get("parameter_size"),
            quantization=(entry.get("details") or {}).get("quantization_level"),
            loaded=entry["name"] in loaded,
        )
        # The embedding model is not offered. Selecting it would leave the
        # server unable to answer anything, and its residency is not optional.
        for entry in details
        if entry["name"] != embed
    ]
    available.sort(key=lambda m: m.name)

    return ModelListResponse(
        current=settings.llm_model,
        embed_model=settings.embed_model,
        available=available,
        busy=_switching.locked(),
    )


@router.post("/models/select", response_model=ModelListResponse)
async def select(
    request: ModelSelectRequest,
    app_state: AppState = Depends(state),
    user: dict = Depends(current_user),
) -> ModelListResponse:
    settings = app_state.settings
    wanted = request.name.strip()

    if not wanted:
        raise HTTPException(status_code=400, detail="Name a model to load.")
    if wanted == _qualify(settings.embed_model):
        raise HTTPException(
            status_code=400,
            detail="That is the embedding model. It cannot answer questions.",
        )

    if _switching.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A model is already being loaded. Wait for it to finish.",
        )

    async with _switching:
        try:
            present = set(await app_state.ollama.list_models())
        except OllamaError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        if wanted not in present:
            raise HTTPException(
                status_code=404,
                detail=f"'{wanted}' is not on this server. Pull it first.",
            )

        previous = settings.llm_model
        if wanted != previous:
            # Evict BEFORE loading, not after. On an 8 GB card the two models
            # would otherwise be resident together for the length of the load,
            # which is exactly when it fails.
            await app_state.ollama.unload(previous)

        try:
            await app_state.ollama.load(wanted)
        except OllamaError as exc:
            # Put the old one back rather than leaving the box with nothing
            # loaded and a setting pointing at a model that would not start.
            await app_state.ollama.load(previous)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        settings.llm_model = wanted
        _remember(app_state, wanted)

    return await models(app_state=app_state, _user=user)


def _qualify(name: str) -> str:
    """Ollama reports 'bge-m3:latest' for a model configured as 'bge-m3'."""
    return name if ":" in name else f"{name}:latest"


def _remember(app_state: AppState, name: str) -> None:
    app_state.conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (MODEL_KEY, name),
    )
    app_state.conn.commit()


def restore(app_state: AppState) -> None:
    """Re-apply a previously selected model at startup.

    Silently ignored if the model is no longer on the box: falling back to the
    configured default is better than starting up pointed at weights that are
    not there, and /api/health reports the mismatch either way.
    """
    row = app_state.conn.execute(
        "SELECT value FROM meta WHERE key = ?", (MODEL_KEY,)
    ).fetchone()
    if row and row["value"]:
        app_state.settings.llm_model = row["value"]
