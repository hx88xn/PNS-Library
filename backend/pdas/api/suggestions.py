"""Opening questions for the empty chat screen.

Generated from the indexed corpus and verified against the retriever — see
core/openers.py for why both halves matter.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..core import openers
from ..schemas import SuggestionResponse
from ..state import AppState
from .deps import current_user, state

router = APIRouter()


@router.get("/suggestions", response_model=SuggestionResponse)
async def suggestions(
    collection: str = "all",
    app_state: AppState = Depends(state),
    _user: dict = Depends(current_user),
) -> SuggestionResponse:
    questions = await openers.generate(
        conn=app_state.conn,
        store=app_state.store,
        sparse=app_state.sparse,
        ollama=app_state.ollama,
        settings=app_state.settings,
        collection=collection,
    )
    return SuggestionResponse(suggestions=questions)
