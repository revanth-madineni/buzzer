"""
Course-host management API (T4, spec §4.8). Mounted at /api/host.

URLs are flat (/host/games/{id}, /host/sessions/{id}) and every endpoint goes
through a require_*_host dependency that loads the resource and checks the
course it belongs to — never a course ID taken from the URL alongside it.
"""

from __future__ import annotations

from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from redis.asyncio import Redis
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import (
    require_course_host,
    require_game_host,
    require_image_host,
    require_question_host,
    require_session_host,
    require_user,
)
from ..common.exceptions import BuzzerError
from ..common.rate_limit import limiter
from ..database import get_db
from ..models.course import Course, CourseRoster
from ..models.game import Game, Question
from ..models.image import Image
from ..models.session import GameSession, SessionScore
from ..models.user import User
from ..redis_client import get_redis
from ..schemas.admin import (
    GameResponse,
    ImageAltUpdate,
    ImageListItem,
    ImageResponse,
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
from ..services import game_service, image_service, question_service
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
    await db.commit()
    return game


@router.get("/games/{game_id}", response_model=GameResponse)
async def get_game(game: Annotated[Game, Depends(require_game_host)]) -> Game:
    return game


async def _guard_write(db: AsyncSession, redis: Redis, game_id: int) -> Game:
    """Game-row lock, then 409 GAME_LIVE if the game is being played (§4.5).
    Returns the freshly locked game."""
    game = await game_service.lock_game(db, game_id)
    await game_service.assert_not_live(db, redis, game_id)
    return game


@router.put("/games/{game_id}", response_model=GameResponse)
async def update_game(
    body: HostGameUpdate,
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Game:
    await _guard_write(db, redis, game.id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(game, field, value)
    await db.flush()
    await db.commit()
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
    with at least one answer, blocks the delete (admins can still delete). Then
    a live game is 409 GAME_LIVE. Score-less sessions (LOBBY, ABANDONED, stale
    IN_PROGRESS) are removed, Redis first. Questions and UserGameAccess grants
    cascade with the game.
    """
    await game_service.lock_game(db, game.id)
    # Locking reads after the lock (REPEATABLE READ, §4.5).
    sessions = (
        (
            await db.execute(
                select(GameSession)
                .where(GameSession.game_id == game.id)
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    session_ids = [s.id for s in sessions]
    has_scores = (
        session_ids
        and (
            await db.execute(
                select(
                    exists().where(SessionScore.session_id.in_(session_ids))
                ).with_for_update(read=True)
            )
        ).scalar()
    )
    if any(s.status == "COMPLETED" for s in sessions) or has_scores:
        raise BuzzerError(
            "GAME_HAS_RESULTS",
            "Games with recorded results can only be deleted by an admin",
            409,
        )
    await game_service.assert_not_live(db, redis, game.id)

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
    await db.commit()


# ---------------------------------------------------------------------------
# Questions (shared logic in question_service; hosts see answer_data to edit
# scoring). Every write is guarded against live games.
# ---------------------------------------------------------------------------


@router.get("/games/{game_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[QuestionResponse]:
    questions = await question_service.list_questions(db, game)
    return await question_service.question_responses(db, questions)


@router.post(
    "/games/{game_id}/questions", response_model=QuestionResponse, status_code=201
)
async def create_question(
    body: QuestionCreate,
    game: Annotated[Game, Depends(require_game_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> QuestionResponse:
    locked = await _guard_write(db, redis, game.id)
    question = await question_service.create_question(db, locked, body, user)
    await db.commit()
    return (await question_service.question_responses(db, [question]))[0]


@router.post("/games/{game_id}/questions/reorder", status_code=204)
async def reorder_questions(
    body: QuestionReorder,
    game: Annotated[Game, Depends(require_game_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    await _guard_write(db, redis, game.id)
    await question_service.reorder_questions(db, game, body.order)
    await db.commit()


@router.put("/games/{game_id}/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    body: QuestionUpdate,
    question: Annotated[Question, Depends(require_question_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> QuestionResponse:
    locked = await _guard_write(db, redis, question.game_id)
    updated = await question_service.update_question(db, locked, question, body, user)
    await db.commit()
    return (await question_service.question_responses(db, [updated]))[0]


@router.delete("/games/{game_id}/questions/{question_id}", status_code=204)
async def delete_question(
    question: Annotated[Question, Depends(require_question_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    await _guard_write(db, redis, question.game_id)
    await question_service.delete_question(db, question)
    await db.commit()


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
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Images (T7 upload; T8 list, alt text, delete, replace). Uploads are stored
# against the course in the URL. Upload, alt text and delete need no live-game
# guard; replace locks and checks every affected game itself.
# ---------------------------------------------------------------------------


@router.post(
    "/courses/{course_id}/images", response_model=ImageResponse, status_code=201
)
@limiter.limit("30/minute")
async def upload_image(
    request: Request,
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP, at most 2 MB")],
    course: Annotated[Course, Depends(require_course_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    alt_text: Annotated[str | None, Form()] = None,
) -> Image:
    alt = image_service.clean_alt_text(alt_text)
    image = await image_service.store_image(db, await file.read(), user, course.id, alt)
    # Commit before responding: get_db's commit runs after the response is sent, so a
    # client that GETs the image right after the 201 could otherwise get a 404.
    await db.commit()
    logger.info(
        "host_image_uploaded", image_id=image.id, course_id=course.id, user_id=user.id
    )
    return image


@router.get("/courses/{course_id}/images", response_model=list[ImageListItem])
async def list_images(
    course: Annotated[Course, Depends(require_course_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """The course's images; uses in games the caller can't use are only counted."""
    return await image_service.list_images(db, user, course_id=course.id)


@router.patch("/images/{image_id}", response_model=ImageResponse)
async def update_image(
    body: ImageAltUpdate,
    image: Annotated[Image, Depends(require_image_host)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Image:
    await image_service.set_alt_text(db, image, body.alt_text)
    await db.commit()
    return image


@router.delete("/images/{image_id}", status_code=204)
async def delete_image(
    image: Annotated[Image, Depends(require_image_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await image_service.delete_image(db, image, user)
    await db.commit()


@router.post(
    "/images/{image_id}/replace", response_model=ImageResponse, status_code=201
)
@limiter.limit("30/minute")
async def replace_image(
    request: Request,
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP, at most 2 MB")],
    image: Annotated[Image, Depends(require_image_host)],
    user: Annotated[User, Depends(require_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    alt_text: Annotated[str | None, Form()] = None,
) -> Image:
    """403 FORBIDDEN if any use is in a game the caller can't use (§4.5)."""
    alt = None if alt_text is None else image_service.clean_alt_text(alt_text)
    new = await image_service.replace_image(
        db, redis, image, await file.read(), alt, user
    )
    await db.commit()
    return new


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
