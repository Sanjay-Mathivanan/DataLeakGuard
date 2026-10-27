import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.api.identity import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    digest_token,
    get_current_user,
)
from app.core.auth_rate_limit import enforce_auth_rate_limit
from app.core.config import settings
from app.db.models import AuthSession, User
from app.db.session import get_db
from app.schemas.identity import (
    AuthResponse,
    LoginRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserRead,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 320 or not _EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    return normalized


def _origin_from_url(value: str, *, allow_path: bool) -> str | None:
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if (
            scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (
                not allow_path
                and (
                    parsed.path not in {"", "/"}
                    or parsed.query
                    or parsed.fragment
                )
            )
        ):
            return None
        host = parsed.hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parsed.port
        default_port = 80 if scheme == "http" else 443
        suffix = f":{port}" if port and port != default_port else ""
        return f"{scheme}://{host}{suffix}"
    except (ValueError, TypeError):
        return None


def _validate_auth_origin(request: Request) -> None:
    supplied_origin = request.headers.get("origin")
    if supplied_origin:
        request_origin = _origin_from_url(supplied_origin, allow_path=False)
    else:
        referer = request.headers.get("referer")
        request_origin = _origin_from_url(referer, allow_path=True) if referer else None

    allowed_origins = {
        normalized
        for configured in settings.BACKEND_CORS_ORIGINS
        if (normalized := _origin_from_url(str(configured), allow_path=False))
    }
    if request_origin is None or request_origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request origin is not allowed",
        )


def _secure_cookie(request: Request) -> bool:
    # The setting covers TLS termination; direct HTTPS requests are always Secure.
    return bool(settings.AUTH_COOKIE_SECURE or request.url.scheme.lower() == "https")


def _issue_session(
    user: User, db: Session, response: Response, request: Request
) -> AuthResponse:
    raw_session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.AUTH_SESSION_TTL_HOURS)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=digest_token(raw_session_token),
            csrf_token_hash=digest_token(csrf_token),
            expires_at=expires_at,
        )
    )
    db.commit()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_session_token,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        max_age=settings.AUTH_SESSION_TTL_HOURS * 60 * 60,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        secure=_secure_cookie(request),
        samesite="lax",
        max_age=settings.AUTH_SESSION_TTL_HOURS * 60 * 60,
        path="/",
    )
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _validate_auth_origin(request)
    enforce_auth_rate_limit(request, "register")
    email = _normalize_email(payload.email)
    if db.query(User.id).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=generate_password_hash(payload.password, method="scrypt"),
    )
    if not user.display_name:
        raise HTTPException(status_code=422, detail="Display name cannot be empty")
    db.add(user)
    try:
        db.flush()
        result = _issue_session(user, db, response, request)
        return result
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    except Exception:
        db.rollback()
        raise


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _validate_auth_origin(request)
    enforce_auth_rate_limit(request, "login")
    email = _normalize_email(payload.email)
    user = db.query(User).filter(User.email == email).first()
    if user is None or not check_password_hash(user.password_hash, payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _issue_session(user, db, response, request)


@router.get("/me", response_model=AuthResponse)
def current_user(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_session_token = request.cookies.get(SESSION_COOKIE_NAME)
    auth_session = db.query(AuthSession).filter(
        AuthSession.token_hash == digest_token(raw_session_token or ""),
        AuthSession.revoked_at.is_(None),
    ).first()
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    csrf_token = secrets.token_urlsafe(32)
    auth_session.csrf_token_hash = digest_token(csrf_token)
    db.commit()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        secure=_secure_cookie(request),
        samesite="lax",
        max_age=settings.AUTH_SESSION_TTL_HOURS * 60 * 60,
        path="/",
    )
    return AuthResponse(user=UserRead.model_validate(user), csrf_token=csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    session = db.query(AuthSession).filter(
        AuthSession.token_hash == digest_token(raw_token or ""),
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).first()
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", samesite="lax", secure=_secure_cookie(request)
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, path="/", samesite="lax", secure=_secure_cookie(request)
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.patch("/profile", response_model=UserRead)
def update_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    email = _normalize_email(payload.email)
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Display name cannot be empty")
    duplicate = db.query(User.id).filter(User.email == email, User.id != user.id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user.email = email
    user.display_name = display_name
    user.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not check_password_hash(user.password_hash, payload.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = generate_password_hash(payload.new_password, method="scrypt")
    # Revoke all existing sessions, including the current one; user must log
    # in again after changing credentials.
    now = datetime.now(timezone.utc)
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update({AuthSession.revoked_at: now}, synchronize_session=False)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
