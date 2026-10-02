"""
Course-host management API (T4, spec §4.8). Mounted at /api/host.

URLs are flat (/host/games/{id}, /host/sessions/{id}) and every endpoint goes
through a require_*_host dependency that loads the resource and checks the
course it belongs to — never a course ID taken from the URL alongside it.
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import (
    require_course_host,
    require_game_host,
    require_question_host,
    require_user,
)
from ..database import get_db
from ..models.course import Course, CourseRoster
from ..models.game import Game, Question
from ..models.user import User
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
)
from ..services import access_service as access
from ..services import question_service
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
