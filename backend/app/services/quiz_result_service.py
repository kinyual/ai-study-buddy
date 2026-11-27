"""Persistence service for completed quiz results."""

from typing import get_args

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..models import QuizResult, QuizResultItem
from ..schemas import (
    QuizMode,
    QuizResultItem as QuizResultItemSchema,
    QuizResultResponse,
    QuizResultSummary,
    SavedQuizResultResponse,
)
from .active_quiz_store import ActiveQuiz

_DUPLICATE_MESSAGE = "A result for this quiz already exists."
_PERSISTENCE_MESSAGE = "Quiz result could not be saved."
_NOT_FOUND_MESSAGE = "Quiz result not found."
_OWNER_MISMATCH_MESSAGE = "Completed quiz owner does not match the authenticated user."
_QUIZ_ID_MISMATCH_MESSAGE = "Saved result quiz ID does not match the active quiz."
_INVALID_MODE_MESSAGE = "Unsupported quiz result mode."
_SUPPORTED_MODES = get_args(QuizMode)


class QuizResultAlreadyExistsError(RuntimeError):
    """Raised when a result for this quiz id is already stored."""


class QuizResultPersistenceError(RuntimeError):
    """Raised when the result and its items could not be saved safely."""


class QuizResultNotFoundError(LookupError):
    """Raised when a result is unknown or belongs to another user."""


class QuizResultInputError(ValueError):
    """Raised when persistence inputs are inconsistent or unsupported."""


def _quiz_id_exists(db: Session, quiz_id: str) -> bool:
    """Return whether a result with this quiz id is already stored."""
    return (
        db.execute(select(QuizResult.id).where(QuizResult.quiz_id == quiz_id)).first()
        is not None
    )


def _quiz_id_exists_after_rollback(db: Session, quiz_id: str) -> bool:
    """Check for a duplicate after rollback, without masking database errors."""
    try:
        return _quiz_id_exists(db, quiz_id)
    except SQLAlchemyError:
        return False


def _validate_save_inputs(
    *,
    owner_id: int,
    quiz: ActiveQuiz,
    result: QuizResultResponse,
    mode: str,
) -> None:
    """Reject inconsistent inputs before any database work begins."""
    if quiz.owner_id != owner_id:
        raise QuizResultInputError(_OWNER_MISMATCH_MESSAGE)
    if quiz.quiz_id != result.quiz_id:
        raise QuizResultInputError(_QUIZ_ID_MISMATCH_MESSAGE)
    if mode not in _SUPPORTED_MODES:
        raise QuizResultInputError(_INVALID_MODE_MESSAGE)


def save_quiz_result(
    db: Session,
    *,
    owner_id: int,
    quiz: ActiveQuiz,
    result: QuizResultResponse,
    mode: str = "uploaded",
    topic: str | None = None,
    source_name: str | None = None,
) -> int:
    """Store one completed result and all its items in one transaction."""
    _validate_save_inputs(
        owner_id=owner_id,
        quiz=quiz,
        result=result,
        mode=mode,
    )

    row = QuizResult(
        user_id=owner_id,
        quiz_id=result.quiz_id,
        mode=mode,
        topic=topic,
        source_name=source_name,
        difficulty=quiz.difficulty,
        question_count=quiz.question_count,
        score=result.score,
        percentage=result.percentage,
    )

    try:
        if _quiz_id_exists(db, result.quiz_id):
            raise QuizResultAlreadyExistsError(_DUPLICATE_MESSAGE)

        db.add(row)
        db.flush()
        result_id = row.id

        for item in result.results:
            db.add(
                QuizResultItem(
                    result_id=result_id,
                    position=item.position,
                    question_text=item.question_text,
                    option_a=item.option_a,
                    option_b=item.option_b,
                    option_c=item.option_c,
                    option_d=item.option_d,
                    correct_option=item.correct_option,
                    selected_option=item.selected_option,
                    is_correct=item.is_correct,
                    explanation=item.explanation,
                    source_snippet=item.source_snippet,
                )
            )

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _quiz_id_exists_after_rollback(db, result.quiz_id):
            raise QuizResultAlreadyExistsError(_DUPLICATE_MESSAGE) from exc
        raise QuizResultPersistenceError(_PERSISTENCE_MESSAGE) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise QuizResultPersistenceError(_PERSISTENCE_MESSAGE) from exc
    except Exception:
        db.rollback()
        raise

    return result_id


def list_owned_results(db: Session, owner_id: int) -> list[QuizResultSummary]:
    """Return one learner's result summaries, newest first."""
    rows = (
        db.execute(
            select(QuizResult)
            .where(QuizResult.user_id == owner_id)
            .order_by(QuizResult.created_at.desc(), QuizResult.id.desc())
        )
        .scalars()
        .all()
    )
    return [QuizResultSummary.model_validate(row) for row in rows]


def get_owned_result(
    db: Session,
    owner_id: int,
    result_id: int,
) -> SavedQuizResultResponse:
    """Return one owned result with its full review in position order."""
    row = db.execute(
        select(QuizResult).where(
            QuizResult.id == result_id,
            QuizResult.user_id == owner_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise QuizResultNotFoundError(_NOT_FOUND_MESSAGE)

    items = [
        QuizResultItemSchema.model_validate(item, from_attributes=True)
        for item in sorted(row.items, key=lambda item: item.position)
    ]

    return SavedQuizResultResponse(
        id=row.id,
        quiz_id=row.quiz_id,
        mode=row.mode,
        topic=row.topic,
        source_name=row.source_name,
        difficulty=row.difficulty,
        question_count=row.question_count,
        score=row.score,
        percentage=row.percentage,
        created_at=row.created_at,
        total_questions=row.question_count,
        results=items,
    )
