"""Grading service for submitted active quizzes."""

from ..schemas import QuizResultItem, QuizResultResponse, SubmitQuizRequest
from .active_quiz_store import ActiveQuiz

_QUIZ_ID_MESSAGE = "Submitted quiz ID does not match the active quiz."
_DUPLICATE_MESSAGE = "A quiz submission cannot contain duplicate question positions."
_COVERAGE_MESSAGE = "Submit exactly one answer for every quiz question."


class QuizSubmissionError(RuntimeError):
    """Raised when a quiz submission cannot be graded safely."""


def build_quiz_result(
    quiz: ActiveQuiz,
    submission: SubmitQuizRequest,
) -> QuizResultResponse:
    """Grade a validated submission and return a reviewable result."""
    if submission.quiz_id != quiz.quiz_id:
        raise QuizSubmissionError(_QUIZ_ID_MESSAGE)

    positions = [answer.position for answer in submission.answers]
    if len(positions) != len(set(positions)):
        raise QuizSubmissionError(_DUPLICATE_MESSAGE)

    expected_positions = {question.position for question in quiz.questions}
    if set(positions) != expected_positions:
        raise QuizSubmissionError(_COVERAGE_MESSAGE)

    answers_by_position = {
        answer.position: answer.selected_option for answer in submission.answers
    }

    score = 0
    results: list[QuizResultItem] = []

    for question in sorted(quiz.questions, key=lambda item: item.position):
        selected_option = answers_by_position[question.position]
        is_correct = selected_option == question.correct_option
        if is_correct:
            score += 1

        results.append(
            QuizResultItem(
                position=question.position,
                question_text=question.question_text,
                option_a=question.option_a,
                option_b=question.option_b,
                option_c=question.option_c,
                option_d=question.option_d,
                source_snippet=question.source_snippet,
                correct_option=question.correct_option,
                selected_option=selected_option,
                is_correct=is_correct,
                explanation=question.explanation,
            )
        )

    percentage = round(score / quiz.question_count * 100, 2)

    return QuizResultResponse(
        quiz_id=quiz.quiz_id,
        score=score,
        total_questions=quiz.question_count,
        percentage=percentage,
        results=results,
    )
