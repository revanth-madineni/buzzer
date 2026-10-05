"""Images table for map-pin questions (T7)

Revision ID: 005
Revises: 004
Create Date: 2026-10-04

Images are immutable. Questions reference them by ID inside their JSON `config`,
so there is no FK from `questions`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mime_type", sa.String(32), nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        # Plain BLOB caps at 64 KB; images go up to 2 MB.
        sa.Column("data", mysql.MEDIUMBLOB(), nullable=False),
        sa.Column(
            "uploaded_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "course_id",
            sa.Integer,
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_images_sha256", "images", ["sha256"])


def downgrade() -> None:
    op.drop_table("images")
