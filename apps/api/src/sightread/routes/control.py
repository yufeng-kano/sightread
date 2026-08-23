"""Control plane `/api/*` — session-cookie authenticated, consumed by the web app.

Mutations additionally require an `X-Requested-With` header (CSRF pairing with
SameSite=Lax), enforced by `require_csrf_header`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

from ..auth.api_keys import create_api_key
from ..auth.crypto import encrypt_connection_key, encrypt_openrouter_key, mask_openrouter_key
from ..auth.deps import AppSettings, CsrfGuard, DbSession, SessionUser
from ..auth.oidc import (
    DEV_USER_EMAIL,
    DEV_USER_SUB,
    POST_LOGIN_KEY,
    POST_LOGIN_LOCALE_KEY,
    upsert_user,
)
from ..auth.sessions import SESSION_COOKIE, SESSION_TTL, create_session, delete_session
from ..db.models import (
    ApiKey,
    Job,
    OpenRouterKey,
    PromptPreset,
    ProviderConnection,
    Result,
    UsageLog,
    UserSettings,
    utcnow,
)
from ..errors import ApiError
from ..jobs.runner import result_payload
from ..parsing.profiles import DEFAULT_PROMPT_TEMPLATE, get_profile
from ..upstream.openrouter import (
    fetch_connection_models,
    normalize_base_url,
    stored_connection_models,
    validate_api_key,
)

router = APIRouter(prefix="/api", tags=["control"])

# Registered by main.py only when APP_ENV=local and AUTH_DEV_MODE=true (docs/auth.md).
dev_router = APIRouter(prefix="/api", tags=["control"])


def set_session_cookie(response: Response, token: str) -> None:
    """Cookie flags are fixed by docs/auth.md: HttpOnly, Secure, SameSite=Lax.

    Secure is set unconditionally; browsers treat `http://localhost` as a secure context,
    so local development still receives the cookie.
    """
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


# --- authentication -------------------------------------------------------------------


@router.get("/auth/login")
async def login(request: Request, settings: AppSettings, locale: str = ""):
    if not settings.google_oidc_configured:
        raise ApiError(503, "internal", "Google sign-in is not configured on this deployment")
    # The web app's locale lives in its URL, so the Google round trip is the one leg that
    # drops it. Parked here rather than round-tripped through Google's `state`, which
    # authlib owns, and validated against an allowlist on the way out (docs/auth.md § 1).
    request.session[POST_LOGIN_LOCALE_KEY] = locale
    return await request.app.state.oauth.google.authorize_redirect(
        request, f"{settings.app_url}/api/auth/callback"
    )


@router.get("/auth/callback")
async def callback(request: Request, db: DbSession, settings: AppSettings):
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise ApiError(400, "auth", f"Google sign-in failed: {exc.error}") from exc

    claims = token.get("userinfo") or {}
    if not claims.get("sub") or not claims.get("email"):
        raise ApiError(400, "auth", "Google sign-in returned no usable identity")

    user = await upsert_user(db, claims["sub"], claims["email"], claims.get("name"))
    session_token = await create_session(db, user)
    await db.commit()

    # A connector flow parks the authorize request that sent the user here; only a path on
    # this origin is honoured, so a parked value can never become an open redirect. An
    # ordinary web login goes back to the web app in the locale it was started from.
    parked = request.session.pop(POST_LOGIN_KEY, "")
    locale = request.session.pop(POST_LOGIN_LOCALE_KEY, "")
    destination = (
        parked
        if parked.startswith("/oauth/authorize")
        else settings.web_url_for_locale(str(locale))
    )
    response = RedirectResponse(destination, status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, session_token)
    return response


@router.post("/auth/logout", dependencies=[CsrfGuard], status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: DbSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await delete_session(db, token)
        await db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@dev_router.post("/auth/dev-login", dependencies=[CsrfGuard])
async def dev_login(db: DbSession):
    """Local-only shortcut so the stack is demoable without Google credentials."""
    user = await upsert_user(db, DEV_USER_SUB, DEV_USER_EMAIL, "Local Developer")
    session_token = await create_session(db, user)
    await db.commit()
    response = JSONResponse({"user": {"id": user.id, "email": user.email}})
    set_session_cookie(response, session_token)
    return response


# --- account --------------------------------------------------------------------------


@router.get("/me")
async def me(user: SessionUser, db: DbSession):
    settings_row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one_or_none()
    key_row = (
        await db.execute(select(OpenRouterKey).where(OpenRouterKey.user_id == user.id))
    ).scalar_one_or_none()
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "created_at": user.created_at,
        },
        "settings": {
            "default_model": settings_row.default_model if settings_row else None,
            "default_profile": settings_row.default_profile if settings_row else None,
            "default_connection_id": settings_row.default_connection_id if settings_row else None,
            "prompt_preset_id": settings_row.prompt_preset_id if settings_row else None,
        },
        # The shipped prompt, so the settings page can show what "default" means.
        "defaults": {"system_prompt": DEFAULT_PROMPT_TEMPLATE},
        "openrouter_key": {
            "present": key_row is not None,
            "masked": key_row.masked if key_row else None,
            "updated_at": key_row.updated_at if key_row else None,
        },
    }


# --- API keys -------------------------------------------------------------------------


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


@router.get("/keys")
async def list_keys(user: SessionUser, db: DbSession):
    rows = (
        (
            await db.execute(
                select(ApiKey)
                .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
                .order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "keys": [
            {
                "id": row.id,
                "name": row.name,
                "prefix": row.prefix,
                "created_at": row.created_at,
                "last_used_at": row.last_used_at,
            }
            for row in rows
        ]
    }


@router.post("/keys", dependencies=[CsrfGuard], status_code=status.HTTP_201_CREATED)
async def create_key(body: ApiKeyCreate, user: SessionUser, db: DbSession):
    row, plaintext = await create_api_key(db, user, body.name)
    await db.commit()
    # `key` is returned exactly once and never stored in plaintext (docs/auth.md).
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "created_at": row.created_at,
        "key": plaintext,
    }


@router.delete("/keys/{key_id}", dependencies=[CsrfGuard], status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: int, user: SessionUser, db: DbSession) -> Response:
    row = (
        await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise ApiError(404, "invalid_request", "No such API key")
    row.revoked_at = utcnow()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- OpenRouter key -------------------------------------------------------------------


class OpenRouterKeyPut(BaseModel):
    key: str = Field(min_length=8, max_length=512)


@router.get("/openrouter-key")
async def get_openrouter_key(user: SessionUser, db: DbSession):
    row = (
        await db.execute(select(OpenRouterKey).where(OpenRouterKey.user_id == user.id))
    ).scalar_one_or_none()
    return {
        "present": row is not None,
        "masked": row.masked if row else None,
        "updated_at": row.updated_at if row else None,
    }


@router.put("/openrouter-key", dependencies=[CsrfGuard])
async def put_openrouter_key(
    body: OpenRouterKeyPut, user: SessionUser, db: DbSession, settings: AppSettings
):
    candidate = body.key.strip()
    if not await validate_api_key(candidate):
        raise ApiError(400, "invalid_request", "OpenRouter rejected this key")

    row = (
        await db.execute(select(OpenRouterKey).where(OpenRouterKey.user_id == user.id))
    ).scalar_one_or_none()
    ciphertext = encrypt_openrouter_key(settings.secret_key, candidate)
    masked = mask_openrouter_key(candidate)
    if row is None:
        row = OpenRouterKey(user_id=user.id, ciphertext=ciphertext, masked=masked)
        db.add(row)
    else:
        row.ciphertext = ciphertext
        row.masked = masked
        row.updated_at = utcnow()
    await db.commit()
    return {"present": True, "masked": masked, "updated_at": row.updated_at}


@router.delete("/openrouter-key", dependencies=[CsrfGuard], status_code=status.HTTP_204_NO_CONTENT)
async def delete_openrouter_key(user: SessionUser, db: DbSession) -> Response:
    await db.execute(delete(OpenRouterKey).where(OpenRouterKey.user_id == user.id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- provider connections -------------------------------------------------------------


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=1024)
    api_key: str = Field(min_length=8, max_length=512)


class ConnectionUpdate(BaseModel):
    """Partial update; changing the endpoint or the key re-validates against it."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=1024)
    api_key: str | None = Field(default=None, min_length=8, max_length=512)


