"""Owner-scoped in-memory storage for active quizzes.

The prototype keeps generated quizzes in backend memory only. The full
questions, including correct answers and explanations, stay here so submissions
can be graded without exposing the answer key before submission. Nothing is
written to disk or SQLite, and all active quizzes disappear when the backend
process restarts.
"""

import threading
import uuid
from dataclasses import dataclass, replace
from typing import Iterable

from ..schemas import Difficulty, GeneratedQuizQuestion, QuestionCount

_NOT_FOUND_MESSAGE = "Quiz not found."


class ActiveQuizNotFoundError(LookupError):
    """Raised when a quiz is unknown or belongs to another user."""


@dataclass(frozen=True)
class ActiveQuiz:
    """One generated quiz held temporarily in backend memory."""

    quiz_id: str
    owner_id: int
    difficulty: Difficulty
    question_count: QuestionCount
    questions: tuple[GeneratedQuizQuestion, ...]
    source_name: str | None = None
    submitted: bool = False


_quizzes_by_id: dict[str, ActiveQuiz] = {}
_quiz_ids_by_owner: dict[int, set[str]] = {}
_lock = threading.Lock()


def _copy_questions(
    questions: Iterable[GeneratedQuizQuestion],
) -> tuple[GeneratedQuizQuestion, ...]:
    """Return an immutable tuple of deep-copied questions."""
    return tuple(question.model_copy(deep=True) for question in questions)


def _copy_quiz(quiz: ActiveQuiz) -> ActiveQuiz:
    """Return a detached copy that cannot mutate stored answer-key data."""
    return replace(quiz, questions=_copy_questions(quiz.questions))


def _get_owned_stored_quiz(quiz_id: str, owner_id: int) -> ActiveQuiz:
    """Return a stored quiz only if it belongs to the given owner.

    The caller must hold ``_lock`` before calling this helper.
    """
    if quiz_id not in _quiz_ids_by_owner.get(owner_id, set()):
        raise ActiveQuizNotFoundError(_NOT_FOUND_MESSAGE)

    stored = _quizzes_by_id.get(quiz_id)
    if stored is None or stored.owner_id != owner_id:
        raise ActiveQuizNotFoundError(_NOT_FOUND_MESSAGE)
    return stored


def save_quiz(
    owner_id: int,
    difficulty: Difficulty,
    question_count: QuestionCount,
    questions: Iterable[GeneratedQuizQuestion],
    source_name: str | None = None,
) -> ActiveQuiz:
    """Store one generated quiz and return a detached copy of it."""
    quiz = ActiveQuiz(
        quiz_id=uuid.uuid4().hex,
        owner_id=owner_id,
        difficulty=difficulty,
        question_count=question_count,
        questions=_copy_questions(questions),
        source_name=source_name,
    )

    with _lock:
        _quizzes_by_id[quiz.quiz_id] = quiz
        _quiz_ids_by_owner.setdefault(owner_id, set()).add(quiz.quiz_id)

    return _copy_quiz(quiz)


def get_owned_quiz(quiz_id: str, owner_id: int) -> ActiveQuiz:
    """Return a detached quiz copy only if it belongs to the given owner."""
    with _lock:
        stored = _get_owned_stored_quiz(quiz_id, owner_id)
        return _copy_quiz(stored)


def mark_quiz_submitted(quiz_id: str, owner_id: int) -> bool:
    """Atomically mark an owned quiz as submitted.

    Return ``True`` when this call changes the quiz from unsubmitted to
    submitted. Return ``False`` when it was already submitted. Unknown quiz IDs
    and quizzes owned by another user raise ``ActiveQuizNotFoundError``.
    """
    with _lock:
        stored = _get_owned_stored_quiz(quiz_id, owner_id)
        if stored.submitted:
            return False

        _quizzes_by_id[quiz_id] = replace(stored, submitted=True)
        return True
