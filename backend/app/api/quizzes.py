"""API endpoint for generating quizzes from uploaded study material."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from ..models import User
from ..schemas import (
    GeneratedQuizQuestion,
    QuizQuestionView,
    QuizResponse,
    UploadedQuizRequest,
)
from ..services.quiz_generation_service import (
    QuizGenerationError,
    generate_quiz_from_material,
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

    return QuizResponse(
        quiz_id=uuid4().hex,
        difficulty=payload.difficulty,
        question_count=payload.question_count,
        questions=[_to_question_view(question) for question in questions],
    )
