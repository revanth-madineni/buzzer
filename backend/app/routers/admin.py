from __future__ import annotations

import io
import json
import uuid
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from redis.asyncio import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.dependencies import require_admin
from ..common.exceptions import ConflictError, NotFoundError
from ..common.rate_limit import limiter
from ..database import get_db
from ..models.course import Course, CourseRoster, UserCourseAccess
from ..models.game import Game, Question, UserGameAccess
from ..models.image import Image
from ..models.session import GameSession, SessionScore
from ..models.user import User
from ..redis_client import get_redis
from ..schemas.admin import (
    AdminSessionItem,
    CourseAccessEntry,
    CourseAccessGrant,
    CourseCreate,
    CourseResponse,
    CourseUpdate,
    GameAccessEntry,
    GameAccessGrant,
    GameCreate,
    GameFields,
    GameMoveRequest,
    GameMoveResult,
    GameResponse,
    GameUpdate,
    ImageResponse,
    QuestionCreate,
    QuestionReorder,
    QuestionResponse,
    QuestionUpdate,
    RosterEntryPatch,
    RosterEntryResponse,
    RosterImportPayload,
    RosterUploadResult,
    UserCreate,
    UserResponse,
    UserUpdate,
    UserWithAccessResponse,
)
from ..services import access_service as access
from ..services import game_service, image_service, question_service
from ..services.auth_service import hash_password
from ..services.export_service import build_canvas_csv, build_session_csv
from ..services.report_service import build_session_report
from ..services.roster_service import process_roster_csv, process_roster_rows

_SUPPORTED_IMPORT_VERSION = 1

router = APIRouter(prefix="/admin", tags=["admin"])
logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


@router.get("/courses", response_model=list[CourseResponse])
async def list_courses(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Course]:
    result = await db.execute(
        select(Course).order_by(Course.semester.desc(), Course.name)
    )
    return result.scalars().all()


