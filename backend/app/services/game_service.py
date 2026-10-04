from __future__ import annotations

import math
import secrets
import uuid
from datetime import datetime, timezone

import structlog
from rapidfuzz.distance import Levenshtein
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..common.exceptions import (
    BuzzerError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from ..models.course import Course, CourseRoster, UserCourseAccess
from ..models.game import Game, Question
from ..models.session import GameSession, SessionScore
from ..models.user import User
from ..schemas.admin import is_valid_number
from ..schemas.game import ScoreResult
from . import access_service as access
from . import state_service as state

logger = structlog.get_logger()

# Character set from spec: unambiguous alphanumeric (no 0/O/1/I/L)
_ROOM_CHARSET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_MAX_CODE_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Room code generation
# ---------------------------------------------------------------------------


async def generate_room_code(redis: Redis) -> str:
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = "".join(secrets.choice(_ROOM_CHARSET) for _ in range(6))
        if not await redis.exists(f"room:{code}"):
            return code
    raise ConflictError("Could not generate a unique room code — try again")


# ---------------------------------------------------------------------------
# Access validation helpers
# ---------------------------------------------------------------------------


# Thin wrappers over access_service, which holds the one definition of "is HOST".


async def assert_host_can_use_course(
    db: AsyncSession, user: User, course_id: int
) -> None:
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")
    if not await access.has_course_host(db, user, course.id):
        raise ForbiddenError(access.COURSE_HOST_REQUIRED)


async def assert_host_can_use_game(db: AsyncSession, user: User, game_id: int) -> None:
    game = await db.get(Game, game_id)
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    await access.assert_can_use_game(db, user, game)


# ---------------------------------------------------------------------------
# Live-game guard (spec §4.5). Every guarded write — question create/update/
# delete/reorder, host game update/delete, admin move — calls lock_game, then
# assert_not_live, then writes. start_game takes the same lock. After the lock,
# reads that decide the outcome must be locking reads (REPEATABLE READ).
# ---------------------------------------------------------------------------


async def lock_game(db: AsyncSession, game_id: int) -> Game:
    """SELECT … FOR UPDATE on the game row, held until the transaction ends."""
    game = (
        await db.execute(
            select(Game)
            .where(Game.id == game_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not game:
        raise NotFoundError(f"Game {game_id} not found")
    return game


async def is_game_live(db: AsyncSession, redis: Redis, game_id: int) -> bool:
    """An IN_PROGRESS session whose Redis room still exists. A row whose key
    expired is stale, not live. Locking read: see the block comment above."""
    room_codes = (
        await db.execute(
            select(GameSession.room_code)
            .where(
                GameSession.game_id == game_id,
                GameSession.status == "IN_PROGRESS",
            )
            .with_for_update(read=True)
        )
    ).scalars()
    for code in room_codes:
        if await redis.exists(f"room:{code}"):
            return True
    return False


async def assert_not_live(db: AsyncSession, redis: Redis, game_id: int) -> None:
    if await is_game_live(db, redis, game_id):
        raise BuzzerError("GAME_LIVE", "This game is being played right now", 409)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


async def create_room(
    db: AsyncSession,
    redis: Redis,
    host: User,
    game_id: int,
    course_id: int,
    max_rooms: int = 50,
) -> GameSession:
    # Course first, so a bad course_id 404s before a courseless game is attached.
    course = await db.get(Course, course_id)
    if not course:
        raise NotFoundError(f"Course {course_id} not found")

    # Row lock until the request's transaction ends: serializes concurrent room
    # creations for one game, so two admins cannot attach it to different courses.
    game = (
        await db.execute(select(Game).where(Game.id == game_id).with_for_update())
    ).scalar_one_or_none()
    if not game:
        raise NotFoundError(f"Game {game_id} not found")

    if host.role == "ADMIN":
        if game.course_id is None:
            game.course_id = course.id
            logger.info(
                "game_attached_on_first_room",
                game_id=game.id,
                course_id=course.id,
                user_id=host.id,
            )
    else:
        await access.assert_can_use_game(db, host, game)

    if course.id != game.course_id:
        game_course = await db.get(Course, game.course_id)
        raise BuzzerError(
            "COURSE_MISMATCH",
            f"This game belongs to course {game_course.name} ({game_course.semester})",
            422,
        )

    # Enforce global room limit — count only LOBBY/IN_PROGRESS rooms.
    # COMPLETED/ABANDONED rooms may linger in Redis briefly for reconnection
    # but do not consume a concurrent-room slot.
    all_room_keys = await redis.keys("room:*")
    room_count = 0
    for key in all_room_keys:
        key_str = key if isinstance(key, str) else key.decode()
        if len(key_str) != 11:  # "room:" (5 chars) + 6-char code
            continue
        room_state_data = await state.get_room_state(redis, key_str[5:])
        if room_state_data and room_state_data.get("status") in (
            "LOBBY",
            "IN_PROGRESS",
        ):
            room_count += 1
    if room_count >= max_rooms:
        raise ConflictError(f"Maximum of {max_rooms} concurrent rooms reached")

    room_code = await generate_room_code(redis)

    session = GameSession(
        id=str(uuid.uuid4()),
        room_code=room_code,
        game_id=game_id,
        course_id=course_id,
        host_user_id=host.id,
        status="LOBBY",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)

    # Store room state in Redis
    await state.set_room_state(
        redis,
        room_code,
        {
            "session_id": session.id,
            "game_id": game_id,
            "course_id": course_id,
            "host_user_id": host.id,
            "status": "LOBBY",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    logger.info(
        "room_created",
        room_code=room_code,
        session_id=session.id,
        host_id=host.id,
        game_id=game_id,
        course_id=course_id,
    )
    return session


async def get_session_by_code(
    db: AsyncSession, redis: Redis, room_code: str
) -> tuple[GameSession, dict | None]:
    """
    Return (session, redis_state). redis_state is None if Redis has no record
    (session may still be in MySQL as COMPLETED/ABANDONED).
    """
    redis_state = await state.get_room_state(redis, room_code)

    result = await db.execute(
        select(GameSession)
        .where(GameSession.room_code == room_code)
        .options(selectinload(GameSession.game))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError(f"Room '{room_code}' not found or has expired")

    return session, redis_state


async def start_game(
    db: AsyncSession, redis: Redis, session: GameSession
) -> list[Question]:
    """Transition LOBBY → IN_PROGRESS. Returns ordered question list."""
    # Same game-row lock as every guarded edit (lock_game), so a start and an
    # edit serialize. The reads after it are locking reads: under REPEATABLE READ
    # a plain SELECT would see the snapshot from this transaction's first read,
    # missing an edit that committed while we waited (spec §4.5).
    await lock_game(db, session.game_id)
    await db.execute(
        select(GameSession)
        .where(GameSession.id == session.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if session.status != "LOBBY":
        raise ConflictError(f"Cannot start a game in '{session.status}' state")

    result = await db.execute(
        select(Question)
        .where(Question.game_id == session.game_id)
        .order_by(Question.order_index)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    questions = result.scalars().all()
    if not questions:
        raise ConflictError(
            "This game has no questions — add questions before starting"
        )

    session.status = "IN_PROGRESS"
    # Commit immediately so concurrent on_submit_answer handlers in separate DB
    # sessions see IN_PROGRESS rather than the unflushed LOBBY status.
    await db.commit()

    # Update Redis status
    room_state = await state.get_room_state(redis, session.room_code)
    if room_state:
        room_state["status"] = "IN_PROGRESS"
        await state.set_room_state(redis, session.room_code, room_state)

    logger.info("game_started", session_id=session.id, question_count=len(questions))
    return list(questions)


async def complete_game(db: AsyncSession, redis: Redis, session: GameSession) -> None:
    session.status = "COMPLETED"
    session.completed_at = datetime.now(timezone.utc)
    # Commit so player join attempts racing with game_over see COMPLETED.
    await db.commit()
    logger.info("game_completed", session_id=session.id)
    # Keep Redis state 10 more minutes for reconnection, then let it expire naturally


async def abandon_game(db: AsyncSession, redis: Redis, session: GameSession) -> None:
    session.status = "ABANDONED"
    session.completed_at = datetime.now(timezone.utc)
    await db.flush()
    await state.delete_room_state(redis, session.room_code, session.id)
    logger.info("game_abandoned", session_id=session.id)


# ---------------------------------------------------------------------------
# Player authorisation at join time
# ---------------------------------------------------------------------------


async def authorise_player(db: AsyncSession, user: User, session: GameSession) -> str:
    """
    Check whether the player is permitted to join this session.
    Returns the display name to use for the player.
    Raises ForbiddenError / NotFoundError if not authorised.
    """
    if user.role == "GUEST":
        return user.display_name or "Guest"

    if user.role == "ADMIN":
        return user.display_name or user.username or "Admin"

    # OAuth2 user — check course roster
    if user.netid:
        result = await db.execute(
            select(CourseRoster).where(
                CourseRoster.course_id == session.course_id,
                CourseRoster.netid == user.netid,
                CourseRoster.is_active == True,  # noqa: E712
            )
        )
        roster_entry = result.scalar_one_or_none()
        if roster_entry:
            return roster_entry.full_name  # first name from CSV

    # Local account with explicit PLAYER role for this course
    result = await db.execute(
        select(UserCourseAccess).where(
            UserCourseAccess.user_id == user.id,
            UserCourseAccess.course_id == session.course_id,
            UserCourseAccess.role == "PLAYER",
        )
    )
    if result.scalar_one_or_none():
        return user.display_name or user.username or "Player"

    # Local account with HOST role can also join as player
    result = await db.execute(
        select(UserCourseAccess).where(
            UserCourseAccess.user_id == user.id,
            UserCourseAccess.course_id == session.course_id,
            UserCourseAccess.role == "HOST",
        )
    )
    if result.scalar_one_or_none():
        return user.display_name or user.username or "Host"

    raise ForbiddenError("You are not enrolled in the course roster for this game")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Map pin (T7 spec §4.6). Every piece of map-pin geometry goes through these
# helpers, so scoring, distributions, reveals, stats and the report agree.
# ---------------------------------------------------------------------------

MAP_PIN_GRID = 50


def map_pin_click(answer: object) -> tuple[float, float] | None:
    """(x, y) if `answer` is exactly {x, y} with valid numbers in [0, 1], else None."""
    if not isinstance(answer, dict) or set(answer) != {"x", "y"}:
        return None
    x, y = answer["x"], answer["y"]
    if not (is_valid_number(x) and is_valid_number(y)):
        return None
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    return float(x), float(y)


def _map_pin_geometry(
    config: dict, answer_data: dict
) -> tuple[float, tuple[float, float], float, float] | None:
    """(aspect, target, fullRadius, zeroRadius), or None for a malformed question."""
    width, height = config.get("imageWidth"), config.get("imageHeight")
    targets = answer_data.get("targets")
    full, zero = answer_data.get("fullRadius"), answer_data.get("zeroRadius")
    if not (is_valid_number(width) and is_valid_number(height)):
        return None
    if width <= 0 or height <= 0:
        return None
    if not isinstance(targets, list) or not targets:
        return None
    target = targets[0]
    if not isinstance(target, dict):
        return None
    tx, ty = target.get("x"), target.get("y")
    if not all(is_valid_number(v) for v in (tx, ty, full, zero)):
        return None
    return width / height, (float(tx), float(ty)), float(full), float(zero)


def map_pin_distance(
    aspect: float, target: tuple[float, float], click: tuple[float, float]
) -> float:
    """Distance in image-width units; `aspect` = imageWidth / imageHeight."""
    dx = click[0] - target[0]
    dy = (click[1] - target[1]) / aspect  # height fractions → width units
    return math.hypot(dx, dy)


def map_pin_fraction(d: float, full_radius: float, zero_radius: float) -> float:
    """1 within fullRadius, linear falloff to 0 at zeroRadius."""
    if d <= full_radius:
        return 1.0
    if d >= zero_radius:
        return 0.0
    return 1 - (d - full_radius) / (zero_radius - full_radius)


def map_pin_bucket(x: float, y: float) -> str:
    """Distribution key "bx,by" on a 50×50 grid. x = 1.0 lands in bucket 49."""
    bx = min(MAP_PIN_GRID - 1, math.floor(x * MAP_PIN_GRID))
    by = min(MAP_PIN_GRID - 1, math.floor(y * MAP_PIN_GRID))
    return f"{bx},{by}"


def map_pin_reveal(grading_type: str, config: dict, answer_data: dict) -> dict:
    """The one map-pin reveal, for both grading types (spec §4.6). Answers' targets
    are only revealed after the question closes; never put them in `config`."""
    targets = answer_data.get("targets") or [{}]
    target = targets[0] if isinstance(targets[0], dict) else {}
    return {
        "type": "map_pin",
        "gradingType": grading_type,
        "imageId": config.get("imageId"),
        "imageWidth": config.get("imageWidth"),
        "imageHeight": config.get("imageHeight"),
        "target": {"x": target.get("x"), "y": target.get("y")},
        "fullRadius": answer_data.get("fullRadius"),
        "zeroRadius": answer_data.get("zeroRadius"),
    }


def map_pin_stats(config: dict, answer_data: dict, answers: list) -> dict:
    """withinFullPct (0–100, 1 dp) and averageCredit (0–1, 3 dp), from geometry only,
    so they mean the same under COMPLETENESS and with points_value 0. The denominator
    is the answers with a valid {x, y}; both are None when there are none."""
    geometry = _map_pin_geometry(config, answer_data)
    clicks = [c for c in (map_pin_click(a) for a in answers) if c is not None]
    if geometry is None or not clicks:
        return {"withinFullPct": None, "averageCredit": None}
    aspect, target, full, zero = geometry
    distances = [map_pin_distance(aspect, target, c) for c in clicks]
    within = sum(1 for d in distances if d <= full)
    credit = sum(map_pin_fraction(d, full, zero) for d in distances)
    return {
        "withinFullPct": round(100 * within / len(clicks), 1),
        "averageCredit": round(credit / len(clicks), 3),
    }


def game_image_ids(questions: list[Question]) -> list[str]:
    """Distinct map_pin image IDs, in question order (for preloading on phones)."""
    ids: list[str] = []
    for q in questions:
        if q.type == "map_pin":
            image_id = (q.config or {}).get("imageId")
            if isinstance(image_id, str) and image_id not in ids:
                ids.append(image_id)
    return ids


async def get_game_image_ids(db: AsyncSession, game_id: int) -> list[str]:
    result = await db.execute(
        select(Question)
        .where(Question.game_id == game_id)
        .order_by(Question.order_index)
    )
    return game_image_ids(list(result.scalars().all()))


def _score_map_pin(question: Question, answer_data: dict) -> ScoreResult:
    """ACCURACY map_pin. Defensive: reachable from tests, seed scripts and direct
    inserts that skip validation, so bad data scores 0 instead of raising."""
    geometry = _map_pin_geometry(question.config or {}, question.answer_data or {})
    if geometry is None:
        logger.warning("map_pin_bad_question", question_id=question.id)
        return ScoreResult(points_awarded=0, is_correct=False)
    click = map_pin_click(answer_data)
    if click is None:
        logger.warning("map_pin_bad_answer", question_id=question.id)
        return ScoreResult(points_awarded=0, is_correct=False)
    aspect, target, full, zero = geometry
    d = map_pin_distance(aspect, target, click)
    frac = map_pin_fraction(d, full, zero)
    return ScoreResult(
        points_awarded=round(question.points_value * frac, 2),
        is_correct=d <= full,
    )


def calculate_score(question: Question, answer_data: dict) -> ScoreResult:
    """
    Calculate points for a player's answer.
    COMPLETENESS: any answer = full points, no answer = 0
    ACCURACY:     points come from answer_data.answer_points per selected option
    """
    if not answer_data:
        return ScoreResult(points_awarded=0, is_correct=False)

    if question.grading_type == "COMPLETENESS":
        return ScoreResult(points_awarded=question.points_value, is_correct=True)

    # ACCURACY
    if question.type == "map_pin":
        return _score_map_pin(question, answer_data)

    if question.type == "multiple_choice":
        selected = answer_data.get("selectedIndex")
        if selected is None:
            return ScoreResult(points_awarded=0, is_correct=False)
        pts_list: list[float] = question.answer_data.get("answer_points", [])
        if not (0 <= selected < len(pts_list)):
            return ScoreResult(points_awarded=0, is_correct=False)
        points = pts_list[selected]
        return ScoreResult(
            points_awarded=points,
            is_correct=(points == question.points_value),
        )

    if question.type == "true_false":
        selected = answer_data.get("selectedValue")
        if selected is None:
            return ScoreResult(points_awarded=0, is_correct=False)
        pts_map: dict = question.answer_data.get("answer_points", {})
        key = "true" if selected else "false"
        points = pts_map.get(key, 0)
        return ScoreResult(
            points_awarded=points,
            is_correct=(points == question.points_value),
        )

    if question.type == "fill_in_the_blank":
        text = " ".join((answer_data.get("text") or "").lower().split())
        if not text:
            return ScoreResult(points_awarded=0, is_correct=False)
        accepted = [
            " ".join(a.lower().split())
            for a in question.answer_data.get("acceptedAnswers", [])
        ]
        answer_pts: list[float] = question.answer_data.get("answerPoints", [])
        max_dist = int(question.answer_data.get("editDistance", 0))
        best: float = 0.0
        for i, a in enumerate(accepted):
            if Levenshtein.distance(text, a) <= max_dist:
                pts = answer_pts[i] if i < len(answer_pts) else question.points_value
                best = max(best, pts)
        return ScoreResult(
            points_awarded=best,
            is_correct=(best >= question.points_value),
        )

    if question.type == "multi_select":
        selected = answer_data.get("selectedIndices")
        if not isinstance(selected, list):
            return ScoreResult(points_awarded=0, is_correct=False)
        pts_list: list[float] = question.answer_data.get("answer_points", [])
        raw = sum(
            pts_list[i]
            for i in selected
            if isinstance(i, int) and 0 <= i < len(pts_list)
        )
        score = max(0.0, raw)
        return ScoreResult(
            points_awarded=score,
            is_correct=(score >= question.points_value and question.points_value > 0),
        )

    return ScoreResult(points_awarded=0, is_correct=False)


async def record_answer(
    db: AsyncSession,
    redis: Redis,
    session_id: str,
    user_id: str,
    question: Question,
    answer_data: dict,
    answer_time_ms: int | None,
) -> ScoreResult:
    """
    Score an answer, write it to MySQL immediately, and update Redis score.
    Returns the score result.
    """
    result = calculate_score(question, answer_data)

    # Persist to MySQL immediately (per-question persistence guarantee)
    score_row = SessionScore(
        session_id=session_id,
        user_id=user_id,
        question_id=question.id,
        points_awarded=result.points_awarded,
        answer_time_ms=answer_time_ms,
        is_correct=result.is_correct,
        answer_data=answer_data or None,
    )
    db.add(score_row)
    await db.flush()

    # Update Redis running score and answered set
    await state.update_player_score(redis, session_id, user_id, result.points_awarded)
    await state.mark_answered(redis, session_id, question.id, user_id)

    # Increment per-option distribution counter for the results bar chart
    dist_key: str | None = None
    if question.type == "multiple_choice":
        idx = answer_data.get("selectedIndex")
        if idx is not None:
            dist_key = str(idx)
    elif question.type == "true_false":
        val = answer_data.get("selectedValue")
        if val is not None:
            dist_key = "true" if val else "false"
    elif question.type == "fill_in_the_blank":
        text = " ".join((answer_data.get("text") or "").lower().split())
        if text:
            dist_key = text
    elif question.type == "map_pin":
        click = map_pin_click(answer_data)
        if click is not None:
            dist_key = map_pin_bucket(*click)
    elif question.type == "multi_select":
        indices = answer_data.get("selectedIndices")
        if isinstance(indices, list):
            for idx in indices:
                if isinstance(idx, int):
                    await state.increment_answer_dist(
                        redis, session_id, question.id, str(idx)
                    )
    if dist_key is not None:
        await state.increment_answer_dist(redis, session_id, question.id, dist_key)

    return result


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


async def get_leaderboard(db: AsyncSession, session_id: str) -> list[dict]:
    """
    Aggregate session_scores from MySQL to produce a leaderboard.
    Used for QUESTION_RESULTS and GAME_OVER broadcasts.
    """
    from sqlalchemy import func as sqlfunc

    rows = await db.execute(
        select(
            SessionScore.user_id,
            sqlfunc.sum(SessionScore.points_awarded).label("total_score"),
        )
        .where(SessionScore.session_id == session_id)
        .group_by(SessionScore.user_id)
        .order_by(sqlfunc.sum(SessionScore.points_awarded).desc())
    )
    return [{"user_id": r.user_id, "score": float(r.total_score or 0)} for r in rows]


async def get_player_question_summary(
    db: AsyncSession, session_id: str, user_id: str
) -> list[dict]:
    """
    Per-question breakdown for a single player — used in GAME_OVER payload.
    """
    rows = await db.execute(
        select(
            Question.id.label("question_id"),
            Question.prompt,
            Question.points_value,
            Question.type.label("q_type"),
            Question.grading_type,
            Question.config,
            Question.answer_data.label("q_answer_data"),
            SessionScore.points_awarded,
            SessionScore.answer_time_ms,
            SessionScore.answer_data.label("player_answer"),
        )
        .join(GameSession, GameSession.game_id == Question.game_id)
        .outerjoin(
            SessionScore,
            (SessionScore.question_id == Question.id)
            & (SessionScore.session_id == session_id)
            & (SessionScore.user_id == user_id),
        )
        .where(GameSession.id == session_id)
        .order_by(Question.order_index)
    )

    result = []
    for r in rows:
        q_type = r.q_type
        grading_type = r.grading_type
        q_ans = r.q_answer_data or {}
        pts_val = r.points_value

        if q_type == "map_pin":
            reveal: dict = map_pin_reveal(grading_type, r.config or {}, q_ans)
        elif grading_type == "COMPLETENESS":
            reveal = {"type": "completeness"}
        elif q_type == "multiple_choice":
            pts = q_ans.get("answer_points", [])
            correct_indices = [i for i, p in enumerate(pts) if p >= pts_val]
            reveal = {"type": "multiple_choice", "correctIndices": correct_indices}
        elif q_type == "true_false":
            pts_map = q_ans.get("answer_points", {})
            correct_true = pts_map.get("true", 0) >= pts_val
            reveal = {"type": "true_false", "correctValue": correct_true}
        elif q_type == "fill_in_the_blank":
            reveal = {
                "type": "fill_in_the_blank",
                "acceptedAnswers": q_ans.get("acceptedAnswers", []),
                "editDistance": q_ans.get("editDistance", 0),
            }
        elif q_type == "multi_select":
            reveal = {
                "type": "multi_select",
                "answerPoints": q_ans.get("answer_points", []),
            }
        else:
            reveal = {}

        result.append(
            {
                "questionId": r.question_id,
                "prompt": r.prompt,
                "type": q_type,
                "gradingType": grading_type,
                "config": r.config or {},
                "pointsAwarded": r.points_awarded or 0,
                "maxPoints": pts_val,
                "answerTimeMs": r.answer_time_ms,
                "playerAnswer": r.player_answer,
                "answerReveal": reveal,
            }
        )

    return result


async def get_host_question_summary(
    db: AsyncSession, session_id: str, total_players: int
) -> list[dict]:
    """Per-question breakdown for the host game-over screen.
    Returns prompt, answer reveal, distribution, and correct/answered counts."""
    from collections import defaultdict

    rows = await db.execute(
        select(
            Question.id.label("question_id"),
            Question.order_index,
            Question.prompt,
            Question.type.label("q_type"),
            Question.grading_type,
            Question.config,
            Question.answer_data.label("q_answer_data"),
            Question.points_value,
            SessionScore.user_id,
            SessionScore.points_awarded,
            SessionScore.answer_data.label("player_answer"),
            SessionScore.answer_time_ms,
            SessionScore.is_correct,
        )
        .join(GameSession, GameSession.game_id == Question.game_id)
        .outerjoin(
            SessionScore,
            (SessionScore.question_id == Question.id)
            & (SessionScore.session_id == session_id),
        )
        .where(GameSession.id == session_id)
        .order_by(Question.order_index)
    )

    questions_meta: dict[int, dict] = {}
    questions_order: list[int] = []
    scores_by_q: dict[int, list[dict]] = defaultdict(list)

    for r in rows:
        qid = r.question_id
        if qid not in questions_meta:
            questions_meta[qid] = {
                "order_index": r.order_index,
                "prompt": r.prompt,
                "type": r.q_type,
                "grading_type": r.grading_type,
                "config": r.config or {},
                "answer_data": r.q_answer_data or {},
                "points_value": r.points_value,
            }
            questions_order.append(qid)
        if r.user_id is not None:
            scores_by_q[qid].append(
                {
                    "player_answer": r.player_answer,
                    "is_correct": bool(r.is_correct),
                    "answer_time_ms": r.answer_time_ms,
                }
            )

    result = []
    for qnum, qid in enumerate(questions_order, start=1):
        q = questions_meta[qid]
        scores = scores_by_q[qid]
        q_type = q["type"]
        q_ans = q["answer_data"]
        pts_val = q["points_value"]
        grading_type = q["grading_type"]

        if q_type == "map_pin":
            reveal: dict = map_pin_reveal(grading_type, q["config"], q_ans)
        elif grading_type == "COMPLETENESS":
            reveal = {"type": "completeness"}
        elif q_type == "multiple_choice":
            pts_list = q_ans.get("answer_points", [])
            reveal = {
                "type": "multiple_choice",
                "correctIndices": [i for i, p in enumerate(pts_list) if p >= pts_val],
            }
        elif q_type == "true_false":
            pts_map = q_ans.get("answer_points", {})
            reveal = {
                "type": "true_false",
                "correctValue": pts_map.get("true", 0) >= pts_val,
            }
        elif q_type == "fill_in_the_blank":
            reveal = {
                "type": "fill_in_the_blank",
                "acceptedAnswers": q_ans.get("acceptedAnswers", []),
                "editDistance": q_ans.get("editDistance", 0),
            }
        elif q_type == "multi_select":
            reveal = {
                "type": "multi_select",
                "answerPoints": q_ans.get("answer_points", []),
            }
        else:
            reveal = {}

        dist: dict[str, int] = {}
        correct_count = 0
        total_time = 0
        time_count = 0
        for s in scores:
            ans = s["player_answer"]
            if ans:
                if q_type == "multiple_choice":
                    idx = ans.get("selectedIndex")
                    if idx is not None:
                        k = str(idx)
                        dist[k] = dist.get(k, 0) + 1
                elif q_type == "true_false":
                    val = ans.get("selectedValue")
                    if val is not None:
                        k = "true" if val else "false"
                        dist[k] = dist.get(k, 0) + 1
                elif q_type == "fill_in_the_blank":
                    text = (ans.get("text") or "").strip().lower()
                    if text:
                        dist[text] = dist.get(text, 0) + 1
                elif q_type == "map_pin":
                    click = map_pin_click(ans)
                    if click is not None:
                        k = map_pin_bucket(*click)
                        dist[k] = dist.get(k, 0) + 1
                elif q_type == "multi_select":
                    indices = ans.get("selectedIndices")
                    if isinstance(indices, list):
                        for idx in indices:
                            if isinstance(idx, int):
                                k = str(idx)
                                dist[k] = dist.get(k, 0) + 1
            if s["is_correct"]:
                correct_count += 1
            if s["answer_time_ms"] is not None:
                total_time += s["answer_time_ms"]
                time_count += 1

        entry = {
            "questionId": qid,
            "questionNumber": qnum,
            "prompt": q["prompt"],
            "type": q_type,
            "gradingType": grading_type,
            "config": q["config"],
            "pointsValue": pts_val,
            "answerReveal": reveal,
            "answerDistribution": dist,
            "totalAnswered": len(scores),
            "totalPlayers": total_players,
            "correctCount": correct_count,
            "avgAnswerTimeMs": round(total_time / time_count) if time_count else None,
        }
        if q_type == "map_pin":
            entry.update(
                map_pin_stats(q["config"], q_ans, [s["player_answer"] for s in scores])
            )
        result.append(entry)

    return result
