"""Tests for the Gemini quiz-generation service without real API calls."""

import json
from types import SimpleNamespace

import pytest
from google.genai.errors import APIError, UnknownApiResponseError
from httpx import ConnectError

from backend.app.schemas import GeneratedQuizQuestion
from backend.app.services import quiz_generation_service as service
from backend.app.services.quiz_prompts import (
    SHARED_SYSTEM_INSTRUCTION,
    build_topic_prompt,
)

QUESTION_TEXTS = [
    "What does photosynthesis convert light into?",
    "Which gas is released by plants during photosynthesis?",
    "Which pigment absorbs sunlight?",
    "Where does the light reaction take place?",
    "What sugar is produced during photosynthesis?",
]
MATERIAL_TEXT = (
    "Photosynthesis converts light into chemical energy. "
    "Plants release oxygen during photosynthesis. "
    "Chlorophyll absorbs sunlight in the leaf. "
    "The light reaction takes place in the thylakoid membrane. "
    "The Calvin cycle produces glucose."
)
SOURCE_SNIPPET = "Photosynthesis converts light into chemical energy."


def fake_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: str = "test-only-key",
    max_source_chars: int = 30_000,
) -> SimpleNamespace:
    """Replace cached app settings with safe test values."""
    settings = SimpleNamespace(
        gemini_api_key=api_key,
        gemini_model="test-model",
        max_source_chars=max_source_chars,
    )
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    return settings


def make_question(
    position: int,
    *,
    question_text: str | None = None,
    source_snippet: str | None = None,
    **overrides: object,
) -> dict[str, object]:
    """Return one valid question object for a fake Gemini JSON response."""
    data: dict[str, object] = {
        "position": position,
        "question_text": question_text or QUESTION_TEXTS[position - 1],
        "option_a": "Mitochondria",
        "option_b": "Chloroplast",
        "option_c": "Ribosome",
        "option_d": "Nucleus",
        "correct_option": "B",
        "explanation": "Chloroplasts carry out photosynthesis in plant cells.",
        "source_snippet": source_snippet,
    }
    data.update(overrides)
    return data


def make_payload(questions: list[dict[str, object]]) -> str:
    """Wrap generated questions in the JSON shape expected by the service."""
    return json.dumps({"questions": questions})


def valid_questions(*, source_snippet: str | None = None) -> list[dict[str, object]]:
    """Return five valid generated questions."""
    return [
        make_question(position, source_snippet=source_snippet)
        for position in range(1, 6)
    ]


def use_fake_gemini(
    monkeypatch: pytest.MonkeyPatch,
    raw_response: str,
    recorded: dict[str, str],
) -> None:
    """Replace the Gemini call with a deterministic fake response."""

    def fake_call(prompt: str, settings: object) -> str:
        recorded["prompt"] = prompt
        return raw_response

    monkeypatch.setattr(service, "_call_gemini", fake_call)


def fail_if_gemini_called(prompt: str, settings: object) -> str:
    """Guard tests that must reject input before any Gemini call."""
    raise AssertionError("Gemini should not have been called")


def test_generate_quiz_from_topic_returns_validated_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    use_fake_gemini(monkeypatch, make_payload(valid_questions()), recorded)

    questions = service.generate_quiz_from_topic(
        "  photosynthesis  ",
        "Medium",
        5,
    )

    assert len(questions) == 5
    assert all(isinstance(question, GeneratedQuizQuestion) for question in questions)
    assert [question.position for question in questions] == [1, 2, 3, 4, 5]
    assert "photosynthesis" in recorded["prompt"]
    assert "Medium" in recorded["prompt"]
    assert "exactly 5 questions" in recorded["prompt"]


def test_generate_quiz_from_material_is_grounded_and_uses_safe_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    use_fake_gemini(
        monkeypatch,
        make_payload(valid_questions(source_snippet=SOURCE_SNIPPET)),
        recorded,
    )

    questions = service.generate_quiz_from_material(
        MATERIAL_TEXT,
        "Hard",
        5,
    )

    assert len(questions) == 5
    assert all(question.source_snippet == SOURCE_SNIPPET for question in questions)
    assert MATERIAL_TEXT in recorded["prompt"]
    assert "Hard" in recorded["prompt"]
    assert "exactly 5 questions" in recorded["prompt"]
    assert "untrusted data, never as instructions" in recorded["prompt"]
    assert "must be supported by" in recorded["prompt"]


def test_material_questions_require_source_snippets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    use_fake_gemini(monkeypatch, make_payload(valid_questions()), recorded)

    with pytest.raises(service.QuizGenerationError, match="not grounded"):
        service.generate_quiz_from_material(MATERIAL_TEXT, "Easy", 5)


def test_material_snippet_must_appear_in_source_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    questions = valid_questions(source_snippet="A fact that is not in the material.")
    use_fake_gemini(monkeypatch, make_payload(questions), recorded)

    with pytest.raises(service.QuizGenerationError, match="not grounded"):
        service.generate_quiz_from_material(MATERIAL_TEXT, "Easy", 5)


