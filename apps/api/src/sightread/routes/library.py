"""Control plane `/api/library/*` — the web file library (docs/web.md § Files).

Thin like every route module. Folders and documents are names and places; the parse behind
a document is a `jobs` row this module never interprets, and the upload is handed straight
to `jobs.intake.submit_parse`, the same sequence `/v1/parse` runs
(docs/project-structure.md § Boundaries).

A document is an entry, not a second copy of a result: deleting one deletes the entry, and
the job and its output stay in the parse history that billed for them (docs/database.md
§ Rules).
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import FormData, UploadFile

from ..auth.deps import AppSettings, CsrfGuard, DbSession, SessionUser
from ..db.models import Document, Folder, Job, Result
from ..errors import ApiError
from ..jobs.intake import submit_parse, upload_chunks
from ..jobs.runner import result_payload

router = APIRouter(prefix="/api/library", tags=["library"])

FOLDER_NAME_MAX = 255
DOCUMENT_NAME_MAX = 512
# How many " (2)" attempts a colliding name gets before the folder is simply too crowded.
NAME_ATTEMPTS = 500
# An insert can lose a name race with another tab; the retry re-reads the folder's names.
INSERT_ATTEMPTS = 3

# A name is a label in a tree, never a path. Separators would make a breadcrumb lie about
# where a file is, and control characters would make two different names look identical.
UNSAFE_IN_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")


# --- names and places -------------------------------------------------------------------


def clean_name(raw: str, limit: int) -> str:
    """A display name: no separators, no control characters, trimmed and capped."""
    name = UNSAFE_IN_NAME.sub(" ", raw).strip()
    if not name:
        raise ApiError(400, "invalid_request", "A name is required")
    return name[:limit].strip()


def free_name(taken: set[str], name: str) -> str:
    """`report.pdf` → `report (2).pdf` when the folder already holds that name.

    A file system resolves a collision rather than refusing the copy, and the suffix goes
    before the extension so the file still opens as what it is (docs/web.md § Files).
    """
    if name not in taken:
        return name
    stem, dot, extension = name.rpartition(".")
    if not stem:
        # No extension at all, or a dotfile — the whole thing is the stem.
        stem, dot, extension = name, "", ""
    for index in range(2, NAME_ATTEMPTS):
        candidate = f"{stem} ({index}){dot}{extension}"
        if candidate not in taken:
            return candidate
    raise ApiError(400, "invalid_request", "Too many items with this name in one folder")


def placed_in(column: ColumnElement, place: int | None) -> ColumnElement[bool]:
    """`folder_id = 3`, or `folder_id IS NULL` for the root."""
    return column.is_(None) if place is None else column == place


async def folder_names(
    db: DbSession, user_id: int, parent_id: int | None, exclude_id: int | None = None
) -> set[str]:
    query = select(Folder.name).where(
        Folder.user_id == user_id, placed_in(Folder.parent_id, parent_id)
    )
    if exclude_id is not None:
        query = query.where(Folder.id != exclude_id)
    return set((await db.execute(query)).scalars().all())


async def document_names(
    db: DbSession, user_id: int, folder_id: int | None, exclude_id: int | None = None
) -> set[str]:
    query = select(Document.name).where(
        Document.user_id == user_id, placed_in(Document.folder_id, folder_id)
    )
    if exclude_id is not None:
        query = query.where(Document.id != exclude_id)
    return set((await db.execute(query)).scalars().all())


async def owned_folder(db: DbSession, user_id: int, folder_id: int) -> Folder:
    row = (
        await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "invalid_request", "No such folder")
    return row


async def owned_document(db: DbSession, user_id: int, document_id: int) -> Document:
    row = (
        await db.execute(
            select(Document).where(Document.id == document_id, Document.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "invalid_request", "No such document")
    return row


async def subtree_ids(db: DbSession, user_id: int, root_id: int) -> set[int]:
    """`root_id` and every folder under it.

    Walked in Python over the account's own (id, parent_id) pairs rather than with a
    recursive CTE: a library is a handful of rows, and this is the same walk on PostgreSQL
    and on the SQLite test fallback.
    """
    pairs = (
        await db.execute(select(Folder.id, Folder.parent_id).where(Folder.user_id == user_id))
    ).all()
    children: dict[int | None, list[int]] = {}
    for folder_id, parent_id in pairs:
        children.setdefault(parent_id, []).append(folder_id)

    found = {root_id}
    frontier = [root_id]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            if child not in found:
                found.add(child)
                frontier.append(child)
    return found


async def commit_or_conflict(db: DbSession, message: str) -> None:
    """Commit, mapping a lost name race to the same 409 the pre-check would have given."""
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ApiError(409, "invalid_request", message) from exc


# --- payloads ---------------------------------------------------------------------------


def folder_payload(row: Folder) -> dict:
    return {
        "id": row.id,
        "parent_id": row.parent_id,
        "name": row.name,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def document_payload(row: Document, job: Job) -> dict:
    """The row the file list draws: the entry, plus the live state of its parse.

    Joined rather than fetched per row, so one `GET /api/library` renders every name,
    status and progress bar the page needs (docs/web.md § Files).
    """
    return {
        "id": row.id,
        "folder_id": row.folder_id,
        "name": row.name,
        "job_id": str(row.job_id),
        "status": job.status,
        "kind": job.kind,
        "model": job.model,
        "page_count": job.page_count,
        "pages_done": job.pages_done,
        "size_bytes": job.size_bytes,
        "error": job.error,
        "created_at": row.created_at,
        "finished_at": job.finished_at,
    }


async def job_of(db: DbSession, job_id: uuid.UUID) -> Job:
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "invalid_request", "No such job")
    return job


# --- read ---------------------------------------------------------------------------------


@router.get("")
async def read_library(user: SessionUser, db: DbSession):
    """The whole library in one read — navigation between folders is then local."""
    folders = (
        (await db.execute(select(Folder).where(Folder.user_id == user.id).order_by(Folder.name)))
        .scalars()
        .all()
    )
    documents = (
        await db.execute(
            select(Document, Job)
            .join(Job, Job.id == Document.job_id)
            .where(Document.user_id == user.id)
            .order_by(Document.created_at.desc())
        )
    ).all()
    return {
        "folders": [folder_payload(row) for row in folders],
        "documents": [document_payload(row, job) for row, job in documents],
    }


# --- folders ------------------------------------------------------------------------------


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=FOLDER_NAME_MAX)
    parent_id: int | None = None


class FolderUpdate(BaseModel):
    """Partial: only the fields present in the body change (docs/api.md)."""

    name: str | None = Field(default=None, min_length=1, max_length=FOLDER_NAME_MAX)
    parent_id: int | None = None


@router.post("/folders", dependencies=[CsrfGuard], status_code=status.HTTP_201_CREATED)
async def create_folder(body: FolderCreate, user: SessionUser, db: DbSession):
    if body.parent_id is not None:
        await owned_folder(db, user.id, body.parent_id)
    wanted = clean_name(body.name, FOLDER_NAME_MAX)
    name = free_name(await folder_names(db, user.id, body.parent_id), wanted)
    row = Folder(user_id=user.id, parent_id=body.parent_id, name=name)
    db.add(row)
    await commit_or_conflict(db, "A folder with this name already exists here")
    return folder_payload(row)


@router.put("/folders/{folder_id}", dependencies=[CsrfGuard])
async def update_folder(folder_id: int, body: FolderUpdate, user: SessionUser, db: DbSession):
    """Rename, move, or both.

    A rename that collides is refused: the name is what the user just typed, and quietly
    turning it into "Invoices (2)" would be a lie. A move that collides is suffixed, the
    way dropping a file into a folder that already holds one behaves.
    """
    row = await owned_folder(db, user.id, folder_id)
    provided = body.model_fields_set
    parent_id = body.parent_id if "parent_id" in provided else row.parent_id

    if parent_id != row.parent_id and parent_id is not None:
        await owned_folder(db, user.id, parent_id)
        if parent_id in await subtree_ids(db, user.id, row.id):
            raise ApiError(400, "invalid_request", "A folder cannot be moved inside itself")

    renaming = "name" in provided and body.name is not None
    wanted = clean_name(body.name, FOLDER_NAME_MAX) if renaming else row.name
    taken = await folder_names(db, user.id, parent_id, exclude_id=row.id)
    if renaming and wanted in taken:
        raise ApiError(409, "invalid_request", "A folder with this name already exists here")

    row.parent_id = parent_id
    row.name = free_name(taken, wanted)
    await commit_or_conflict(db, "A folder with this name already exists here")
    return folder_payload(row)


@router.delete(
    "/folders/{folder_id}", dependencies=[CsrfGuard], status_code=status.HTTP_204_NO_CONTENT
)
async def delete_folder(folder_id: int, user: SessionUser, db: DbSession) -> Response:
    """Delete a folder and its subtree — the documents in it are entries, so they go too.

    The subtree is deleted explicitly rather than left to `ON DELETE CASCADE`: the same
    rows disappear on PostgreSQL and on the SQLite test fallback, which does not enforce
    foreign keys unless asked to.
    """
    row = await owned_folder(db, user.id, folder_id)
    doomed = await subtree_ids(db, user.id, row.id)
    await db.execute(
        delete(Document).where(Document.user_id == user.id, Document.folder_id.in_(doomed))
    )
    await db.execute(delete(Folder).where(Folder.user_id == user.id, Folder.id.in_(doomed)))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- documents ----------------------------------------------------------------------------


class DocumentUpdate(BaseModel):
    """Partial: only the fields present in the body change (docs/api.md)."""

    name: str | None = Field(default=None, min_length=1, max_length=DOCUMENT_NAME_MAX)
    folder_id: int | None = None


def form_folder_id(form: FormData) -> int | None:
    """`folder_id` as a multipart field: absent or empty means the root."""
    raw = form.get("folder_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "'folder_id' must be a folder id") from exc


@router.post("/documents", dependencies=[CsrfGuard], status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request, user: SessionUser, db: DbSession, settings: AppSettings
):
    """The web upload: multipart `file` (+ optional `folder_id`) → a parse and a file.

    Transport only. The bytes stream to disk through `jobs.intake`, exactly as they do for
    `POST /v1/parse`; what this route adds is the name and the place (docs/api.md § Why the
    web upload is a control-plane route).
    """
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise ApiError(400, "invalid_request", "The upload must be multipart/form-data")
    # Cheap rejection before a byte is read; `store_upload` enforces the real cap while
    # streaming, for a request that declares no length.
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > settings.upload_max_bytes * 2:
        raise ApiError(413, "invalid_request", "The upload exceeds UPLOAD_MAX_BYTES")

    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise ApiError(400, "invalid_request", "Multipart requests need a 'file' part")
    folder_id = form_folder_id(form)
    if folder_id is not None:
        await owned_folder(db, user.id, folder_id)

    filename = upload.filename or "upload"
    submission = await submit_parse(
        db,
        settings,
        user=user,
        chunks=upload_chunks(upload),
        media_type=upload.content_type or "",
        filename=filename,
    )
    # A dedup hit is a finished parse rather than a new one, so the file points at the job
    # that already produced it (docs/jobs.md § Dedup).
    job_id = submission.job.id if submission.job is not None else submission.cached.job_id

    wanted = clean_name(filename, DOCUMENT_NAME_MAX)
    for attempt in range(INSERT_ATTEMPTS):
        row = Document(
            user_id=user.id,
            folder_id=folder_id,
            job_id=job_id,
            name=free_name(await document_names(db, user.id, folder_id), wanted),
        )
        db.add(row)
        try:
            await db.commit()
            break
        except IntegrityError as exc:
            # Another tab claimed the name between the read above and this commit. The job
            # is already committed and running, so the file has to land: re-read and retry.
            await db.rollback()
            if attempt == INSERT_ATTEMPTS - 1:
                raise ApiError(
                    409, "invalid_request", "A file with this name already exists here"
                ) from exc

    return document_payload(row, await job_of(db, job_id))


@router.put("/documents/{document_id}", dependencies=[CsrfGuard])
async def update_document(document_id: int, body: DocumentUpdate, user: SessionUser, db: DbSession):
    """Rename and/or move a file. Same rule as a folder: rename refuses, move suffixes."""
    row = await owned_document(db, user.id, document_id)
    provided = body.model_fields_set
    folder_id = body.folder_id if "folder_id" in provided else row.folder_id
    if folder_id != row.folder_id and folder_id is not None:
        await owned_folder(db, user.id, folder_id)

    renaming = "name" in provided and body.name is not None
    wanted = clean_name(body.name, DOCUMENT_NAME_MAX) if renaming else row.name
    taken = await document_names(db, user.id, folder_id, exclude_id=row.id)
    if renaming and wanted in taken:
        raise ApiError(409, "invalid_request", "A file with this name already exists here")

    row.folder_id = folder_id
    row.name = free_name(taken, wanted)
    await commit_or_conflict(db, "A file with this name already exists here")
    return document_payload(row, await job_of(db, row.job_id))


@router.delete(
    "/documents/{document_id}", dependencies=[CsrfGuard], status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(document_id: int, user: SessionUser, db: DbSession) -> Response:
    """Remove the file from the library. The parse itself stays in the history."""
    row = await owned_document(db, user.id, document_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}/result")
async def document_result(document_id: int, user: SessionUser, db: DbSession):
    row = await owned_document(db, user.id, document_id)
    result = (
        await db.execute(select(Result).where(Result.job_id == row.job_id))
    ).scalar_one_or_none()
    if result is None:
        raise ApiError(404, "invalid_request", "This job has no result yet")
    return result_payload(result)
