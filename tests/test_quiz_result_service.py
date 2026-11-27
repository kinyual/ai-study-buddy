"""Tests for the completed quiz-result persistence service."""

from typing import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.database  # noqa: F401  # registers SQLite foreign-key enforcement
from backend.app.models import Base, QuizResult, QuizResultItem, User
from backend.app.schemas import (
    AnswerSelection,
    GeneratedQuizQuestion,
    QuizResultResponse,
    QuizResultSummary,
    SubmitQuizRequest,
)
from backend.app.services import quiz_result_service as service
from backend.app.services.active_quiz_store import ActiveQuiz
from backend.app.services.quiz_submission_service import build_quiz_result

CORRECT_OPTIONS = ("B", "C", "A", "B", "D")


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Provide a fresh in-memory database for one service test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def make_user(db: Session, email: str) -> User:
    """Create and commit one learner."""
    user = User(email=email, password_hash="test-only-hash")
    db.add(user)
    db.commit()
    return user


def make_quiz(quiz_id: str, owner_id: int) -> ActiveQuiz:
    """Build a deterministic active quiz for persistence tests."""
    questions = tuple(
        GeneratedQuizQuestion(
            position=position,
            question_text=f"Question {position}?",
            option_a=f"Option A{position}",
            option_b=f"Option B{position}",
            option_c=f"Option C{position}",
            option_d=f"Option D{position}",
            correct_option=CORRECT_OPTIONS[(position - 1) % len(CORRECT_OPTIONS)],
            explanation=f"Explanation for question {position}.",
            source_snippet=f"Source snippet for question {position}.",
        )
        for position in range(1, 6)
    )
    return ActiveQuiz(
        quiz_id=quiz_id,
        owner_id=owner_id,
        difficulty="Medium",
        question_count=5,
        questions=questions,
    )


def make_graded_result(quiz: ActiveQuiz) -> QuizResultResponse:
    """Grade a fully correct submission using the existing service."""
    submission = SubmitQuizRequest(
        quiz_id=quiz.quiz_id,
        answers=[
            AnswerSelection(
                position=question.position,
                selected_option=question.correct_option,
            )
            for question in quiz.questions
        ],
    )
    return build_quiz_result(quiz, submission)


def assert_no_saved_rows(db: Session) -> None:
    """Confirm that no result or item rows were written."""
    assert (
        db.execute(select(func.count()).select_from(QuizResult)).scalar_one() == 0
    )
    assert (
        db.execute(select(func.count()).select_from(QuizResultItem)).scalar_one() == 0
    )


def generic_integrity_error() -> IntegrityError:
    """Return an IntegrityError with no quiz-id wording to inspect."""
    return IntegrityError(
        "INSERT statement failed",
        {},
        Exception("constraint failure"),
    )


def test_save_round_trip_preserves_metadata_and_review(db_session: Session) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-round-trip", user.id)
    graded = make_graded_result(quiz)

    result_id = service.save_quiz_result(
        db_session,
        owner_id=user.id,
        quiz=quiz,
        result=graded,
        mode="uploaded",
        source_name="notes.txt",
    )

    saved = service.get_owned_result(db_session, user.id, result_id)

    assert result_id > 0
    assert saved.id == result_id
    assert saved.quiz_id == quiz.quiz_id
    assert saved.mode == "uploaded"
    assert saved.topic is None
    assert saved.source_name == "notes.txt"
    assert saved.difficulty == "Medium"
    assert saved.question_count == 5
    assert saved.total_questions == 5
    assert saved.score == 5
    assert saved.percentage == 100.0
    assert saved.created_at is not None
    assert [item.position for item in saved.results] == [1, 2, 3, 4, 5]
    assert saved.results[0].question_text == "Question 1?"
    assert saved.results[0].correct_option == "B"
    assert saved.results[0].selected_option == "B"
    assert saved.results[0].is_correct is True
    assert saved.results[0].explanation == "Explanation for question 1."
    assert saved.results[0].source_snippet == "Source snippet for question 1."


def test_saved_items_are_returned_in_position_order(db_session: Session) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-order", user.id)
    graded = make_graded_result(quiz)
    graded.results.reverse()

    result_id = service.save_quiz_result(
        db_session,
        owner_id=user.id,
        quiz=quiz,
        result=graded,
    )

    saved = service.get_owned_result(db_session, user.id, result_id)
    assert [item.position for item in saved.results] == [1, 2, 3, 4, 5]


def test_list_owned_results_is_owner_scoped_and_newest_first(
    db_session: Session,
) -> None:
    owner = make_user(db_session, "owner@example.com")
    other = make_user(db_session, "other@example.com")
    first_quiz = make_quiz("quiz-first", owner.id)
    second_quiz = make_quiz("quiz-second", owner.id)
    other_quiz = make_quiz("quiz-other", other.id)

    service.save_quiz_result(
        db_session,
        owner_id=owner.id,
        quiz=first_quiz,
        result=make_graded_result(first_quiz),
    )
    service.save_quiz_result(
        db_session,
        owner_id=owner.id,
        quiz=second_quiz,
        result=make_graded_result(second_quiz),
    )
    service.save_quiz_result(
        db_session,
        owner_id=other.id,
        quiz=other_quiz,
        result=make_graded_result(other_quiz),
    )

    summaries = service.list_owned_results(db_session, owner.id)

    assert all(isinstance(summary, QuizResultSummary) for summary in summaries)
    assert [summary.quiz_id for summary in summaries] == [
        "quiz-second",
        "quiz-first",
    ]
    assert all("results" not in summary.model_dump() for summary in summaries)
    assert [
        summary.quiz_id for summary in service.list_owned_results(db_session, other.id)
    ] == ["quiz-other"]


