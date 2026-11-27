"""API endpoints for quiz generation and submission."""

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import User
from ..schemas import (
    GeneratedQuizQuestion,
    QuizQuestionView,
    QuizResponse,
    QuizResultResponse,
    SubmitQuizRequest,
    UploadedQuizRequest,
)
from ..services.active_quiz_store import (
    ActiveQuizNotFoundError,
    get_owned_quiz,
    mark_quiz_submitted,
    save_quiz,
)
from ..services.quiz_generation_service import (
    QuizGenerationError,
    generate_quiz_from_material,
)
from ..services.quiz_submission_service import (
    QuizSubmissionError,
    build_quiz_result,
)
from ..services.upload_store import UploadNotFoundError, get_owned_upload
from .deps import get_current_user

router = APIRouter(tags=["quizzes"])


def _to_question_view(question: GeneratedQuizQuestion) -> QuizQuestionView:
    """Strip answer-key fields before returning a question to the learner."""
    return QuizQuestionView(
        position=question.position,
        question_text=question.question_text,
        option_a=question.option_a,
        option_b=question.option_b,
        option_c=question.option_c,
        option_d=question.option_d,
        source_snippet=question.source_snippet,
    )


@router.post("/quizzes/uploaded", response_model=QuizResponse)
def generate_uploaded_quiz(
    payload: UploadedQuizRequest,
    current_user: User = Depends(get_current_user),
) -> QuizResponse:
    """Generate a quiz from one upload owned by the authenticated user."""
    try:
        stored = get_owned_upload(payload.upload_id, current_user.id)
    except UploadNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found.",
        ) from None

    try:
        questions = generate_quiz_from_material(
            stored.text,
            payload.difficulty,
            payload.question_count,
        )
    except QuizGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from None

    active_quiz = save_quiz(
        owner_id=current_user.id,
        difficulty=payload.difficulty,
        question_count=payload.question_count,
        questions=questions,
    )

    return QuizResponse(
        quiz_id=active_quiz.quiz_id,
        difficulty=payload.difficulty,
        question_count=payload.question_count,
        questions=[_to_question_view(question) for question in active_quiz.questions],
    )


@router.post("/quizzes/submit", response_model=QuizResultResponse)
def submit_quiz(
    payload: SubmitQuizRequest,
    current_user: User = Depends(get_current_user),
) -> QuizResultResponse:
    """Grade one owned active quiz and mark it submitted."""
    try:
        quiz = get_owned_quiz(payload.quiz_id, current_user.id)
    except ActiveQuizNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quiz not found.",
        ) from None

    if quiz.submitted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quiz has already been submitted.",
        )

    try:
        result = build_quiz_result(quiz, payload)
    except QuizSubmissionError as exc:
        # A literal keeps this compatible with the project's older FastAPI versions.
        raise HTTPException(status_code=422, detail=str(exc)) from None

    if not mark_quiz_submitted(payload.quiz_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quiz has already been submitted.",
        )

    return result
