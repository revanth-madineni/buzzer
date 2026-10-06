from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Image(Base):
    """An uploaded image (T7 map pin, T8 prompts and options).

    Bytes and dimensions are immutable: "replace" uploads a new row and re-points
    questions. Only `alt_text` (descriptive) and `course_id` (ownership, re-tagged when
    a game moves, T8 §4.7a) are updated in place; neither affects geometry.

    `data` is deferred so metadata queries never load the bytes. No relationships to
    User/Course, so there is no cascade to reason about; questions reference images by
    ID inside their JSON `config`, not by FK.
    """

    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[bytes] = mapped_column(
        LargeBinary().with_variant(MEDIUMBLOB(), "mysql"),
        nullable=False,
        deferred=True,
    )
    uploaded_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    course_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    alt_text: Mapped[str] = mapped_column(
        String(250), nullable=False, server_default=""
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
