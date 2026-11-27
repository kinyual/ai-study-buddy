"""Tests for the persisted quiz-result ORM models."""

from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.database  # noqa: F401  # registers SQLite foreign-key enforcement
from backend.app.models import Base, QuizResult, QuizResultItem, User


@pytest.fixture
def db_session() -> Iterator[Session]:
    """Provide a fresh in-memory database for one model test."""
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


def make_user(db: Session, email: str = "learner@example.com") -> User:
    """Create and commit one learner."""
    user = User(email=email, password_hash="test-only-hash")
    db.add(user)
    db.commit()
    return user


def make_item(
    result_id: int,
    position: int,
    *,
    selected_option: str = "B",
) -> QuizResultItem:
    """Build one valid question snapshot."""
    return QuizResultItem(
        result_id=result_id,
        position=position,
        question_text=f"Question {position}?",
        option_a=f"Option A{position}",
        option_b=f"Option B{position}",
        option_c=f"Option C{position}",
        option_d=f"Option D{position}",
        correct_option="B",
        selected_option=selected_option,
        is_correct=selected_option == "B",
        explanation=f"Explanation {position}.",
        source_snippet=f"Snippet {position}.",
    )


def make_result(
    db: Session,
    user_id: int,
    quiz_id: str = "quiz-1",
    *,
    score: int = 5,
) -> QuizResult:
    """Create and commit one completed result with five items."""
    result = QuizResult(
        user_id=user_id,
        quiz_id=quiz_id,
        mode="uploaded",
        topic=None,
        source_name="notes.txt",
        difficulty="Easy",
        question_count=5,
        score=score,
        percentage=float(score * 20),
    )
    db.add(result)
    db.flush()
    for position in range(1, 6):
        db.add(make_item(result.id, position))
    db.commit()
    return result


def test_result_and_items_round_trip(db_session: Session) -> None:
    user = make_user(db_session)
    saved = make_result(db_session, user.id)

    stored = db_session.execute(
        select(QuizResult).where(QuizResult.id == saved.id)
    ).scalar_one()

    assert stored.user_id == user.id
    assert stored.quiz_id == "quiz-1"
    assert stored.mode == "uploaded"
    assert stored.topic is None
    assert stored.source_name == "notes.txt"
    assert stored.difficulty == "Easy"
    assert stored.question_count == 5
    assert stored.score == 5
    assert stored.percentage == 100.0
    assert stored.created_at is not None
    assert [item.position for item in stored.items] == [1, 2, 3, 4, 5]
    assert stored.items[0].selected_option == "B"
    assert stored.items[0].correct_option == "B"
    assert stored.items[0].is_correct is True
    assert stored.items[0].explanation == "Explanation 1."
    assert stored.items[0].source_snippet == "Snippet 1."


def test_duplicate_quiz_id_is_rejected(db_session: Session) -> None:
    user = make_user(db_session)
    make_result(db_session, user.id, quiz_id="duplicate-quiz")

    with pytest.raises(IntegrityError):
        make_result(db_session, user.id, quiz_id="duplicate-quiz")
    db_session.rollback()

    stored = db_session.execute(select(QuizResult)).scalars().all()
    assert len(stored) == 1


def test_duplicate_position_within_one_result_is_rejected(db_session: Session) -> None:
    user = make_user(db_session)
    result = QuizResult(
        user_id=user.id,
        quiz_id="quiz-positions",
        mode="uploaded",
        topic=None,
        source_name=None,
        difficulty="Medium",
        question_count=5,
        score=0,
        percentage=0.0,
    )
    db_session.add(result)
    db_session.flush()
    db_session.add(make_item(result.id, 1))
    db_session.add(make_item(result.id, 1))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    stored = db_session.execute(select(QuizResultItem)).scalars().all()
    assert stored == []


def test_foreign_keys_are_enforced(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        db_session.add(
            QuizResult(
                user_id=999_999,
                quiz_id="orphan-result",
                mode="uploaded",
                topic=None,
                source_name=None,
                difficulty="Easy",
                question_count=5,
                score=0,
                percentage=0.0,
            )
        )
        db_session.commit()
    db_session.rollback()

    user = make_user(db_session)
    result = make_result(db_session, user.id)

    with pytest.raises(IntegrityError):
        db_session.add(make_item(result.id + 1, 1))
        db_session.commit()
    db_session.rollback()

    stored = db_session.execute(select(QuizResultItem)).scalars().all()
    assert len(stored) == 5


def test_deleting_result_removes_its_items(db_session: Session) -> None:
    user = make_user(db_session)
    result = make_result(db_session, user.id)

    db_session.delete(result)
    db_session.commit()

    assert db_session.execute(select(QuizResult)).scalars().all() == []
    assert db_session.execute(select(QuizResultItem)).scalars().all() == []