def test_get_owned_result_hides_unknown_and_other_users_results(
    db_session: Session,
) -> None:
    owner = make_user(db_session, "owner@example.com")
    other = make_user(db_session, "other@example.com")
    quiz = make_quiz("quiz-private", owner.id)
    result_id = service.save_quiz_result(
        db_session,
        owner_id=owner.id,
        quiz=quiz,
        result=make_graded_result(quiz),
    )

    with pytest.raises(service.QuizResultNotFoundError) as unknown:
        service.get_owned_result(db_session, owner.id, 999_999)
    with pytest.raises(service.QuizResultNotFoundError) as other_user:
        service.get_owned_result(db_session, other.id, result_id)

    assert str(unknown.value) == str(other_user.value)


def test_duplicate_quiz_id_is_rejected_without_a_second_result(
    db_session: Session,
) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-duplicate", user.id)
    graded = make_graded_result(quiz)
    service.save_quiz_result(
        db_session,
        owner_id=user.id,
        quiz=quiz,
        result=graded,
    )

    with pytest.raises(service.QuizResultAlreadyExistsError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=graded,
        )

    assert (
        db_session.execute(select(func.count()).select_from(QuizResult)).scalar_one()
        == 1
    )
    assert (
        db_session.execute(select(func.count()).select_from(QuizResultItem)).scalar_one()
        == 5
    )


def test_commit_failure_rolls_back_the_whole_transaction(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-commit-failure", user.id)

    def fail_commit() -> None:
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(service.QuizResultPersistenceError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=make_graded_result(quiz),
        )

    assert (
        db_session.execute(select(func.count()).select_from(QuizResult)).scalar_one()
        == 0
    )
    assert (
        db_session.execute(select(func.count()).select_from(QuizResultItem)).scalar_one()
        == 0
    )


def test_item_integrity_failure_rolls_back_the_whole_transaction(
    db_session: Session,
) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-item-failure", user.id)
    graded = make_graded_result(quiz)
    graded.results.append(graded.results[0].model_copy())

    with pytest.raises(service.QuizResultPersistenceError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=graded,
        )

    assert (
        db_session.execute(select(func.count()).select_from(QuizResult)).scalar_one()
        == 0
    )
    assert (
        db_session.execute(select(func.count()).select_from(QuizResultItem)).scalar_one()
        == 0
    )


def test_generic_integrity_error_is_duplicate_when_row_exists_after_rollback(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-generic-duplicate", user.id)
    lookup_results = iter([False, True])
    monkeypatch.setattr(
        service,
        "_quiz_id_exists",
        lambda _db, _quiz_id: next(lookup_results),
    )

    def fail_commit() -> None:
        raise generic_integrity_error()

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(service.QuizResultAlreadyExistsError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=make_graded_result(quiz),
        )


def test_generic_integrity_error_without_duplicate_is_persistence_error(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-generic-persistence", user.id)
    lookup_results = iter([False, False])
    monkeypatch.setattr(
        service,
        "_quiz_id_exists",
        lambda _db, _quiz_id: next(lookup_results),
    )

    def fail_commit() -> None:
        raise generic_integrity_error()

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(service.QuizResultPersistenceError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=make_graded_result(quiz),
        )


def test_unexpected_exception_rolls_back_and_is_re_raised(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedFailure(Exception):
        """A non-SQLAlchemy failure that must not be relabelled."""

    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-unexpected-failure", user.id)

    def fail_commit() -> None:
        raise UnexpectedFailure("unexpected failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(UnexpectedFailure, match="unexpected failure"):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=make_graded_result(quiz),
        )

    assert_no_saved_rows(db_session)


def test_owner_mismatch_is_rejected_before_writing(db_session: Session) -> None:
    owner = make_user(db_session, "owner@example.com")
    other = make_user(db_session, "other@example.com")
    quiz = make_quiz("quiz-owner-mismatch", owner.id)

    with pytest.raises(service.QuizResultInputError):
        service.save_quiz_result(
            db_session,
            owner_id=other.id,
            quiz=quiz,
            result=make_graded_result(quiz),
        )

    assert_no_saved_rows(db_session)


def test_quiz_id_mismatch_is_rejected_before_writing(db_session: Session) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-id-mismatch", user.id)
    graded = make_graded_result(quiz)
    graded.quiz_id = "different-quiz"

    with pytest.raises(service.QuizResultInputError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=graded,
        )

    assert_no_saved_rows(db_session)


@pytest.mark.parametrize("mode", ["uploaded", "topic"])
def test_supported_modes_are_saved(db_session: Session, mode: str) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-supported-mode", user.id)

    result_id = service.save_quiz_result(
        db_session,
        owner_id=user.id,
        quiz=quiz,
        result=make_graded_result(quiz),
        mode=mode,
    )

    assert service.get_owned_result(db_session, user.id, result_id).mode == mode


@pytest.mark.parametrize("mode", ["Uploaded", "unknown", "", None])
def test_unsupported_mode_is_rejected_before_writing(
    db_session: Session,
    mode: str,
) -> None:
    user = make_user(db_session, "owner@example.com")
    quiz = make_quiz("quiz-invalid-mode", user.id)

    with pytest.raises(service.QuizResultInputError):
        service.save_quiz_result(
            db_session,
            owner_id=user.id,
            quiz=quiz,
            result=make_graded_result(quiz),
            mode=mode,
        )

    assert_no_saved_rows(db_session)
