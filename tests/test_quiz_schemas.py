"""Focused tests for quiz request, question, submission, and result schemas."""

import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    GeneratedQuizQuestion,
    QuizQuestionView,
    QuizResultItem,
    QuizResultResponse,
    SubmitQuizRequest,
    TopicQuizRequest,
    UploadedQuizRequest,
)


def question_data(**overrides: object) -> dict[str, object]:
    """Return valid shared question fields for schema tests."""
    data: dict[str, object] = {
        "position": 1,
        "question_text": "Which planet is known as the Red Planet?",
        "option_a": "Venus",
        "option_b": "Mars",
        "option_c": "Jupiter",
        "option_d": "Mercury",
        "source_snippet": "Mars appears red because of iron oxide on its surface.",
    }
    data.update(overrides)
    return data


def generated_question_data(**overrides: object) -> dict[str, object]:
    """Return valid generated question fields for schema tests."""
    data = question_data()
    data.update({"correct_option": "B", "explanation": "Mars is the Red Planet."})
    data.update(overrides)
    return data


def result_item_data(**overrides: object) -> dict[str, object]:
    """Return valid result review fields for schema tests."""
    data = generated_question_data()
    data.update({"selected_option": "B", "is_correct": True})
    data.update(overrides)
    return data


def result_response_data(**overrides: object) -> dict[str, object]:
    """Return valid quiz result response fields for schema tests."""
    data: dict[str, object] = {
        "quiz_id": "quiz-1",
        "score": 5,
        "total_questions": 5,
        "percentage": 100.0,
        "results": [result_item_data(position=position) for position in range(1, 6)],
    }
    data.update(overrides)
    return data


def test_topic_quiz_request_accepts_valid_values() -> None:
    request = TopicQuizRequest(
        topic="  world history  ",
        difficulty="Medium",
        question_count=10,
    )

    assert request.topic == "world history"
    assert request.difficulty == "Medium"
    assert request.question_count == 10


def test_uploaded_quiz_request_accepts_valid_values() -> None:
    request = UploadedQuizRequest(
        upload_id="  upload-123  ",
        difficulty="Hard",
        question_count=15,
    )

    assert request.upload_id == "upload-123"
    assert request.difficulty == "Hard"
    assert request.question_count == 15


@pytest.mark.parametrize(
    "payload",
    [
        {"topic": "Science", "difficulty": "Very Hard", "question_count": 5},
        {"topic": "Science", "difficulty": "Easy", "question_count": 7},
        {"topic": "   ", "difficulty": "Easy", "question_count": 5},
    ],
)
def test_topic_quiz_request_rejects_invalid_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TopicQuizRequest(**payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"upload_id": "upload-123", "difficulty": "Hard", "question_count": 8},
        {"upload_id": "   ", "difficulty": "Hard", "question_count": 5},
    ],
)
def test_uploaded_quiz_request_rejects_invalid_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UploadedQuizRequest(**payload)


def test_generated_question_accepts_valid_data_and_optional_source_snippet() -> None:
    data = generated_question_data()
    del data["source_snippet"]

    question = GeneratedQuizQuestion(**data)

    assert question.position == 1
    assert question.correct_option == "B"
    assert question.explanation == "Mars is the Red Planet."
    assert question.source_snippet is None


@pytest.mark.parametrize("position", [0, -1])
def test_generated_question_requires_positive_position(position: int) -> None:
    with pytest.raises(ValidationError):
        GeneratedQuizQuestion(**generated_question_data(position=position))


@pytest.mark.parametrize(
    "overrides",
    [
        {"option_b": "Venus"},
        {"option_c": "   "},
        {"option_e": "Phobos"},
    ],
)
def test_generated_question_requires_four_distinct_non_empty_options(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GeneratedQuizQuestion(**generated_question_data(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"correct_option": "E"},
        {"explanation": "   "},
        {"question_text": ""},
    ],
)
def test_generated_question_requires_valid_answer_and_explanation(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GeneratedQuizQuestion(**generated_question_data(**overrides))


def test_quiz_question_view_hides_correct_answers_and_explanations() -> None:
    view = QuizQuestionView(**question_data())
    dumped = view.model_dump()

    assert "correct_option" not in dumped
    assert "explanation" not in dumped

    hidden_data = question_data()
    hidden_data["correct_option"] = "B"
    hidden_data["explanation"] = "Mars is the Red Planet."
    with pytest.raises(ValidationError):
        QuizQuestionView(**hidden_data)


def test_submit_quiz_request_accepts_unique_answer_positions() -> None:
    submission = SubmitQuizRequest(
        quiz_id="quiz-1",
        answers=[
            {"position": 1, "selected_option": "A"},
            {"position": 2, "selected_option": "C"},
        ],
    )

    assert [answer.position for answer in submission.answers] == [1, 2]


def test_submit_quiz_request_rejects_duplicate_positions() -> None:
    with pytest.raises(ValidationError):
        SubmitQuizRequest(
            quiz_id="quiz-1",
            answers=[
                {"position": 1, "selected_option": "A"},
                {"position": 1, "selected_option": "B"},
            ],
        )


@pytest.mark.parametrize(
    "answer",
    [
        {"position": 0, "selected_option": "A"},
        {"position": 1, "selected_option": "E"},
    ],
)
def test_submit_quiz_request_rejects_invalid_answers(answer: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SubmitQuizRequest(quiz_id="quiz-1", answers=[answer])


def test_quiz_result_item_contains_review_details() -> None:
    item = QuizResultItem(**result_item_data())

    assert item.correct_option == "B"
    assert item.selected_option == "B"
    assert item.is_correct is True
    assert item.explanation == "Mars is the Red Planet."


def test_quiz_result_response_accepts_valid_score_and_percentage() -> None:
    result = QuizResultResponse(**result_response_data())

    assert result.score == 5
    assert result.total_questions == 5
    assert result.percentage == 100.0
    assert len(result.results) == 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"score": 6},
        {"score": -1},
        {"percentage": 101.0},
        {"percentage": -1.0},
    ],
)
def test_quiz_result_response_rejects_out_of_range_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        QuizResultResponse(**result_response_data(**overrides))
