"""Parse intake: everything between "bytes arrive" and "a job exists" (docs/api.md, docs/jobs.md).

`POST /v1/parse` and the web library's `POST /api/library/documents` run this one sequence
— store, hash, probe, dedup, enqueue — whichever credential opened the door (API key, OAuth
token, upload ticket, or the web session). A route keeps only its transport concerns
(multipart vs base64, SSE vs JSON, which folder the file lands in); the shell owns no
business logic (docs/project-structure.md).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import upload_tickets
from ..config import Settings
from ..db.models import Job, Result, UploadTicket, User
from ..errors import ApiError
from ..parsing import poppler
from ..parsing.images import ACCEPTED_IMAGE_TYPES, ImageError, probe_image
from ..parsing.profiles import BBOX_FORMAT_YXYX, get_profile, transcription_prompt_template
from ..upstream.openrouter import fetch_image_models
from .queue import (
    count_running_jobs,
    enqueue_job,
    find_active_job,
    find_cached_job,
    hold_dedup_key,
    normalize_pages_spec,
    parse_pages_spec,
)
from .runner import result_payload

PDF_MEDIA_TYPE = "application/pdf"
RETRY_AFTER_SECONDS = 30
UPLOAD_CHUNK_BYTES = 1024 * 1024
# Room for the multipart envelope around a file at the cap: boundaries, part headers and
# the other fields. The exact cap on the document itself stays in `store_upload`; this is
# the coarse bound that stops a body being spooled to disk without limit.
MULTIPART_ENVELOPE_BYTES = 64 * 1024
# Base64 decodes in whole 4-character groups, so the slice length must stay a multiple of 4.
BASE64_CHUNK_CHARS = 4 * 256 * 1024


@dataclass
class Submission:
    """The outcome of an intake: either a queued job or a cached result, never both."""

    job: Job | None = None
    cached: Result | None = None


class ChunkReader(Protocol):
    """What a multipart upload has to offer to be streamed: `read(size)`.

    Typed as a protocol rather than as Starlette's `UploadFile` so this layer stays a
    service and not a piece of the web framework — every route that accepts a file hands
    its own reader in (docs/project-structure.md § Boundaries).
    """

    async def read(self, size: int = -1) -> bytes: ...


async def upload_chunks(upload: ChunkReader) -> AsyncIterator[bytes]:
    """Read a multipart upload in slices, so the document never sits in memory whole."""
    while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
        yield chunk


async def capped_stream(stream: AsyncIterator[bytes], max_bytes: int) -> AsyncIterator[bytes]:
    """A request body that stops at a size, for the multipart parser to read.

    The parser spools every file part to disk as it arrives with no cap of its own, and
    `store_upload` only sees the file once the whole body has been parsed. A request that
    declares no length — chunked, or simply lying — could therefore fill the upload
    directory long before anything answered 413. This is where that request stops.
    """
    total = 0
    async for chunk in stream:
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(413, "invalid_request", "The upload exceeds UPLOAD_MAX_BYTES")
        yield chunk


async def base64_chunks(source: str) -> AsyncIterator[bytes]:
    """Decode a base64 `source` in slices, so a large document never sits in memory twice."""
    compact = "".join(source.split())
    for start in range(0, len(compact), BASE64_CHUNK_CHARS):
        piece = compact[start : start + BASE64_CHUNK_CHARS]
        try:
            yield base64.b64decode(piece, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ApiError(400, "invalid_request", "'source' is not valid base64") from exc


def resolve_kind(filename: str, media_type: str) -> tuple[str, str]:
    """Decide pdf vs image from the declared type, falling back to the file extension."""
    suffix = Path(filename).suffix.lower()
    if media_type == PDF_MEDIA_TYPE or suffix == ".pdf":
        return "pdf", PDF_MEDIA_TYPE
    if media_type in ACCEPTED_IMAGE_TYPES:
        return "image", media_type
    for accepted, extension in ACCEPTED_IMAGE_TYPES.items():
        if suffix == extension:
            return "image", accepted
    raise ApiError(400, "invalid_request", "Only PDF and jpg/png/webp/heic images are accepted")


@dataclass(frozen=True)
class Target:
    """What a job will run: model, profile facts, prompt and the upstream it calls.

    `connection_base_url` snapshots the endpoint at enqueue time — part of the dedup key,
    so editing a connection's URL invalidates the old endpoint's cached results.
    """

    model: str
    profile: str | None
    profile_version: int
    bbox_format: str
    prompt: str
    connection_id: int | None
    connection_base_url: str | None


async def resolve_target(user: User, model: str | None, profile_id: str | None) -> Target:
    """Model, profile, bbox format, prompt template and upstream for this job.

    A preset profile resolves its model from the live OpenRouter catalog. A raw model id
    runs the default prompt and is untested by us. The user's selected prompt preset, when
    one is set, replaces the template in every case (docs/parsing.md § Prompts). When the
    user's default connection is a custom OpenAI-compatible endpoint, profiles do not
    apply and the model comes from the connection itself — a connection is a complete
    profile, so `user_settings.default_model` never applies to it (docs/api.md §
    Upstreams).
    """
    settings_row = user.settings
    preset = settings_row.prompt_preset if settings_row else None
    custom_prompt = preset.text if preset else None
    connection = settings_row.default_connection if settings_row else None
    if not model and not profile_id and connection is None:
        profile_id = settings_row.default_profile if settings_row else None
        model = settings_row.default_model if settings_row else None
    if model and profile_id:
        raise ApiError(400, "invalid_request", "Pass either 'model' or 'profile', not both")

    if connection is not None:
        if profile_id:
            raise ApiError(
                400,
                "invalid_request",
                "Profiles run on OpenRouter only; pass 'model' or switch back to OpenRouter",
            )
        # An explicit request model still overrides; the connection's own model is the
        # default. NULL only on rows that predate the model column (docs/database.md).
        model = model or connection.model
        if not model:
            raise ApiError(
                400,
                "invalid_request",
                "No model configured: pass 'model' or set one on the connection",
            )
        prompt = custom_prompt or transcription_prompt_template(None)
        return Target(
            model, None, 0, BBOX_FORMAT_YXYX, prompt, connection.id, connection.base_url
        )

    if profile_id:
        profile = get_profile(profile_id)
        if profile is None:
            raise ApiError(400, "invalid_request", f"Unknown profile '{profile_id}'")
        resolved = profile.resolve_model(await fetch_image_models())
        if resolved is None:
            raise ApiError(503, "upstream", f"Profile '{profile_id}' has no available model")
        prompt = custom_prompt or profile.prompt_template
        return Target(
            resolved, profile.id, profile.profile_version, profile.bbox_format, prompt, None, None
        )

    if model:
        prompt = custom_prompt or transcription_prompt_template(None)
        return Target(model, None, 0, BBOX_FORMAT_YXYX, prompt, None, None)

    raise ApiError(
        400, "invalid_request", "No model configured: pass 'model' or 'profile', or set a default"
    )


async def store_upload(
    chunks: AsyncIterator[bytes], destination: Path, max_bytes: int
) -> tuple[int, str]:
    """Stream an upload to disk, hashing as it goes; the whole file never sits in memory."""
    digest = hashlib.sha256()
    size = 0
    try:
        with destination.open("wb") as handle:
            async for chunk in chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise ApiError(413, "invalid_request", "The upload exceeds UPLOAD_MAX_BYTES")
                digest.update(chunk)
                handle.write(chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


async def count_pages(kind: str, path: Path, upload_dir: Path, page_cap: int) -> int:
    """Page count for a stored upload, rejecting documents we cannot read or must not run."""
    if kind == "image":
        try:
            probe_image(path)
        except ImageError as exc:
            path.unlink(missing_ok=True)
            raise ApiError(400, "invalid_request", "The image could not be decoded") from exc
        return 1

    try:
        info = await poppler.pdf_info(path, cwd=upload_dir)
    except poppler.PopplerError as exc:
        path.unlink(missing_ok=True)
        raise ApiError(400, "invalid_request", "The PDF could not be read") from exc
    if info.page_count > page_cap:
        path.unlink(missing_ok=True)
        raise ApiError(400, "invalid_request", f"The PDF exceeds the {page_cap} page cap")
    return info.page_count


async def submit_parse(
    db: AsyncSession,
    settings: Settings,
    *,
    user: User,
    chunks: AsyncIterator[bytes],
    media_type: str,
    filename: str,
    model: str | None = None,
    profile_id: str | None = None,
    pages: str | None = None,
    force: bool = False,
    ticket: UploadTicket | None = None,
    reuse_in_flight: bool = False,
) -> Submission:
    """Store the document, dedup it and queue the parse. Commits before it returns.

    An upload ticket is bound and spent by that same commit, so nothing rejected on the way
    here (413, 400, 429) costs the caller its one upload (docs/auth.md § 5).

    `reuse_in_flight` additionally answers with a job that is still queued or running for
    these exact bytes instead of starting a second one. Only the web library asks for it: a
    browser cannot tell a lost response from a lost request, so its retry would otherwise
    buy the user a second parse of a document they already paid for (docs/jobs.md § Dedup).
    """
    kind, media_type = resolve_kind(filename, media_type)
    target = await resolve_target(user, model, profile_id)
    prompt_sha256 = hashlib.sha256(target.prompt.encode()).hexdigest()

    if await count_running_jobs(db, user.id) >= settings.max_jobs_per_user:
        raise ApiError(
            429,
            "rate_limit",
            "Too many running jobs; retry when one finishes",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4()
    stored = upload_dir / f"{job_id}{Path(filename).suffix.lower()[:16]}"
    size_bytes, sha256 = await store_upload(chunks, stored, settings.upload_max_bytes)

    page_count = await count_pages(kind, stored, upload_dir, settings.page_cap)
    pages_spec = normalize_pages_spec(pages)
    try:
        parse_pages_spec(pages_spec, page_count)
    except ValueError as exc:
        stored.unlink(missing_ok=True)
        raise ApiError(400, "invalid_request", str(exc)) from exc

    key = {
        "user_id": user.id,
        "sha256": sha256,
        "model": target.model,
        "connection_id": target.connection_id,
        "connection_base_url": target.connection_base_url,
        "profile": target.profile,
        "profile_version": target.profile_version,
        "pages_spec": pages_spec,
        "prompt_sha256": prompt_sha256,
    }

    if not force:
        cached = await find_cached_job(db, **key)
        result = (
            None
            if cached is None
            else (
                await db.execute(select(Result).where(Result.job_id == cached.id))
            ).scalar_one_or_none()
        )
        if result is not None and result.errors:
            # A degraded result (failed pages) answers its own job, never a new upload —
            # a transient upstream failure must not be replayed forever (docs/jobs.md).
            result = None
        if result is not None:
            # The cache already holds this exact parse; the fresh copy is dead weight.
            stored.unlink(missing_ok=True)
            if ticket is not None:
                upload_tickets.spend(ticket, result.job_id)
                await db.commit()
            return Submission(cached=result)

        if reuse_in_flight:
            # Held until this transaction commits, so a second upload of the same bytes
            # waits here rather than racing past the check below into its own parse.
            await hold_dedup_key(db, **key)
            active = await find_active_job(db, **key)
            if active is not None:
                # The same parse is already on its way. Starting another would spend the
                # user's key twice over for one document.
                stored.unlink(missing_ok=True)
                if ticket is not None:
                    upload_tickets.spend(ticket, active.id)
                    await db.commit()
                return Submission(job=active)

    job = await enqueue_job(
        db,
        user_id=user.id,
        kind=kind,
        filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        pages_spec=pages_spec,
        model=target.model,
        connection_id=target.connection_id,
        connection_base_url=target.connection_base_url,
        profile=target.profile,
        profile_version=target.profile_version,
        bbox_format=target.bbox_format,
        prompt=target.prompt,
        prompt_sha256=prompt_sha256,
        page_count=page_count,
        source_path=str(stored),
    )
    if ticket is not None:
        upload_tickets.spend(ticket, job.id)
    await db.commit()
    return Submission(job=job)


def cached_payload(result: Result) -> dict:
    """The result payload of a dedup hit, flagged `meta.cached` (docs/jobs.md § Dedup)."""
    payload = result_payload(result)
    payload["meta"] = {**payload["meta"], "cached": True}
    return payload
