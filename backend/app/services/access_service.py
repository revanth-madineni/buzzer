"""
Course-host access rules (T4). The one place that decides whether a user may
author/run a game or read a session's results.

A non-admin may use game G iff they hold course HOST on G.course_id and, if G is
restricted, also hold a UserGameAccess grant on G. Admins bypass everything.
Session results follow the course the session was played in (session.course_id),
not the game's current course.
"""

from __future__ import annotations

from sqlalchemy import Select, and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import BuzzerError, ForbiddenError, NotFoundError
from ..models.course import UserCourseAccess
from ..models.game import Game, UserGameAccess
from ..models.session import GameSession
from ..models.user import User

COURSE_HOST_REQUIRED = "You do not have HOST access to this course"


class GameRestrictedError(BuzzerError):
    def __init__(self) -> None:
        super().__init__("GAME_RESTRICTED", "This game is restricted", 403)


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


async def has_course_host(db: AsyncSession, user: User, course_id: int) -> bool:
    if user.role == "ADMIN":
        return True
    result = await db.execute(
        select(
            exists().where(
                UserCourseAccess.user_id == user.id,
                UserCourseAccess.course_id == course_id,
                UserCourseAccess.role == "HOST",
            )
        )
    )
    return bool(result.scalar())


async def has_game_grant(db: AsyncSession, user: User, game_id: int) -> bool:
    result = await db.execute(
        select(
            exists().where(
                UserGameAccess.user_id == user.id,
                UserGameAccess.game_id == game_id,
            )
        )
    )
    return bool(result.scalar())


async def can_use_game(db: AsyncSession, user: User, game: Game) -> bool:
    """Authoring and running a game."""
    if user.role == "ADMIN":
        return True
    if game.course_id is None:
        return False
    if not await has_course_host(db, user, game.course_id):
        return False
    return not game.restricted or await has_game_grant(db, user, game.id)


async def can_view_session_results(
    db: AsyncSession, user: User, session: GameSession, game: Game
) -> bool:
    """Exports and reports. Checks HOST on the session's course, not the game's."""
    if user.role == "ADMIN":
        return True
    if not await has_course_host(db, user, session.course_id):
        return False
    return not game.restricted or await has_game_grant(db, user, game.id)


# ---------------------------------------------------------------------------
# Raising checks (spec §4.0 error precedence: 404 → FORBIDDEN → GAME_RESTRICTED)
# ---------------------------------------------------------------------------


async def assert_can_use_game(db: AsyncSession, user: User, game: Game) -> None:
    if user.role == "ADMIN":
        return
    if game.course_id is None:
        raise NotFoundError(f"Game {game.id} not found")
    if not await has_course_host(db, user, game.course_id):
        raise ForbiddenError(COURSE_HOST_REQUIRED)
    if game.restricted and not await has_game_grant(db, user, game.id):
        raise GameRestrictedError()


async def assert_can_view_session_results(
    db: AsyncSession, user: User, session: GameSession, game: Game
) -> None:
    if user.role == "ADMIN":
        return
    if not await has_course_host(db, user, session.course_id):
        raise ForbiddenError(COURSE_HOST_REQUIRED)
    if game.restricted and not await has_game_grant(db, user, game.id):
        raise GameRestrictedError()


# ---------------------------------------------------------------------------
# Query form of can_use_game, for lists (one query, no per-game checks)
# ---------------------------------------------------------------------------


def usable_games_stmt(user: User, course_id: int | None = None) -> Select:
    """SELECT of the games `user` can use, optionally limited to one course."""
    stmt = select(Game)
    if course_id is not None:
        stmt = stmt.where(Game.course_id == course_id)
    if user.role == "ADMIN":
        return stmt
    return (
        stmt.join(
            UserCourseAccess,
            and_(
                UserCourseAccess.course_id == Game.course_id,
                UserCourseAccess.user_id == user.id,
                UserCourseAccess.role == "HOST",
            ),
        )
        .outerjoin(
            UserGameAccess,
            and_(
                UserGameAccess.game_id == Game.id,
                UserGameAccess.user_id == user.id,
            ),
        )
        .where(or_(Game.restricted.is_(False), UserGameAccess.user_id.is_not(None)))
    )


# ---------------------------------------------------------------------------
# Grant holders (admin Access page and game move)
# ---------------------------------------------------------------------------


async def grant_holders(
    db: AsyncSession, game_id: int, course_id: int | None
) -> list[tuple[User, bool]]:
    """
    Users with a UserGameAccess grant on the game, each paired with whether they
    hold HOST on `course_id` (has_course_host semantics: ADMIN counts as HOST).
    A grant whose holder lacks HOST has no effect. course_id None -> only admins.
    """
    result = await db.execute(
        select(User, UserCourseAccess.role)
        .join(UserGameAccess, UserGameAccess.user_id == User.id)
        .outerjoin(
            UserCourseAccess,
            and_(
                UserCourseAccess.user_id == User.id,
                UserCourseAccess.course_id == course_id,
                UserCourseAccess.role == "HOST",
            ),
        )
        .where(UserGameAccess.game_id == game_id)
        .order_by(User.username, User.netid, User.id)
    )
    return [(user, user.role == "ADMIN" or role is not None) for user, role in result]
