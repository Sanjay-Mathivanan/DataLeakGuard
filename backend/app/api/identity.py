"""Authentication and request-scoped authorization helpers."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.models import AuthSession, User
from app.db.session import get_db

SESSION_COOKIE_NAME = "dlg_session"
CSRF_COOKIE_NAME = "dlg_csrf"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    session_hash = digest_token(raw_token)
    auth_session = db.query(AuthSession).filter(
        AuthSession.token_hash == session_hash,
        AuthSession.revoked_at.is_(None),
    ).first()
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = db.query(User).filter(User.id == auth_session.user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    if request.method.upper() in UNSAFE_METHODS:
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        csrf_header = request.headers.get("X-CSRF-Token")
        if (
            not csrf_cookie
            or not csrf_header
            or not hmac.compare_digest(csrf_cookie, csrf_header)
            or not hmac.compare_digest(
                digest_token(csrf_header), auth_session.csrf_token_hash
            )
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return user
