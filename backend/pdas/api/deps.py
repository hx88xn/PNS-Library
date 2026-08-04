"""Shared request dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core.security import decode_token
from ..state import AppState, get_state

_bearer = HTTPBearer(auto_error=False)


def state() -> AppState:
    return get_state()


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    app_state: AppState = Depends(state),
) -> dict[str, str]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to use this service.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = decode_token(app_state.settings, credentials.credentials)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"service_no": claims["sub"], "role": claims.get("role", "user")}
