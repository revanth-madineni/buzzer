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
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..common.exceptions import BuzzerError, ConflictError
from ..models.game import Game, Question
from ..models.session import SessionScore
from ..schemas.admin import QuestionCreate, QuestionUpdate

PROMPT_TAGS = ["b", "i", "br", "u"]


def sanitize_prompt(html: str) -> str:
    return bleach.clean(html, tags=PROMPT_TAGS, attributes={}, strip=True)


async def list_questions(db: AsyncSession, game: Game) -> list[Question]:
    result = await db.execute(
        select(Question)
        .where(Question.game_id == game.id)
        .order_by(Question.order_index)
    )
    return list(result.scalars().all())


async def create_question(
    db: AsyncSession, game: Game, body: QuestionCreate
) -> Question:
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
    db: AsyncSession, question: Question, body: QuestionUpdate
) -> Question:
    """Applies every non-null field. No whole-question re-validation ([Extra])."""
    changes = body.model_dump(exclude_none=True)
    if "prompt" in changes:
        changes["prompt"] = sanitize_prompt(changes["prompt"])
    for field, value in changes.items():
        setattr(question, field, value)
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
