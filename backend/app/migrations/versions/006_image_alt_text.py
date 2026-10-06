"""Alt text on images (T8)

Revision ID: 006
Revises: 005
Create Date: 2026-10-06

Image bytes stay immutable. `alt_text` is descriptive and editable in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "images",
        sa.Column("alt_text", sa.String(250), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("images", "alt_text")
