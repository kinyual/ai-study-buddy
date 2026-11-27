"""SQLAlchemy ORM models for AI Study Buddy."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class User(Base):
    """A registered learner."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    quiz_results: Mapped[list["QuizResult"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        """Store email addresses consistently in lowercase."""
        return value.strip().lower()


class QuizResult(Base):
    """One completed quiz kept so the learner can review it later."""

    __tablename__ = "quiz_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quiz_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    topic: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="quiz_results")
    items: Mapped[list["QuizResultItem"]] = relationship(
        back_populates="result",
        cascade="all, delete-orphan",
    )


class QuizResultItem(Base):
    """One answered question snapshot from a completed quiz."""

    __tablename__ = "quiz_result_items"
    __table_args__ = (
        UniqueConstraint(
            "result_id",
            "position",
            name="uq_quiz_result_items_result_position",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("quiz_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_a: Mapped[str] = mapped_column(Text, nullable=False)
    option_b: Mapped[str] = mapped_column(Text, nullable=False)
    option_c: Mapped[str] = mapped_column(Text, nullable=False)
    option_d: Mapped[str] = mapped_column(Text, nullable=False)
    correct_option: Mapped[str] = mapped_column(String(1), nullable=False)
    selected_option: Mapped[str] = mapped_column(String(1), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    source_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    result: Mapped["QuizResult"] = relationship(back_populates="items")
