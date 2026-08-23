"""library folders and documents

Revision ID: 5192e8e8b401
Revises: bcbf4eedb39c
Create Date: 2026-08-23 17:55:01.215727
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5192e8e8b401"
down_revision: str | None = "bcbf4eedb39c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "parent_id", "name", name="uq_folders_parent_name"),
    )
    op.create_index("ix_folders_user_id", "folders", ["user_id"], unique=False)
    # NULL is the root, and NULLs are distinct to a unique constraint, so without this
    # partial index one account could hold two root folders of the same name
    # (docs/database.md § Rules).
    op.create_index(
        "uq_folders_root_name",
        "folders",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
        sqlite_where=sa.text("parent_id IS NULL"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "folder_id", "name", name="uq_documents_folder_name"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"], unique=False)
    op.create_index(
        "ix_documents_user_created", "documents", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_documents_root_name",
        "documents",
        ["user_id", "name"],
        unique=True,
        postgresql_where=sa.text("folder_id IS NULL"),
        sqlite_where=sa.text("folder_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_documents_root_name", table_name="documents")
    op.drop_index("ix_documents_user_created", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("uq_folders_root_name", table_name="folders")
    op.drop_index("ix_folders_user_id", table_name="folders")
    op.drop_table("folders")
