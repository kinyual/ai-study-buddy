"""Tests for the quiz submission grading service."""

import pytest

from backend.app.schemas import (
    AnswerSelection,
    GeneratedQuizQuestion,
    SubmitQuizRequest,
)
from backend.app.services import quiz_submission_service as service
from backend.app.services.active_quiz_store import ActiveQuiz


CORRECT_OPTIONS = ("B", "C", "A", "B", "D")


def make_questions(question_count: int = 5) -> list[GeneratedQuizQuestion]:
    """Return deterministic valid questions with known correct answers."""
    return [
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
        for position in range(1, question_count + 1)
    ]


def make_quiz(question_count: int = 5) -> ActiveQuiz:
    """Build an active quiz directly for grading tests."""
    return ActiveQuiz(
        quiz_id=f"quiz-{question_count}",
        owner_id=7,
        difficulty="Medium",
        question_count=question_count,
        questions=tuple(make_questions(question_count)),
    )


def correct_answers(quiz: ActiveQuiz) -> dict[int, str]:
    """Return the correct option for each question position."""
    return {question.position: question.correct_option for question in quiz.questions}


def wrong_option(correct_option: str) -> str:
    """Return a guaranteed incorrect option."""
    return "B" if correct_option == "A" else "A"


def make_submission(
    quiz: ActiveQuiz,
    selected_by_position: dict[int, str] | None = None,
    *,
    reverse: bool = False,
) -> SubmitQuizRequest:
    """Build a submission, optionally reversing the answer order."""
    if selected_by_position is None:
        selected_by_position = correct_answers(quiz)

    questions = list(quiz.questions)
    if reverse:
        questions.reverse()

    return SubmitQuizRequest(
        quiz_id=quiz.quiz_id,
        answers=[
            AnswerSelection(
                position=question.position,
                selected_option=selected_by_position[question.position],
            )
            for question in questions
        ],
    )


def make_submission_from_positions(
    quiz: ActiveQuiz,
    positions: list[int],
) -> SubmitQuizRequest:
    """Build a submission using only the supplied positions."""
    return SubmitQuizRequest(
        quiz_id=quiz.quiz_id,
        answers=[
            AnswerSelection(position=position, selected_option="A")
            for position in positions
        ],
    )


def test_all_correct_answers_produce_full_score_and_review_details() -> None:
    quiz = make_quiz()

    result = service.build_quiz_result(quiz, make_submission(quiz))

    assert result.quiz_id == quiz.quiz_id
    assert result.score == 5
    assert result.total_questions == 5
    assert result.percentage == 100.0
    assert [item.position for item in result.results] == [1, 2, 3, 4, 5]

    for question, item in zip(quiz.questions, result.results):
        assert item.question_text == question.question_text
        assert item.correct_option == question.correct_option
        assert item.selected_option == question.correct_option
        assert item.is_correct is True
        assert item.explanation == question.explanation
        assert item.source_snippet == question.source_snippet


def test_mixed_answers_produce_partial_score() -> None:
    quiz = make_quiz()
    selected = correct_answers(quiz)
    selected[2] = wrong_option(selected[2])
    selected[4] = wrong_option(selected[4])

    result = service.build_quiz_result(quiz, make_submission(quiz, selected))

    assert result.score == 3
    assert result.total_questions == 5
    assert result.percentage == 60.0
    assert [item.is_correct for item in result.results] == [
        True,
        False,
        True,
        False,
        True,
    ]


def test_all_incorrect_answers_produce_zero_score() -> None:
    quiz = make_quiz()
    selected = {
        question.position: wrong_option(question.correct_option)
        for question in quiz.questions
    }

    result = service.build_quiz_result(quiz, make_submission(quiz, selected))

    assert result.score == 0
    assert result.percentage == 0.0
    assert all(item.is_correct is False for item in result.results)


def test_percentage_is_rounded_to_two_decimal_places() -> None:
    quiz = make_quiz(15)
    selected = {
        question.position: wrong_option(question.correct_option)
        for question in quiz.questions
    }
    selected[1] = quiz.questions[0].correct_option

    result = service.build_quiz_result(quiz, make_submission(quiz, selected))

    assert result.score == 1
    assert result.total_questions == 15
    assert result.percentage == 6.67


def test_results_follow_question_order_not_submission_order() -> None:
    quiz = make_quiz()
    selected = correct_answers(quiz)
    selected[1] = wrong_option(selected[1])
    selected[5] = wrong_option(selected[5])

    result = service.build_quiz_result(
        quiz,
        make_submission(quiz, selected, reverse=True),
    )

    assert [item.position for item in result.results] == [1, 2, 3, 4, 5]
    assert [item.selected_option for item in result.results] == [
        selected[1],
        selected[2],
        selected[3],
        selected[4],
        selected[5],
    ]
    assert [item.is_correct for item in result.results] == [
        False,
        True,
        True,
        True,
        False,
    ]
    assert result.score == 3


@pytest.mark.parametrize(
    "positions",
    [
        [1, 2, 4, 5],
        [1, 2, 3, 4, 5, 6],
        [1, 2, 99, 4, 5],
    ],
    ids=["missing", "extra", "out-of-range"],
)
def test_invalid_answer_coverage_is_rejected(positions: list[int]) -> None:
    quiz = make_quiz()
    submission = make_submission_from_positions(quiz, positions)

    with pytest.raises(service.QuizSubmissionError):
        service.build_quiz_result(quiz, submission)


def test_duplicate_positions_are_rejected_defensively() -> None:
    quiz = make_quiz()
    selected = correct_answers(quiz)
    answers = [
        AnswerSelection(
            position=question.position,
            selected_option=selected[question.position],
        )
        for question in quiz.questions
    ]
    answers.append(
        AnswerSelection(position=1, selected_option=selected[1]),
    )
    submission = SubmitQuizRequest.model_construct(
        quiz_id=quiz.quiz_id,
        answers=answers,
    )

    with pytest.raises(service.QuizSubmissionError):
        service.build_quiz_result(quiz, submission)


def test_mismatched_quiz_id_is_rejected() -> None:
    quiz = make_quiz()
    submission = make_submission(quiz)
    submission = SubmitQuizRequest.model_construct(
        quiz_id="another-quiz",
        answers=submission.answers,
    )

    with pytest.raises(service.QuizSubmissionError):
        service.build_quiz_result(quiz, submission)


def test_grading_does_not_mutate_active_quiz() -> None:
    quiz = make_quiz()
    selected = {
        question.position: wrong_option(question.correct_option)
        for question in quiz.questions
    }
    before_questions = [question.model_dump() for question in quiz.questions]
    before_fields = (
        quiz.quiz_id,
        quiz.owner_id,
        quiz.difficulty,
        quiz.question_count,
        quiz.submitted,
    )

    service.build_quiz_result(quiz, make_submission(quiz, selected))

    assert (
        quiz.quiz_id,
        quiz.owner_id,
        quiz.difficulty,
        quiz.question_count,
        quiz.submitted,
    ) == before_fields
    assert [question.model_dump() for question in quiz.questions] == before_questions
