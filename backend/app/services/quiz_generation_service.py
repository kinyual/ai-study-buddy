"""Gemini-powered quiz generation service.

This module keeps Gemini access away from routes and the frontend. It returns
validated ``GeneratedQuizQuestion`` objects and raises friendly domain errors
when generation cannot be completed safely.

Source-snippet matching for material quizzes is a grounding safeguard only.
It helps reject clearly unsupported questions, but it does not prove that the
AI's answer is factually correct.
"""

import json
from typing import Optional

from google.genai import Client, errors, types
from httpx import RequestError
from pydantic import BaseModel, ValidationError

from ..config import Settings, get_settings
from ..schemas import Difficulty, GeneratedQuizQuestion, QuestionCount
from .quiz_prompts import (
    SHARED_SYSTEM_INSTRUCTION,
    build_material_prompt,
    build_topic_prompt,
)

_API_FAILURE_MESSAGE = "Quiz generation failed. Please try again."
_INVALID_RESPONSE_MESSAGE = "The generated quiz was invalid. Please try again."
_NOT_CONFIGURED_MESSAGE = "Quiz generation is not available right now."
_EMPTY_TOPIC_MESSAGE = "Enter a topic before generating a quiz."
_EMPTY_MATERIAL_MESSAGE = "Study material is empty. Please provide text to generate a quiz."
_COUNT_MESSAGE = "The generated quiz did not contain the requested number of questions. Please try again."
_POSITION_MESSAGE = "The generated quiz had invalid question numbers. Please try again."
_DUPLICATE_MESSAGE = "The generated quiz contained duplicate questions. Please try again."
_GROUNDING_MESSAGE = "The generated quiz was not grounded in the supplied material. Please try again."

_GEMINI_ERRORS = (
    errors.APIError,
    errors.UnknownApiResponseError,
    TimeoutError,
    RequestError,
)


class QuizGenerationError(RuntimeError):
    """Raised when a quiz cannot be generated safely."""


class _GeminiQuizResponse(BaseModel):
    """Internal JSON wrapper expected from Gemini."""

    questions: list[GeneratedQuizQuestion]


def _build_client(settings: Settings) -> Client:
    """Create a Gemini client from backend settings only."""
    return Client(api_key=settings.gemini_api_key)


def _call_gemini(prompt: str, settings: Settings) -> str:
    """Ask Gemini for JSON quiz data and return the raw response text."""
    client = _build_client(settings)
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SHARED_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=_GeminiQuizResponse,
            temperature=0.2,
        ),
    )

    text = response.text
    if not isinstance(text, str) or not text.strip():
        raise QuizGenerationError(_INVALID_RESPONSE_MESSAGE)
    return text


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace so snippets can be matched across line breaks."""
    return " ".join(text.split())


def _has_duplicate_questions(questions: list[GeneratedQuizQuestion]) -> bool:
    """Check for repeated question text after simple normalisation."""
    normalized = [
        _normalize_whitespace(question.question_text).casefold()
        for question in questions
    ]
    return len(normalized) != len(set(normalized))


def _questions_are_grounded(
    questions: list[GeneratedQuizQuestion],
    source_text: str,
) -> bool:
    """Check that each material question includes a snippet from the source."""
    normalized_source = _normalize_whitespace(source_text)

    for question in questions:
        snippet = question.source_snippet
        if not snippet:
            return False
        if _normalize_whitespace(snippet) not in normalized_source:
            return False

    return True


def _validate_generated_questions(
    questions: list[GeneratedQuizQuestion],
    question_count: QuestionCount,
    source_text: Optional[str] = None,
) -> list[GeneratedQuizQuestion]:
    """Apply service-level checks that schemas cannot express on their own."""
    if len(questions) != question_count:
        raise QuizGenerationError(_COUNT_MESSAGE)

    expected_positions = list(range(1, question_count + 1))
    actual_positions = [question.position for question in questions]
    if actual_positions != expected_positions:
        raise QuizGenerationError(_POSITION_MESSAGE)

    if _has_duplicate_questions(questions):
        raise QuizGenerationError(_DUPLICATE_MESSAGE)

    if source_text is not None and not _questions_are_grounded(questions, source_text):
        raise QuizGenerationError(_GROUNDING_MESSAGE)

    return questions


def _generate_questions(
    prompt: str,
    question_count: QuestionCount,
    source_text: Optional[str] = None,
) -> list[GeneratedQuizQuestion]:
    """Call Gemini, validate its output, and return quiz questions."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise QuizGenerationError(_NOT_CONFIGURED_MESSAGE)

    try:
        raw_text = _call_gemini(prompt, settings)
    except _GEMINI_ERRORS as exc:
        raise QuizGenerationError(_API_FAILURE_MESSAGE) from exc

    try:
        payload = _GeminiQuizResponse.model_validate_json(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise QuizGenerationError(_INVALID_RESPONSE_MESSAGE) from exc

    return _validate_generated_questions(
        payload.questions,
        question_count,
        source_text=source_text,
    )


def generate_quiz_from_topic(
    topic: str,
    difficulty: Difficulty,
    question_count: QuestionCount,
) -> list[GeneratedQuizQuestion]:
    """Generate validated quiz questions from a topic using general knowledge.

    Callers must pass one of the ``Difficulty`` values and one of the
    ``QuestionCount`` values. Future API routes should use the existing Pydantic
    request schemas to validate these inputs before calling this service.
    """
    cleaned_topic = topic.strip()
    if not cleaned_topic:
        raise QuizGenerationError(_EMPTY_TOPIC_MESSAGE)

    prompt = build_topic_prompt(cleaned_topic, difficulty, question_count)
    return _generate_questions(prompt, question_count)


def generate_quiz_from_material(
    source_text: str,
    difficulty: Difficulty,
    question_count: QuestionCount,
) -> list[GeneratedQuizQuestion]:
    """Generate validated quiz questions grounded in supplied study material.

    Callers must pass one of the ``Difficulty`` values and one of the
    ``QuestionCount`` values. Future API routes should use the existing Pydantic
    request schemas to validate these inputs before calling this service.
    """
    settings = get_settings()
    cleaned_source = source_text.strip()

    if not cleaned_source:
        raise QuizGenerationError(_EMPTY_MATERIAL_MESSAGE)
    if len(source_text) > settings.max_source_chars:
        raise QuizGenerationError(
            f"Study material is too large. Please use {settings.max_source_chars} "
            "characters or fewer."
        )

    prompt = build_material_prompt(cleaned_source, difficulty, question_count)
    return _generate_questions(prompt, question_count, source_text=source_text)