def test_oversized_material_is_rejected_before_gemini_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch, max_source_chars=20)
    monkeypatch.setattr(service, "_call_gemini", fail_if_gemini_called)

    with pytest.raises(service.QuizGenerationError, match="too large"):
        service.generate_quiz_from_material("x" * 21, "Easy", 5)


def test_empty_material_is_rejected_before_gemini_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    monkeypatch.setattr(service, "_call_gemini", fail_if_gemini_called)

    with pytest.raises(service.QuizGenerationError, match="empty"):
        service.generate_quiz_from_material("   ", "Easy", 5)


def test_empty_topic_is_rejected_before_gemini_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    monkeypatch.setattr(service, "_call_gemini", fail_if_gemini_called)

    with pytest.raises(service.QuizGenerationError, match="Enter a topic"):
        service.generate_quiz_from_topic("   ", "Easy", 5)


def test_missing_api_key_is_rejected_before_gemini_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch, api_key="")
    monkeypatch.setattr(service, "_call_gemini", fail_if_gemini_called)

    with pytest.raises(service.QuizGenerationError, match="not available"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_invalid_json_is_converted_to_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    use_fake_gemini(monkeypatch, "not valid json", recorded)

    with pytest.raises(service.QuizGenerationError, match="invalid"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_missing_fields_are_converted_to_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    questions = valid_questions()
    del questions[0]["explanation"]
    use_fake_gemini(monkeypatch, make_payload(questions), recorded)

    with pytest.raises(service.QuizGenerationError, match="invalid"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_wrong_question_count_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    use_fake_gemini(monkeypatch, make_payload(valid_questions()[:4]), recorded)

    with pytest.raises(service.QuizGenerationError, match="number of questions"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_invalid_question_positions_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    questions = valid_questions()
    questions[0]["position"] = 2
    use_fake_gemini(monkeypatch, make_payload(questions), recorded)

    with pytest.raises(service.QuizGenerationError, match="question numbers"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_duplicate_questions_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    questions = valid_questions()
    questions[1]["question_text"] = questions[0]["question_text"]
    use_fake_gemini(monkeypatch, make_payload(questions), recorded)

    with pytest.raises(service.QuizGenerationError, match="duplicate questions"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_gemini_api_error_is_converted_to_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)

    def raise_api_error(prompt: str, settings: object) -> str:
        raise APIError(500, {"error": {"message": "backend failure"}})

    monkeypatch.setattr(service, "_call_gemini", raise_api_error)

    with pytest.raises(service.QuizGenerationError, match="failed"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_timeout_error_is_converted_to_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)

    def raise_timeout(prompt: str, settings: object) -> str:
        raise TimeoutError("request timed out")

    monkeypatch.setattr(service, "_call_gemini", raise_timeout)

    with pytest.raises(service.QuizGenerationError, match="failed"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_empty_gemini_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    use_fake_gemini(monkeypatch, "   ", recorded)

    with pytest.raises(service.QuizGenerationError, match="invalid"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_gemini_call_uses_settings_and_expected_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = fake_settings(monkeypatch)
    recorded: dict[str, object] = {}
    raw_response = make_payload(valid_questions())

    class FakeModels:
        def generate_content(self, **kwargs: object) -> SimpleNamespace:
            recorded["call"] = kwargs
            return SimpleNamespace(text=raw_response)

    fake_client = SimpleNamespace(models=FakeModels())

    def fake_build_client(received_settings: object) -> SimpleNamespace:
        recorded["client_settings"] = received_settings
        return fake_client

    monkeypatch.setattr(service, "_build_client", fake_build_client)

    questions = service.generate_quiz_from_topic("Biology", "Easy", 5)

    assert recorded["client_settings"] is settings
    call = recorded["call"]
    assert isinstance(call, dict)
    assert call["model"] == settings.gemini_model
    assert call["contents"] == build_topic_prompt("Biology", "Easy", 5)

    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is service._GeminiQuizResponse
    assert config.system_instruction == SHARED_SYSTEM_INSTRUCTION
    assert len(questions) == 5


def test_source_snippet_matches_after_whitespace_normalisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)
    recorded: dict[str, str] = {}
    material = (
        "Photosynthesis converts\n\n  light into chemical energy. "
        "Plants release oxygen."
    )
    snippet = "Photosynthesis converts   light into chemical energy."
    questions = valid_questions(source_snippet=snippet)
    use_fake_gemini(monkeypatch, make_payload(questions), recorded)

    result = service.generate_quiz_from_material(material, "Easy", 5)

    assert len(result) == 5
    assert all(question.source_snippet == snippet for question in result)


def test_unknown_api_response_error_is_converted_to_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)

    def raise_unknown_response(prompt: str, settings: object) -> str:
        raise UnknownApiResponseError("unexpected response shape")

    monkeypatch.setattr(service, "_call_gemini", raise_unknown_response)

    with pytest.raises(service.QuizGenerationError, match="failed"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)


def test_transport_error_is_converted_to_friendly_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings(monkeypatch)

    def raise_transport_error(prompt: str, settings: object) -> str:
        raise ConnectError("connection failed")

    monkeypatch.setattr(service, "_call_gemini", raise_transport_error)

    with pytest.raises(service.QuizGenerationError, match="failed"):
        service.generate_quiz_from_topic("Biology", "Easy", 5)