@router.post("/courses", response_model=CourseResponse, status_code=201)
async def create_course(
    body: CourseCreate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Course:
    course = Course(
        name=body.name, semester=body.semester, allow_guests=body.allow_guests
    )
    db.add(course)
    await db.flush()
    await db.refresh(course)
    await db.commit()
    logger.info("course_created", course_id=course.id, name=body.name)
    return course


@router.get("/courses/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Course:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    return course


@router.put("/courses/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: int,
    body: CourseUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Course:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    if body.name is not None:
        course.name = body.name
    if body.semester is not None:
        course.semester = body.semester
    if body.allow_guests is not None:
        course.allow_guests = body.allow_guests
    return course


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


@router.get("/courses/{course_id}/roster", response_model=list[RosterEntryResponse])
async def list_roster(
    course_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CourseRoster]:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    result = await db.execute(
        select(CourseRoster)
        .where(CourseRoster.course_id == course_id)
        .order_by(CourseRoster.full_name)
    )
    return result.scalars().all()


@router.post("/courses/{course_id}/roster", response_model=RosterUploadResult)
async def upload_roster(
    course_id: int,
    file: Annotated[UploadFile, File(description="Canvas gradebook CSV export")],
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RosterUploadResult:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    content = await file.read()
    return await process_roster_csv(db, course_id, content)


@router.post("/courses/{course_id}/roster/import", response_model=RosterUploadResult)
async def import_roster_rows(
    course_id: int,
    payload: RosterImportPayload,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RosterUploadResult:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    rows = [
        {"netid": r.netid, "full_name": r.full_name, "email": r.email}
        for r in payload.rows
    ]
    result = await process_roster_rows(db, course_id, rows)
    await db.commit()
    return result


@router.patch(
    "/courses/{course_id}/roster/{roster_id}", response_model=RosterEntryResponse
)
async def patch_roster_entry(
    course_id: int,
    roster_id: int,
    body: RosterEntryPatch,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CourseRoster:
    result = await db.execute(
        select(CourseRoster).where(
            CourseRoster.id == roster_id,
            CourseRoster.course_id == course_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise NotFoundError(f"Roster entry {roster_id} not found in course {course_id}")
    if body.is_active is not None:
        entry.is_active = body.is_active
    if body.netid is not None:
        entry.netid = body.netid.strip().lower()
    if body.full_name is not None:
        entry.full_name = body.full_name.strip()
    if body.email is not None:
        entry.email = str(body.email).lower()
    return entry


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------


@router.get("/games", response_model=list[GameResponse])
async def list_games(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Game]:
    result = await db.execute(select(Game).order_by(Game.title))
    return result.scalars().all()


@router.post("/games", response_model=GameResponse, status_code=201)
async def create_game(
    body: GameCreate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Game:
    if body.course_id is not None and not await db.get(Course, body.course_id):
        raise NotFoundError(f"Course {body.course_id} not found")
    game = Game(
        title=body.title,
        description=body.description,
        max_players=body.max_players,
        course_id=body.course_id,
    )
    db.add(game)
    await db.flush()
    await db.refresh(game)
    await db.commit()
    logger.info("game_created", game_id=game.id, title=body.title)
    return game


@router.get("/games/{game_id}", response_model=GameResponse)
async def get_game(
    game_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Game:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    return game


@router.put("/games/{game_id}", response_model=GameResponse)
async def update_game(
    game_id: int,
    body: GameUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Game:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    if body.title is not None:
        game.title = body.title
    if body.description is not None:
        game.description = body.description
    if body.max_players is not None:
        game.max_players = body.max_players
    if body.restricted is not None:
        game.restricted = body.restricted
    return game


@router.delete("/games/{game_id}", status_code=204)
async def delete_game(
    game_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    # Nullify game_sessions references before delete — game_sessions.game_id is
    # NOT NULL so SQLAlchemy's default SET-NULL cascade would fail without this.
    from sqlalchemy import delete as sa_delete, select as sa_select
    from ..models.session import GameSession as _GS, SessionScore as _SS

    session_ids = (
        (await db.execute(sa_select(_GS.id).where(_GS.game_id == game_id)))
        .scalars()
        .all()
    )
    if session_ids:
        await db.execute(sa_delete(_SS).where(_SS.session_id.in_(session_ids)))
    await db.execute(sa_delete(_GS).where(_GS.game_id == game_id))
    await db.delete(game)


def _access_entry(user: User) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "netid": user.netid,
        "display_name": user.display_name,
    }


@router.post("/games/{game_id}/move", response_model=GameMoveResult)
async def move_game(
    game_id: int,
    body: GameMoveRequest,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict:
    """
    Assign a courseless game to a course, or move it to another one. Grants whose
    holder lacks HOST on the target course would stop working, so they are
    dropped. confirm=false only reports them (no writes); the UI shows them first.
    Existing sessions keep their own course_id; `restricted` is unchanged.
    """
    game = await game_service.lock_game(db, game_id)
    if not await db.get(Course, body.course_id):
        raise NotFoundError(f"Course {body.course_id} not found")
    await game_service.assert_not_live(db, redis, game.id)

    doomed = [
        user
        for user, has_host in await access.grant_holders(db, game.id, body.course_id)
        if not has_host
    ]
    dropped = [{**_access_entry(u), "has_course_host": False} for u in doomed]
    if not body.confirm:
        return {"applied": False, "game": game, "dropped_grants": dropped}

    if doomed:
        await db.execute(
            delete(UserGameAccess).where(
                UserGameAccess.game_id == game.id,
                UserGameAccess.user_id.in_([u.id for u in doomed]),
            )
        )
    old_course_id = game.course_id
    game.course_id = body.course_id
    await db.flush()
    logger.info(
        "game_moved",
        game_id=game.id,
        from_course_id=old_course_id,
        to_course_id=body.course_id,
        dropped_grants=len(doomed),
    )
    return {"applied": True, "game": game, "dropped_grants": dropped}


@router.get("/games/{game_id}/access", response_model=list[GameAccessEntry])
async def list_game_access(
    game_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    return [
        {**_access_entry(user), "has_course_host": has_host}
        for user, has_host in await access.grant_holders(db, game.id, game.course_id)
    ]


@router.get("/courses/{course_id}/access", response_model=list[CourseAccessEntry])
async def list_course_access(
    course_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    if not await db.get(Course, course_id):
        raise NotFoundError(f"Course {course_id} not found")
    result = await db.execute(
        select(User, UserCourseAccess.role)
        .join(UserCourseAccess, UserCourseAccess.user_id == User.id)
        .where(UserCourseAccess.course_id == course_id)
        .order_by(UserCourseAccess.role, User.username, User.netid, User.id)
    )
    return [{**_access_entry(user), "role": role} for user, role in result]


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


@router.get("/games/{game_id}/questions", response_model=list[QuestionResponse])
async def list_questions(
    game_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Question]:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    return await question_service.list_questions(db, game)


@router.post(
    "/games/{game_id}/questions", response_model=QuestionResponse, status_code=201
)
async def create_question(
    game_id: int,
    body: QuestionCreate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Question:
    game = await game_service.lock_game(db, game_id)
    await game_service.assert_not_live(db, redis, game.id)
    question = await question_service.create_question(db, game, body)
    await db.commit()
    return question


@router.put("/games/{game_id}/questions/{question_id}", response_model=QuestionResponse)
async def update_question(
    game_id: int,
    question_id: int,
    body: QuestionUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Question:
    result = await db.execute(
        select(Question).where(Question.id == question_id, Question.game_id == game_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise NotFoundError(f"Question {question_id} not found in game {game_id}")
    await game_service.lock_game(db, game_id)
    await game_service.assert_not_live(db, redis, game_id)
    return await question_service.update_question(db, question, body)


@router.delete("/games/{game_id}/questions/{question_id}", status_code=204)
async def delete_question(
    game_id: int,
    question_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    result = await db.execute(
        select(Question).where(Question.id == question_id, Question.game_id == game_id)
    )
    question = result.scalar_one_or_none()
    if not question:
        raise NotFoundError(f"Question {question_id} not found in game {game_id}")
    await game_service.lock_game(db, game_id)
    await game_service.assert_not_live(db, redis, game_id)
    await question_service.delete_question(db, question)


@router.post("/games/{game_id}/questions/reorder", status_code=204)
async def reorder_questions(
    game_id: int,
    body: QuestionReorder,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    game = await game_service.lock_game(db, game_id)
    await game_service.assert_not_live(db, redis, game.id)
    await question_service.reorder_questions(db, game, body.order)


@router.get("/games/{game_id}/export")
async def export_game(
    game_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")

    result = await db.execute(
        select(Question)
        .where(Question.game_id == game_id)
        .order_by(Question.order_index)
    )
    questions = result.scalars().all()

    bundle = {
        "format": "buzzer/game",
        "version": _SUPPORTED_IMPORT_VERSION,
        "game": {
            "title": game.title,
            "description": game.description,
            "max_players": game.max_players,
        },
        "questions": [
            {
                "type": q.type,
                "grading_type": q.grading_type,
                "prompt": q.prompt,
                "config": q.config,
                "answer_data": q.answer_data,
                "time_limit_seconds": q.time_limit_seconds,
                "points_value": q.points_value,
            }
            for q in questions
        ],
    }

    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in game.title)
    filename = f"{safe_title}.json"
    content = json.dumps(bundle, indent=2, ensure_ascii=False).encode()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/games/import", status_code=201)
async def import_game(
    file: Annotated[UploadFile, File(description="buzzer/game JSON bundle")],
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    course_id: Annotated[int | None, Form()] = None,
) -> dict:
    # The course comes only from this form field, never from the bundle.
    if course_id is not None and not await db.get(Course, course_id):
        raise NotFoundError(f"Course {course_id} not found")
    raw = await file.read()
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {exc}") from exc

    if bundle.get("format") != "buzzer/game":
        raise HTTPException(status_code=422, detail="Unrecognised file format")
    version = bundle.get("version")
    if version != _SUPPORTED_IMPORT_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported version {version!r}; server supports version {_SUPPORTED_IMPORT_VERSION}",
        )

    game_data = bundle.get("game", {})
    try:
        game_meta = GameFields(**game_data)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid game metadata: {exc}"
        ) from exc

    questions_raw = bundle.get("questions", [])
    validated_questions: list[QuestionCreate] = []
    for i, q in enumerate(questions_raw):
        try:
            validated_questions.append(QuestionCreate(**q))
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Question {i + 1} invalid: {exc}"
            ) from exc

    game = Game(
        title=game_meta.title,
        description=game_meta.description,
        max_players=game_meta.max_players,
        course_id=course_id,
    )
    db.add(game)
    await db.flush()

    for idx, q in enumerate(validated_questions):
        clean_prompt = question_service.sanitize_prompt(q.prompt)
        db.add(
            Question(
                game_id=game.id,
                type=q.type,
                grading_type=q.grading_type,
                prompt=clean_prompt,
                config=q.config,
                answer_data=q.answer_data,
                time_limit_seconds=q.time_limit_seconds,
                points_value=q.points_value,
                order_index=idx,
            )
        )

    await db.commit()
    logger.info(
        "game_imported",
        game_id=game.id,
        title=game.title,
        question_count=len(validated_questions),
    )
    return {"game_id": game.id}


# ---------------------------------------------------------------------------
# Images (T7). Upload only; reading is GET /api/images/{id} (routers/images.py).
# No live-game guard: an upload writes no game or question.
# ---------------------------------------------------------------------------


@router.post("/images", response_model=ImageResponse, status_code=201)
@limiter.limit("30/minute")
async def upload_image(
    request: Request,
    file: Annotated[UploadFile, File(description="PNG, JPEG or WebP, at most 2 MB")],
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    course_id: Annotated[int | None, Form()] = None,
) -> Image:
    if course_id is not None and not await db.get(Course, course_id):
        raise NotFoundError(f"Course {course_id} not found")
    image = await image_service.store_image(db, await file.read(), admin, course_id)
    # Commit before responding: get_db's commit runs after the response is sent, so a
    # client that GETs the image right after the 201 could otherwise get a 404.
    await db.commit()
    logger.info("admin_image_uploaded", image_id=image.id, user_id=admin.id)
    return image


# ---------------------------------------------------------------------------
# Users (local accounts)
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[User]:
    result = await db.execute(
        select(User).where(User.role != "GUEST").order_by(User.role, User.username)
    )
    return result.scalars().all()


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    # Enforce unique username
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise ConflictError(f"Username '{body.username}' is already taken")

    user = User(
        id=str(uuid.uuid4()),
        username=body.username,
        display_name=body.display_name,
        email=str(body.email) if body.email else None,
        password_hash=hash_password(body.password),
        role="USER",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    await db.commit()
    logger.info("local_user_created", user_id=user.id, username=body.username)
    return user


@router.get("/users/guests", response_model=list[UserResponse])
async def list_guests(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[User]:
    result = await db.execute(
        select(User).where(User.role == "GUEST").order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.get("/users/{user_id}", response_model=UserWithAccessResponse)
async def get_user(
    user_id: str,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")

    ca_result = await db.execute(
        select(UserCourseAccess).where(UserCourseAccess.user_id == user_id)
    )
    ga_result = await db.execute(
        select(UserGameAccess).where(UserGameAccess.user_id == user_id)
    )

    course_access = [
        {"course_id": ca.course_id, "role": ca.role} for ca in ca_result.scalars().all()
    ]
    game_access = [ga.game_id for ga in ga_result.scalars().all()]

    return {
        **{
            c: getattr(user, c)
            for c in [
                "id",
                "username",
                "netid",
                "display_name",
                "email",
                "role",
                "created_at",
                "last_login",
            ]
        },
        "course_access": course_access,
        "game_access": game_access,
    }


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    if body.username is not None:
        existing = await db.execute(
            select(User).where(User.username == body.username, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise ConflictError(f"Username '{body.username}' is already taken")
        user.username = body.username
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.email is not None:
        user.email = str(body.email)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.role is not None:
        user.role = body.role
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    if user.role == "ADMIN":
        raise ConflictError("Cannot delete an admin account")
    # Delete scores first — the session_scores.user_id column is NOT NULL so
    # SQLAlchemy's default SET-NULL cascade would fail without this.
    from sqlalchemy import delete as sa_delete
    from ..models.session import SessionScore

    await db.execute(sa_delete(SessionScore).where(SessionScore.user_id == user_id))
    await db.delete(user)


# ---------------------------------------------------------------------------
# Access management
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/course-access", status_code=204)
async def grant_course_access(
    user_id: str,
    body: CourseAccessGrant,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    course = await db.get(Course, body.course_id)
    if not course:
        raise NotFoundError(f"Course {body.course_id} not found")

    result = await db.execute(
        select(UserCourseAccess).where(
            UserCourseAccess.user_id == user_id,
            UserCourseAccess.course_id == body.course_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.role = body.role  # update role if access already exists
    else:
        db.add(
            UserCourseAccess(user_id=user_id, course_id=body.course_id, role=body.role)
        )


@router.delete("/users/{user_id}/course-access/{course_id}", status_code=204)
async def revoke_course_access(
    user_id: str,
    course_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(UserCourseAccess).where(
            UserCourseAccess.user_id == user_id,
            UserCourseAccess.course_id == course_id,
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        raise NotFoundError(
            f"No course access record for user {user_id} / course {course_id}"
        )
    await db.delete(access)


@router.post("/users/{user_id}/game-access", status_code=204)
async def grant_game_access(
    user_id: str,
    body: GameAccessGrant,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    user = await db.get(User, user_id)
    if not user:
        raise NotFoundError(f"User {user_id} not found")
    game = await db.get(Game, body.game_id)
    if not game:
        raise NotFoundError(f"Game {body.game_id} not found")

    result = await db.execute(
        select(UserGameAccess).where(
            UserGameAccess.user_id == user_id,
            UserGameAccess.game_id == body.game_id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(UserGameAccess(user_id=user_id, game_id=body.game_id))


@router.delete("/users/{user_id}/game-access/{game_id}", status_code=204)
async def revoke_game_access(
    user_id: str,
    game_id: int,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(
        select(UserGameAccess).where(
            UserGameAccess.user_id == user_id,
            UserGameAccess.game_id == game_id,
        )
    )
    access = result.scalar_one_or_none()
    if not access:
        raise NotFoundError(
            f"No game access record for user {user_id} / game {game_id}"
        )
    await db.delete(access)


# ---------------------------------------------------------------------------
# Guest merge
# ---------------------------------------------------------------------------


@router.post("/users/merge-guest", status_code=204)
async def merge_guest(
    body: dict,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    guest_user_id: str = body.get("guest_user_id", "")
    target_netid: str = body.get("target_netid", "")

    if not guest_user_id or not target_netid:
        raise ConflictError("guest_user_id and target_netid are required")

    guest = await db.get(User, guest_user_id)
    if not guest or guest.role != "GUEST":
        raise NotFoundError(f"Guest user {guest_user_id} not found")

    normalized_netid = target_netid.strip().lower()

    # Find the real user by netid
    result = await db.execute(select(User).where(User.netid == normalized_netid))
    real_user = result.scalar_one_or_none()

    from ..models.session import SessionScore

    if real_user:
        # Real user already has an account — re-attribute scores and delete the guest record
        scores_result = await db.execute(
            select(SessionScore).where(SessionScore.user_id == guest_user_id)
        )
        for score in scores_result.scalars().all():
            score.user_id = real_user.id
        await db.delete(guest)
        logger.info("guest_merged", guest_id=guest_user_id, real_user_id=real_user.id)
    else:
        # No account yet for this netid (student hasn't logged in via OAuth2) —
        # promote the guest record in-place so scores are retained without re-attribution
        guest.netid = normalized_netid
        guest.role = "USER"
        logger.info("guest_promoted", guest_id=guest_user_id, netid=normalized_netid)


# ---------------------------------------------------------------------------
# Sessions (admin view)
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[AdminSessionItem])
async def list_sessions(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = Query(
        None, description="Filter by status (LOBBY, IN_PROGRESS, COMPLETED, ABANDONED)"
    ),
) -> list[dict]:
    """List all game sessions across all hosts, newest first."""
    query = select(GameSession).order_by(GameSession.created_at.desc())
    if status:
        query = query.where(GameSession.status == status)
    result = await db.execute(query)
    sessions = result.scalars().all()

    rows = []
    for s in sessions:
        game = await db.get(Game, s.game_id)
        course = await db.get(Course, s.course_id)
        host = await db.get(User, s.host_user_id) if s.host_user_id else None

        count_result = await db.execute(
            select(func.count(SessionScore.user_id.distinct())).where(
                SessionScore.session_id == s.id
            )
        )
        player_count = count_result.scalar_one() or 0

        rows.append(
            {
                "session_id": s.id,
                "room_code": s.room_code,
                "status": s.status,
                "game_id": s.game_id,
                "game_title": game.title if game else "Unknown",
                "course_id": s.course_id,
                "course_name": course.name if course else "Unknown",
                "course_semester": course.semester if course else "",
                "host_display_name": (host.display_name or host.username or host.netid)
                if host
                else None,
                "created_at": s.created_at,
                "completed_at": s.completed_at,
                "player_count": player_count,
            }
        )
    return rows


@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    format: str = Query("canvas", description="'canvas' or 'raw'"),
    title: str | None = Query(
        None, description="Assignment column title (Canvas format)"
    ),
    sis_domain: str = Query(
        "", description="Domain appended to netid for SIS Login ID (e.g. wisc.edu)"
    ),
    roster_only: bool = Query(
        True, description="Exclude players without a netid (guests, local accounts)"
    ),
    per_question: bool = Query(
        False, description="One column per question instead of total"
    ),
) -> StreamingResponse:
    """Download session scores as CSV. Supports Canvas gradebook import format."""
    session = await db.get(GameSession, session_id)
    if not session:
        raise NotFoundError(f"Session {session_id} not found")

    if format == "canvas":
        filename, content = await build_canvas_csv(
            db,
            session_id,
            assignment_title=title,
            sis_domain=sis_domain,
            roster_only=roster_only,
            per_question=per_question,
        )
    else:
        filename, content = await build_session_csv(db, session_id)

    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sessions/{session_id}/report")
async def session_report(
    session_id: str,
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Download a standalone HTML report for a session (aggregate stats, no PII)."""
    session = await db.get(GameSession, session_id)
    if not session:
        raise NotFoundError(f"Session {session_id} not found")
    filename, content = await build_session_report(db, session_id)
    return Response(
        content=content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
