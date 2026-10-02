"""Course-specific games: games.course_id, games.restricted, courses.allow_guests

Revision ID: 004
Revises: 003
Create Date: 2026-10-01

Backfill (not reversible):
- games.course_id = course with the most COMPLETED sessions of the game (ties: most
  recent created_at, then highest session id). A game with no COMPLETED sessions gets
  the single course its grant holders host, or NULL if they host zero or several.
- Every existing game is set restricted, so no host gains access to a game they could
  not use before; admins un-restrict deliberately.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("games", sa.Column("course_id", sa.Integer, nullable=True))
    op.create_index("ix_games_course_id", "games", ["course_id"])
    op.create_foreign_key(
        "fk_games_course_id_courses", "games", "courses", ["course_id"], ["id"]
    )
    op.add_column(
        "games",
        sa.Column("restricted", sa.Boolean, nullable=False, server_default="0"),
    )
    op.add_column(
        "courses",
        sa.Column("allow_guests", sa.Boolean, nullable=False, server_default="1"),
    )

    _backfill_course_id()
    op.execute("UPDATE games SET restricted = 1")


def _backfill_course_id() -> None:
    bind = op.get_bind()
    assignments: dict[int, int] = {}

    # Games with COMPLETED sessions: pick the course maximising (n, last, maxid).
    completed = bind.execute(
        sa.text(
            "SELECT game_id, course_id, COUNT(*) AS n, MAX(created_at) AS last, "
            "MAX(id) AS maxid FROM game_sessions WHERE status = 'COMPLETED' "
            "GROUP BY game_id, course_id"
        )
    ).all()
    best: dict[int, tuple] = {}
    for game_id, course_id, n, last, maxid in completed:
        key = (n, last, maxid)
        if game_id not in best or key > best[game_id][0]:
            best[game_id] = (key, course_id)
    for game_id, (_, course_id) in best.items():
        assignments[game_id] = course_id

    # Remaining games: the single course that their grant holders host, if exactly one.
    holder_courses = bind.execute(
        sa.text(
            "SELECT DISTINCT uga.game_id, uca.course_id FROM user_game_access uga "
            "JOIN user_course_access uca "
            "ON uca.user_id = uga.user_id AND uca.role = 'HOST'"
        )
    ).all()
    host_courses: dict[int, set[int]] = {}
    for game_id, course_id in holder_courses:
        host_courses.setdefault(game_id, set()).add(course_id)
    for game_id, courses in host_courses.items():
        if game_id not in assignments and len(courses) == 1:
            assignments[game_id] = next(iter(courses))

    if assignments:
        bind.execute(
            sa.text("UPDATE games SET course_id = :course_id WHERE id = :game_id"),
            [{"game_id": g, "course_id": c} for g, c in assignments.items()],
        )


def downgrade() -> None:
    op.drop_constraint("fk_games_course_id_courses", "games", type_="foreignkey")
    op.drop_index("ix_games_course_id", table_name="games")
    op.drop_column("games", "course_id")
    op.drop_column("games", "restricted")
    op.drop_column("courses", "allow_guests")