async def _commit_or_name_conflict(db: DbSession, message: str) -> None:
    """Commit, mapping a unique-name race to the same 400 the pre-check gives.

    Two concurrent creates can both pass the duplicate pre-check before either commits;
    the loser's constraint violation is an ordinary name conflict, not a 500.
    """
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ApiError(400, "invalid_request", message) from exc


def _connection_payload(row: ProviderConnection) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "base_url": row.base_url,
        "masked": row.masked,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _owned_connection(
    db: DbSession, user_id: int, connection_id: int, for_update: bool = False
) -> ProviderConnection:
    # `for_update` serializes concurrent edits of one connection (PostgreSQL row lock;
    # compiled away on the SQLite test fallback): two edits validating different URL/key
    # pairs must not interleave into a stored pair nobody validated.
    query = select(ProviderConnection).where(
        ProviderConnection.id == connection_id, ProviderConnection.user_id == user_id
    )
    if for_update:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "invalid_request", "No such connection")
    return row


async def _refuse_duplicate_connection_name(
    db: DbSession, user_id: int, name: str, exclude_id: int | None = None
) -> None:
    query = select(ProviderConnection.id).where(
        ProviderConnection.user_id == user_id, ProviderConnection.name == name
    )
    if exclude_id is not None:
        query = query.where(ProviderConnection.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise ApiError(400, "invalid_request", "A connection with this name already exists")


@router.get("/connections")
async def list_connections(user: SessionUser, db: DbSession):
    rows = (
        (
            await db.execute(
                select(ProviderConnection)
                .where(ProviderConnection.user_id == user.id)
                .order_by(ProviderConnection.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"connections": [_connection_payload(row) for row in rows]}


@router.post("/connections", dependencies=[CsrfGuard], status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate, user: SessionUser, db: DbSession, settings: AppSettings
):
    name = body.name.strip()
    if not name:
        raise ApiError(400, "invalid_request", "The connection needs a name")
    base_url = await normalize_base_url(body.base_url, settings.app_env)
    candidate = body.api_key.strip()
    await _refuse_duplicate_connection_name(db, user.id, name)
    # `GET {base_url}/models` doubles as the save-time key check (docs/auth.md § 3).
    await fetch_connection_models(base_url, candidate, settings.upstream_response_max_bytes)

    row = ProviderConnection(
        user_id=user.id,
        name=name,
        base_url=base_url,
        ciphertext=encrypt_connection_key(settings.secret_key, candidate),
        masked=mask_openrouter_key(candidate),
    )
    db.add(row)
    await _commit_or_name_conflict(db, "A connection with this name already exists")
    return _connection_payload(row)


@router.put("/connections/{connection_id}", dependencies=[CsrfGuard])
async def update_connection(
    connection_id: int,
    body: ConnectionUpdate,
    user: SessionUser,
    db: DbSession,
    settings: AppSettings,
):
    row = await _owned_connection(db, user.id, connection_id, for_update=True)
    provided = body.model_fields_set

    name = body.name.strip() if body.name else row.name
    if not name:
        raise ApiError(400, "invalid_request", "The connection needs a name")
    if "name" in provided:
        await _refuse_duplicate_connection_name(db, user.id, name, exclude_id=row.id)

    base_url = (
        await normalize_base_url(body.base_url, settings.app_env)
        if "base_url" in provided and body.base_url
        else row.base_url
    )
    candidate = body.api_key.strip() if "api_key" in provided and body.api_key else None

    if candidate is not None:
        await fetch_connection_models(base_url, candidate, settings.upstream_response_max_bytes)
        row.ciphertext = encrypt_connection_key(settings.secret_key, candidate)
        row.masked = mask_openrouter_key(candidate)
    elif base_url != row.base_url:
        # A moved endpoint must still accept the stored key before we point jobs at it.
        await stored_connection_models(
            base_url, settings.secret_key, row.ciphertext, settings.upstream_response_max_bytes
        )

    row.name = name
    row.base_url = base_url
    row.updated_at = utcnow()
    await _commit_or_name_conflict(db, "A connection with this name already exists")
    return _connection_payload(row)


@router.delete(
    "/connections/{connection_id}",
    dependencies=[CsrfGuard],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_connection(
    connection_id: int, user: SessionUser, db: DbSession
) -> Response:
    row = await _owned_connection(db, user.id, connection_id)
    # Explicit fallback (not just the FK's SET NULL): a default model belongs to the
    # deleted endpoint's catalog, so it goes too — back to "not set" on OpenRouter.
    await db.execute(
        sa_update(UserSettings)
        .where(UserSettings.user_id == user.id, UserSettings.default_connection_id == row.id)
        .values(default_connection_id=None, default_model=None)
    )
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/connections/{connection_id}/models")
async def connection_models(
    connection_id: int, user: SessionUser, db: DbSession, settings: AppSettings
):
    """The connection's live model catalog, fetched with its stored key (docs/api.md)."""
    row = await _owned_connection(db, user.id, connection_id)
    models = await stored_connection_models(
        row.base_url, settings.secret_key, row.ciphertext, settings.upstream_response_max_bytes
    )
    return {"data": models}


# --- prompt presets ---------------------------------------------------------------------


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, min_length=1)


def _prompt_payload(row: PromptPreset) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "text": row.text,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _checked_prompt_text(text: str, settings) -> str:
    trimmed = text.strip()
    if not trimmed:
        raise ApiError(400, "invalid_request", "The prompt needs text")
    if len(trimmed) > settings.system_prompt_max_chars:
        raise ApiError(
            400,
            "invalid_request",
            f"The prompt exceeds {settings.system_prompt_max_chars} characters",
        )
    return trimmed


async def _owned_prompt(db: DbSession, user_id: int, prompt_id: int) -> PromptPreset:
    row = (
        await db.execute(
            select(PromptPreset).where(
                PromptPreset.id == prompt_id, PromptPreset.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "invalid_request", "No such prompt")
    return row


async def _refuse_duplicate_prompt_name(
    db: DbSession, user_id: int, name: str, exclude_id: int | None = None
) -> None:
    query = select(PromptPreset.id).where(
        PromptPreset.user_id == user_id, PromptPreset.name == name
    )
    if exclude_id is not None:
        query = query.where(PromptPreset.id != exclude_id)
    if (await db.execute(query)).first() is not None:
        raise ApiError(400, "invalid_request", "A prompt with this name already exists")


@router.get("/prompts")
async def list_prompts(user: SessionUser, db: DbSession):
    rows = (
        (
            await db.execute(
                select(PromptPreset)
                .where(PromptPreset.user_id == user.id)
                .order_by(PromptPreset.created_at)
            )
        )
        .scalars()
        .all()
    )
    return {"prompts": [_prompt_payload(row) for row in rows]}


@router.post("/prompts", dependencies=[CsrfGuard], status_code=status.HTTP_201_CREATED)
async def create_prompt(
    body: PromptCreate, user: SessionUser, db: DbSession, settings: AppSettings
):
    name = body.name.strip()
    if not name:
        raise ApiError(400, "invalid_request", "The prompt needs a name")
    text = _checked_prompt_text(body.text, settings)
    await _refuse_duplicate_prompt_name(db, user.id, name)
    row = PromptPreset(user_id=user.id, name=name, text=text)
    db.add(row)
    await _commit_or_name_conflict(db, "A prompt with this name already exists")
    return _prompt_payload(row)


@router.put("/prompts/{prompt_id}", dependencies=[CsrfGuard])
async def update_prompt(
    prompt_id: int, body: PromptUpdate, user: SessionUser, db: DbSession, settings: AppSettings
):
    row = await _owned_prompt(db, user.id, prompt_id)
    provided = body.model_fields_set
    if "name" in provided and body.name:
        name = body.name.strip()
        if not name:
            raise ApiError(400, "invalid_request", "The prompt needs a name")
        await _refuse_duplicate_prompt_name(db, user.id, name, exclude_id=row.id)
        row.name = name
    if "text" in provided and body.text:
        row.text = _checked_prompt_text(body.text, settings)
    row.updated_at = utcnow()
    await _commit_or_name_conflict(db, "A prompt with this name already exists")
    return _prompt_payload(row)


@router.delete(
    "/prompts/{prompt_id}", dependencies=[CsrfGuard], status_code=status.HTTP_204_NO_CONTENT
)
async def delete_prompt(prompt_id: int, user: SessionUser, db: DbSession) -> Response:
    row = await _owned_prompt(db, user.id, prompt_id)
    # Explicit fallback to the default prompt, not just the FK's SET NULL.
    await db.execute(
        sa_update(UserSettings)
        .where(UserSettings.user_id == user.id, UserSettings.prompt_preset_id == row.id)
        .values(prompt_preset_id=None)
    )
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- settings -------------------------------------------------------------------------


class SettingsPut(BaseModel):
    """Partial update: only the fields present in the body change (docs/api.md)."""

    default_model: str | None = Field(default=None, max_length=255)
    default_profile: str | None = Field(default=None, max_length=64)
    default_connection_id: int | None = None
    prompt_preset_id: int | None = None


@router.put("/settings", dependencies=[CsrfGuard])
async def put_settings(body: SettingsPut, user: SessionUser, db: DbSession):
    if body.default_profile is not None and get_profile(body.default_profile) is None:
        raise ApiError(400, "invalid_request", f"Unknown profile '{body.default_profile}'")
    if body.default_connection_id is not None:
        await _owned_connection(db, user.id, body.default_connection_id)
    if body.prompt_preset_id is not None:
        await _owned_prompt(db, user.id, body.prompt_preset_id)

    row = (
        await db.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
    provided = body.model_fields_set
    # The model/profile pair travels together: the web app always sends both.
    if "default_model" in provided or "default_profile" in provided:
        row.default_model = body.default_model
        row.default_profile = body.default_profile
    if "default_connection_id" in provided:
        row.default_connection_id = body.default_connection_id
    if "prompt_preset_id" in provided:
        row.prompt_preset_id = body.prompt_preset_id
    if row.default_connection_id is not None and row.default_profile is not None:
        # Profiles resolve against the OpenRouter catalog only (docs/api.md).
        raise ApiError(
            400, "invalid_request", "Profiles run on OpenRouter only; clear one of the two"
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        # Another tab deleted the selected connection/prompt between the ownership
        # pre-check and this commit — an ordinary selection race, not a 500.
        await db.rollback()
        raise ApiError(
            409, "invalid_request", "The selected connection or prompt was just deleted"
        ) from exc
    return {
        "default_model": row.default_model,
        "default_profile": row.default_profile,
        "default_connection_id": row.default_connection_id,
        "prompt_preset_id": row.prompt_preset_id,
    }


# --- usage ----------------------------------------------------------------------------


@router.get("/usage")
async def usage(user: SessionUser, db: DbSession, days: int = Query(default=30, ge=1, le=365)):
    since = utcnow() - timedelta(days=days)
    day = func.date(UsageLog.created_at)  # UTC day bucket on both PostgreSQL and SQLite

    per_day = (
        await db.execute(
            select(
                day.label("day"),
                func.sum(UsageLog.prompt_tokens),
                func.sum(UsageLog.completion_tokens),
                func.sum(UsageLog.cost),
            )
            .where(UsageLog.user_id == user.id, UsageLog.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    per_model = (
        await db.execute(
            select(
                UsageLog.model,
                func.sum(UsageLog.prompt_tokens),
                func.sum(UsageLog.completion_tokens),
                func.sum(UsageLog.cost),
            )
            .where(UsageLog.user_id == user.id, UsageLog.created_at >= since)
            .group_by(UsageLog.model)
            .order_by(UsageLog.model)
        )
    ).all()

    return {
        "days": days,
        "per_day": [
            {
                "date": str(bucket)[:10],
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "cost": float(cost or 0),
            }
            for bucket, prompt, completion, cost in per_day
        ],
        "per_model": [
            {
                "model": model,
                "prompt_tokens": int(prompt or 0),
                "completion_tokens": int(completion or 0),
                "cost": float(cost or 0),
            }
            for model, prompt, completion, cost in per_model
        ],
    }


# --- job history ----------------------------------------------------------------------


@router.get("/jobs")
async def list_jobs(user: SessionUser, db: DbSession, limit: int = Query(default=50, ge=1, le=200)):
    rows = (
        (
            await db.execute(
                select(Job)
                .where(Job.user_id == user.id)
                .order_by(Job.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "jobs": [
            {
                "job_id": str(row.id),
                "status": row.status,
                "filename": row.filename,
                "kind": row.kind,
                "model": row.model,
                "profile": row.profile,
                "page_count": row.page_count,
                "pages_done": row.pages_done,
                "error": row.error,
                "created_at": row.created_at,
                "finished_at": row.finished_at,
            }
            for row in rows
        ]
    }


@router.get("/jobs/{job_id}/result")
async def job_result(job_id: uuid.UUID, user: SessionUser, db: DbSession):
    job = (
        await db.execute(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "invalid_request", "No such job")
    result = (await db.execute(select(Result).where(Result.job_id == job_id))).scalar_one_or_none()
    if result is None:
        raise ApiError(404, "invalid_request", "This job has no result yet")
    return result_payload(result)
