from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import Cookie, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from ..database import get_db
from ..models.course import Course
from ..models.game import Game, Question
from ..models.session import GameSession
from ..models.user import User
from ..services import access_service as access
from ..services.auth_service import decode_token, get_user_by_id

logger = structlog.get_logger()

_bearer = HTTPBearer(auto_error=False)


async def _token_from_request(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    access_token: Annotated[str | None, Cookie()] = None,
) -> str | None:
    """Extract JWT from Authorization header or access_token cookie."""
    if credentials:
        return credentials.credentials
    return access_token


async def get_current_user(
    token: Annotated[str | None, Depends(_token_from_request)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not token:
        raise UnauthorizedError("Authentication required")
    try:
        payload = decode_token(token)
    except JWTError:
        raise UnauthorizedError("Invalid or expired token")

    token_type = payload.get("token_type")
    if token_type not in ("access", "temp"):
        raise UnauthorizedError("Invalid token type")

    user = await get_user_by_id(db, payload["sub"])
    if not user:
        raise UnauthorizedError("User not found")
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != "ADMIN":
        raise ForbiddenError("Admin access required")
    return user


async def require_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Allow ADMIN and USER roles; reject GUEST."""
    if user.role == "GUEST":
        raise ForbiddenError("Authenticated account required")
    return user


# ---------------------------------------------------------------------------
# Course-host access (T4). Each loads the resource first and checks the course it
# belongs to, never a course ID taken from the URL. Order: 404 → 403 FORBIDDEN →
# 403 GAME_RESTRICTED. require_user runs first (401, GUEST 403).
# ---------------------------------------------------------------------------


async def require_course_host(
    course_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Course:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    if not await access.has_course_host(db, user, course.id):
        raise ForbiddenError(access.COURSE_HOST_REQUIRED)
    return course


async def require_game_host(
    game_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Game:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    await access.assert_can_use_game(db, user, game)
    return game


async def require_question_host(
    question_id: int,
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Question:
    question = await db.get(Question, question_id)
    if not question or question.game_id != game.id:
        raise NotFoundError(f"Question {question_id} not found")
    return question


async def require_session_host(
    session_id: str,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GameSession:
    session = await db.get(GameSession, session_id)
    if not session:
        raise NotFoundError(f"Session {session_id} not found")
    game = await db.get(Game, session.game_id)
    await access.assert_can_view_session_results(db, user, session, game)
    return session


async def get_refresh_token(
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> str:
    if not refresh_token:
        raise UnauthorizedError("No refresh token")
    return refresh_token
