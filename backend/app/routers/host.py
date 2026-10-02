"""
Course-host management API (T4, spec §4.8). Mounted at /api/host.

URLs are flat (/host/games/{id}, /host/sessions/{id}) and every endpoint goes
through a require_*_host dependency that loads the resource and checks the
course it belongs to — never a course ID taken from the URL alongside it.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from redis.asyncio import Redis
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import (
    require_course_host,
    require_game_host,
    require_question_host,
    require_session_host,
    require_user,
)
from ..common.exceptions import BuzzerError
from ..database import get_db
from ..models.course import Course, CourseRoster
from ..models.game import Game, Question
from ..models.session import GameSession, SessionScore
from ..models.user import User
from ..redis_client import get_redis
from ..schemas.admin import (
    GameResponse,
    QuestionCreate,
    QuestionReorder,
    QuestionResponse,
    QuestionUpdate,
    RosterEntryResponse,
    RosterUploadResult,
)
from ..schemas.host import (
    HostGameCreate,
    HostGameListItem,
    HostGameUpdate,
    RosterUploadMode,
    SessionListItem,
)
from ..services import access_service as access
from ..services import question_service
from ..services import state_service as state
from ..services.export_service import build_session_csv
from ..services.report_service import build_session_report
from ..services.roster_service import process_roster_csv

router = APIRouter(prefix="/host", tags=["host"])
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


@router.get("/courses/{course_id}/games", response_model=list[HostGameListItem])
async def list_course_games(
    course: Annotated[Course, Depends(require_course_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Games of this course the caller can use (restricted ones only with a grant)."""
    games = (
        (
            await db.execute(
                access.usable_games_stmt(user, course.id).order_by(Game.title)
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await db.execute(
                select(Question.game_id, func.count())
                .where(Question.game_id.in_([g.id for g in games]))
                .group_by(Question.game_id)
            )
        ).all()
    )
    return [
        {
            **GameResponse.model_validate(g).model_dump(),
            "question_count": counts.get(g.id, 0),
        }
        for g in games
    ]


@router.post("/courses/{course_id}/games", response_model=GameResponse, status_code=201)
async def create_course_game(
    body: HostGameCreate,
    course: Annotated[Course, Depends(require_course_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Game:
    game = Game(
        title=body.title,
        description=body.description,
        max_players=body.max_players,
        course_id=course.id,
        restricted=False,
    )
    db.add(game)
    await db.flush()
    await db.refresh(game)
    logger.info(
        "host_game_created", game_id=game.id, course_id=course.id, user_id=user.id
    )
    return game


@router.get("/games/{game_id}", response_model=GameResponse)
async def get_game(game: Annotated[Game, Depends(require_game_host)]) -> Game:
    return game


@router.put("/games/{game_id}", response_model=GameResponse)
async def update_game(
    body: HostGameUpdate,
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Game:
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(game, field, value)
    await db.flush()
    return game


@router.delete("/games/{game_id}", status_code=204)
async def delete_game(
    game: Annotated[Game, Depends(require_game_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    """
    Hosts never delete recorded results: any COMPLETED session, or any session
    with at least one answer, blocks the delete (admins can still delete).
    Score-less sessions (LOBBY, ABANDONED, stale IN_PROGRESS) are removed,
    Redis first. Questions and UserGameAccess grants cascade with the game.
    """
    sessions = (
        (await db.execute(select(GameSession).where(GameSession.game_id == game.id)))
        .scalars()
        .all()
    )
    session_ids = [s.id for s in sessions]
    has_scores = (
        session_ids
        and (
            await db.execute(
                select(exists().where(SessionScore.session_id.in_(session_ids)))
            )
        ).scalar()
    )
    if any(s.status == "COMPLETED" for s in sessions) or has_scores:
        raise BuzzerError(
            "GAME_HAS_RESULTS",
            "Games with recorded results can only be deleted by an admin",
            409,
        )

    for s in sessions:
        await state.delete_room_state(redis, s.room_code, s.id)
    if session_ids:
        await db.execute(delete(GameSession).where(GameSession.id.in_(session_ids)))
    await db.delete(game)
    await db.flush()
    logger.info(
        "host_game_deleted",
        game_id=game.id,
        user_id=user.id,
        sessions_deleted=len(session_ids),
    )


# ---------------------------------------------------------------------------
# Questions (shared logic in question_service; hosts see answer_data to edit
# scoring)
# ---------------------------------------------------------------------------


@router.get("/games/{game_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Question]:
    return await question_service.list_questions(db, game)


@router.post(
    "/games/{game_id}/questions", response_model=QuestionResponse, status_code=201
)
async def create_question(
    body: QuestionCreate,
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Question:
    return await question_service.create_question(db, game, body)


@router.post("/games/{game_id}/questions/reorder", status_code=204)
async def reorder_questions(
    body: QuestionReorder,
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await question_service.reorder_questions(db, game, body.order)


@router.put("/games/{game_id}/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    body: QuestionUpdate,
    question: Annotated[Question, Depends(require_question_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Question:
    return await question_service.update_question(db, question, body)


@router.delete("/games/{game_id}/questions/{question_id}", status_code=204)
async def delete_question(
    question: Annotated[Question, Depends(require_question_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await question_service.delete_question(db, question)


# ---------------------------------------------------------------------------
# Roster. Hosts upload only the Canvas gradebook CSV (process_roster_csv); the
# admin column-mapping import stays admin-only. Roster rows never touch
# UserCourseAccess (PLAYER/HOST grants stay admin-only).
# ---------------------------------------------------------------------------


@router.get("/courses/{course_id}/roster", response_model=list[RosterEntryResponse])
async def list_roster(
    course: Annotated[Course, Depends(require_course_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CourseRoster]:
    """Active and inactive entries."""
    result = await db.execute(
        select(CourseRoster)
        .where(CourseRoster.course_id == course.id)
        .order_by(CourseRoster.full_name)
    )
    return list(result.scalars().all())


@router.post("/courses/{course_id}/roster", response_model=RosterUploadResult)
async def upload_roster(
    file: Annotated[UploadFile, File(description="Canvas gradebook CSV export")],
    course: Annotated[Course, Depends(require_course_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    mode: Annotated[RosterUploadMode, Form()] = "add_update",
) -> RosterUploadResult:
    result = await process_roster_csv(db, course.id, await file.read(), mode)
    logger.info("host_roster_uploaded", course_id=course.id, user_id=user.id, mode=mode)
    return result


# ---------------------------------------------------------------------------
# Sessions and results. Sessions belong to the course they were played in
# (session.course_id), whichever host ran them.
# ---------------------------------------------------------------------------

SessionStatus = Literal["LOBBY", "IN_PROGRESS", "COMPLETED", "ABANDONED"]


@router.get("/courses/{course_id}/sessions", response_model=list[SessionListItem])
async def list_sessions(
    course: Annotated[Course, Depends(require_course_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[SessionStatus | None, Query()] = None,
) -> list[dict]:
    """Newest first; sessions of restricted games the caller has no grant on are omitted."""
    stmt = (
        select(GameSession, Game.title, Course.name, Course.semester, User)
        .join(Game, Game.id == GameSession.game_id)
        .join(Course, Course.id == GameSession.course_id)
        .outerjoin(User, User.id == GameSession.host_user_id)
        .where(GameSession.course_id == course.id)
        .order_by(GameSession.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(GameSession.status == status)
    rows = (await db.execute(access.without_ungranted_restricted(stmt, user))).all()

    counts = dict(
        (
            await db.execute(
                select(
                    SessionScore.session_id,
                    func.count(SessionScore.user_id.distinct()),
                )
                .where(SessionScore.session_id.in_([r[0].id for r in rows]))
                .group_by(SessionScore.session_id)
            )
        ).all()
    )
    return [
        {
            "session_id": s.id,
            "room_code": s.room_code,
            "status": s.status,
            "game_id": s.game_id,
            "game_title": title,
            "course_id": s.course_id,
            "course_name": course_name,
            "course_semester": semester,
            "host_display_name": (host.display_name or host.username or host.netid)
            if host
            else None,
            "created_at": s.created_at,
            "completed_at": s.completed_at,
            "player_count": counts.get(s.id, 0),
        }
        for s, title, course_name, semester, host in rows
    ]


def _require_completed(session: GameSession) -> None:
    if session.status != "COMPLETED":
        raise BuzzerError(
            "SESSION_NOT_COMPLETED",
            "Results are available once the session is completed",
            409,
        )


@router.get("/sessions/{session_id}/export")
async def export_session(
    session: Annotated[GameSession, Depends(require_session_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Per-player score CSV (Player, Q1..Qn, Total)."""
    _require_completed(session)
    filename, content = await build_session_csv(db, session.id)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sessions/{session_id}/report")
async def session_report(
    session: Annotated[GameSession, Depends(require_session_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Standalone HTML summary (aggregate stats, no player names)."""
    _require_completed(session)
    filename, content = await build_session_report(db, session.id)
    return Response(
        content=content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
