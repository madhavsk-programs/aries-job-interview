"""Short-lived, session-scoped access tokens for transcript and report APIs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import Header, HTTPException, Query

from config import settings


def issue_session_token(session_id: str, ttl_seconds: int = 60 * 60 * 6) -> str:
    payload = {"sid": session_id, "exp": int(time.time()) + ttl_seconds}
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    signature = hmac.new(
        settings.access_secret.encode(), body.encode(), hashlib.sha256
    ).digest()
    return f"{body}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def verify_session_token(token: str, session_id: str) -> None:
    try:
        body, supplied = token.split(".", 1)
        expected = hmac.new(
            settings.access_secret.encode(), body.encode(), hashlib.sha256
        ).digest()
        supplied_bytes = base64.urlsafe_b64decode(supplied + "=" * (-len(supplied) % 4))
        payload = json.loads(
            base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid session access token.") from exc
    if not hmac.compare_digest(expected, supplied_bytes):
        raise HTTPException(status_code=401, detail="Invalid session access token.")
    if payload.get("sid") != session_id or int(payload.get("exp", 0)) < time.time():
        raise HTTPException(status_code=401, detail="Session access token expired or mismatched.")


def require_session_access(
    session_id: str,
    access_token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    token = access_token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="A session access token is required.")
    verify_session_token(token, session_id)
