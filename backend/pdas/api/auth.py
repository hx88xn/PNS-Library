from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.security import authenticate, issue_token
from ..schemas import LoginRequest, LoginResponse
from ..state import AppState
from .deps import current_user, state

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, app_state: AppState = Depends(state)) -> LoginResponse:
    user = authenticate(app_state.conn, payload.service_no, payload.password)
    if user is None:
        # One message for both failure modes: a distinct "no such user" reply
        # would let anyone enumerate valid service numbers.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service number or passphrase is incorrect.",
        )

    return LoginResponse(
        access_token=issue_token(app_state.settings, user["service_no"], user["role"]),
        service_no=user["service_no"],
        display_name=user["display_name"],
        role=user["role"],
    )


@router.get("/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user
