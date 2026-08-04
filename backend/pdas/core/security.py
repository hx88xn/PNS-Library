"""Password hashing and bearer tokens.

Local accounts only. There is no directory server to talk to on an air-gapped
box, and no password reset path that does not involve an administrator at the
console — `pdas adduser` is that path.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from ..config import Settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError):
        return False


def issue_token(settings: Settings, service_no: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": service_no,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(settings: Settings, token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def create_user(
    conn: sqlite3.Connection,
    service_no: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
) -> None:
    conn.execute(
        "INSERT INTO users(service_no, password_hash, display_name, role, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (
            service_no.strip().upper(),
            hash_password(password),
            display_name,
            role,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def authenticate(
    conn: sqlite3.Connection, service_no: str, password: str
) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM users WHERE service_no = ? AND disabled = 0",
        (service_no.strip().upper(),),
    ).fetchone()

    # Hash even when the user is absent, so a missing account and a wrong
    # password take the same time to reject.
    if row is None:
        _hasher.hash(password)
        return None

    return row if verify_password(row["password_hash"], password) else None
