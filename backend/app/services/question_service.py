"""
Question authoring shared by the admin and host routers (spec §4.5).

Every prompt write goes through sanitize_prompt: report_service embeds prompts
as raw HTML, so an unsanitized write would let any course HOST store script.
Callers own the transaction (flush only, no commit). Writers call
game_service.lock_game + assert_not_live first; the reads here that decide the
outcome are therefore locking reads, so they see edits committed while the
caller waited for the lock (REPEATABLE READ, spec §4.5).
"""

from __future__ import annotations

import bleach
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import BuzzerError, ConflictError
from ..models.game import Game, Question
from ..models.session import SessionScore
from ..models.user import User
from ..schemas.admin import QuestionCreate, QuestionResponse, QuestionUpdate
from . import game_service, image_service

PROMPT_TAGS = ["b", "i", "br", "u"]

# The content fields a PUT is validated on, after merging (spec T7 §4.5). order_index is
# positional, so it's applied from the PUT as before but not part of the merge.
_CONTENT_FIELDS = (
    "type",
    "grading_type",
    "prompt",
    "config",
    "answer_data",
    "time_limit_seconds",
    "points_value",
)


def sanitize_prompt(html: str) -> str:
    return bleach.clean(html, tags=PROMPT_TAGS, attributes={}, strip=True)


async def list_questions(db: AsyncSession, game: Game) -> list[Question]:
    result = await db.execute(
        select(Question)
        .where(Question.game_id == game.id)
        .order_by(Question.order_index)
    )
    return list(result.scalars().all())


async def resolve_question_images(
    db: AsyncSession,
    body: QuestionCreate,
    game: Game,
    user: User,
    previous_ids: set[str],
) -> None:
    """Existence, course scoping and map dimensions for every image the question
    references (T8 spec §4.4). Runs on create and update, **not** import (import's
    images aren't stored yet; it sets dimensions from its own PreparedImages).

    The `FOR SHARE` lock on each image row blocks a concurrent delete or replace
    (`FOR UPDATE`) until this transaction commits, so the two can't both pass their
    checks. Callers run this before writing the question row (lock order: game →
    image → question rows).
    """
    refs = game_service.question_image_ids(body.type, body.config)
    ids = {image_id for image_id, _ in refs}
    if not ids:
        return
    images = await image_service.lock_images(db, ids, read=True)
    for image_id, _ in refs:
        if image_id not in images:
            raise BuzzerError("IMAGE_NOT_FOUND", f"Image {image_id} not found", 422)
    if user.role != "ADMIN":
        # Only IDs new to the question, so an edit still saves after an admin moved
        # the game (or for images shared from before a move).
        for image_id in sorted(ids - previous_ids):
            image = images[image_id]
            if image.course_id is None or image.course_id != game.course_id:
                raise BuzzerError(
                    "IMAGE_NOT_IN_COURSE",
                    f"Image {image_id} belongs to a different course",
                    422,
                )
    if body.type == "map_pin":
        image = images[body.config["imageId"]]
        body.config = {
            **body.config,
            "imageWidth": image.width,
            "imageHeight": image.height,
        }


async def question_responses(
    db: AsyncSession, questions: list[Question]
) -> list[QuestionResponse]:
    """`QuestionResponse`s with `image_alt` filled in (one metadata query)."""
    refs = {
        q.id: {i for i, _ in game_service.question_image_ids(q.type, q.config)}
        for q in questions
    }
    meta = await image_service.get_images_meta(db, set().union(*refs.values()))
    out = []
    for q in questions:
        response = QuestionResponse.model_validate(q)
        response.image_alt = {i: meta[i].alt_text for i in refs[q.id] if i in meta}
        out.append(response)
    return out


async def create_question(
    db: AsyncSession, game: Game, body: QuestionCreate, user: User
) -> Question:
    await resolve_question_images(db, body, game, user, set())
    # Auto-assign order_index if not specified
    if body.order_index is None:
        result = await db.execute(
            select(Question.order_index)
            .where(Question.game_id == game.id)
            .order_by(Question.order_index.desc())
            .limit(1)
            .with_for_update(read=True)
        )
        max_idx = result.scalar_one_or_none()
        order_index = (max_idx + 1) if max_idx is not None else 0
    else:
        order_index = body.order_index

    question = Question(
        game_id=game.id,
        type=body.type,
        grading_type=body.grading_type,
        prompt=sanitize_prompt(body.prompt),
        config=body.config,
        answer_data=body.answer_data,
        time_limit_seconds=body.time_limit_seconds,
        points_value=body.points_value,
        order_index=order_index,
    )
    db.add(question)
    await db.flush()
    await db.refresh(question)
    return question


async def update_question(
    db: AsyncSession,
    game: Game,
    question: Question,
    body: QuestionUpdate,
    user: User,
) -> Question:
    """Validates the whole merged question, so a PUT can't produce a question that
    create would reject (T7 spec §4.5).

    The PUT's non-null fields are overlaid on the existing question's content
    fields; `config` and `answer_data` are replaced whole (send `{}` to clear one).
    Then: schema validation (422 VALIDATION_ERROR), image resolution, prompt
    sanitizing, apply. An existing question that create would reject can't be PUT,
    even for a prompt-only change, until it is made valid.
    """
    # Locking read: the caller holds the game lock, and the merge must see edits
    # committed while it waited (see module docstring). FOR SHARE, not FOR UPDATE
    # (T8 §4.0): the game lock already serialises writers, and a shared lock doesn't
    # block an image delete's locking scan, which would deadlock against it.
    await db.execute(
        select(Question)
        .where(Question.id == question.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    previous_ids = {
        i for i, _ in game_service.question_image_ids(question.type, question.config)
    }
    changes = body.model_dump(exclude_none=True)
    merged = {field: getattr(question, field) for field in _CONTENT_FIELDS}
    merged.update({k: v for k, v in changes.items() if k in _CONTENT_FIELDS})
    try:
        validated = QuestionCreate.model_validate(merged)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    await resolve_question_images(db, validated, game, user, previous_ids)
    validated.prompt = sanitize_prompt(validated.prompt)
    for field in _CONTENT_FIELDS:
        setattr(question, field, getattr(validated, field))
    if "order_index" in changes:
        question.order_index = changes["order_index"]
    await db.flush()
    return question


async def delete_question(db: AsyncSession, question: Question) -> None:
    """409 QUESTION_HAS_ANSWERS if any SessionScore references it (the FK would
    otherwise fail as a 500). Recorded answers are never deleted this way."""
    answered = (
        await db.execute(
            select(exists().where(SessionScore.question_id == question.id))
        )
    ).scalar()
    if answered:
        raise BuzzerError(
            "QUESTION_HAS_ANSWERS",
            "Question has recorded answers and cannot be deleted",
            409,
        )
    await db.delete(question)
    await db.flush()


async def reorder_questions(db: AsyncSession, game: Game, order: list[int]) -> None:
    result = await db.execute(
        select(Question)
        .where(Question.game_id == game.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    questions = {q.id: q for q in result.scalars().all()}

    if set(order) != set(questions.keys()):
        raise ConflictError(
            "order list must contain exactly the IDs of all questions in this game"
        )

    for idx, qid in enumerate(order):
        questions[qid].order_index = idx
    await db.flush()
