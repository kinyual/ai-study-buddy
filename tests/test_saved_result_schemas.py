"""Focused tests for saved-result response schemas."""

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    QuizResultItem,
    QuizResultSummary,
    SavedQuizResultResponse,
)

CREATED_AT = datetime(2026, 11, 27, 12, 30, 0)


def summary_data(**overrides: object) -> dict[str, object]:
    """Return valid summary fields for schema tests."""
    data: dict[str, object] = {
        "id": 12,
        "quiz_id": "quiz-abc123",
        "mode": "uploaded",
        "topic": None,
        "source_name": "notes.txt",
        "difficulty": "Medium",
        "question_count": 5,
        "score": 3,
        "percentage": 60.0,
        "created_at": CREATED_AT,
    }
    data.update(overrides)
    return data


def item_data(position: int = 1) -> dict[str, object]:
    """Return one valid result item."""
    return {
        "position": position,
        "question_text": f"Question {position}?",
        "option_a": f"Option A{position}",
        "option_b": f"Option B{position}",
        "option_c": f"Option C{position}",
        "option_d": f"Option D{position}",
        "source_snippet": f"Snippet {position}.",
        "correct_option": "B",
        "selected_option": "A",
        "is_correct": False,
        "explanation": f"Explanation {position}.",
    }


def test_summary_accepts_orm_style_objects() -> None:
    summary = QuizResultSummary.model_validate(SimpleNamespace(**summary_data()))

    assert summary.id == 12
    assert summary.quiz_id == "quiz-abc123"
    assert summary.mode == "uploaded"
    assert summary.topic is None
    assert summary.source_name == "notes.txt"
    assert summary.difficulty == "Medium"
    assert summary.question_count == 5
    assert summary.score == 3
    assert summary.percentage == 60.0
    assert summary.created_at == CREATED_AT


def test_summary_allows_nullable_optional_metadata() -> None:
    summary = QuizResultSummary.model_validate(
        summary_data(topic=None, source_name=None)
    )

    assert summary.topic is None
    assert summary.source_name is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "unknown"),
        ("difficulty", "Impossible"),
        ("question_count", 7),
        ("score", -1),
        ("percentage", 101.0),
        ("created_at", "not-a-datetime"),
    ],
)
def test_summary_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        QuizResultSummary.model_validate(summary_data(**{field: value}))


def test_summary_requires_an_id() -> None:
    data = summary_data()
    data.pop("id")

    with pytest.raises(ValidationError):
        QuizResultSummary.model_validate(data)


def test_saved_response_reuses_the_existing_result_item_schema() -> None:
    data: dict[str, Any] = {
        **summary_data(),
        "total_questions": 5,
        "results": [item_data(position) for position in range(1, 6)],
    }

    saved = SavedQuizResultResponse.model_validate(data)

    assert set(saved.model_dump()) == {
        "id",
        "quiz_id",
        "mode",
        "topic",
        "source_name",
        "difficulty",
        "question_count",
        "score",
        "percentage",
        "created_at",
        "total_questions",
        "results",
    }
    assert all(isinstance(item, QuizResultItem) for item in saved.results)
    assert [item.position for item in saved.results] == [1, 2, 3, 4, 5]
    assert saved.results[0].correct_option == "B"
    assert saved.results[0].selected_option == "A"
    assert saved.results[0].is_correct is False
    assert saved.results[0].explanation == "Explanation 1."
    assert saved.results[0].source_snippet == "Snippet 1."


def test_saved_response_rejects_a_score_above_total_questions() -> None:
    data: dict[str, Any] = {
        **summary_data(score=6, percentage=100.0),
        "total_questions": 5,
        "results": [item_data()],
    }

    with pytest.raises(ValidationError):
        SavedQuizResultResponse.model_validate(data)
