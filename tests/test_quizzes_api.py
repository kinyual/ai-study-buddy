"""Shared fixtures and helpers for uploaded-quiz API tests."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from backend.app.api import quizzes as quizzes_api
from backend.app.api.deps import get_current_user, get_db
from backend.app.main import app
from backend.app.models import Base, QuizResult, QuizResultItem, User
from backend.app.services import (
    active_quiz_store,
    quiz_generation_service,
    token_service,
    upload_store,
)
from backend.app.services.quiz_result_service import (
    QuizResultAlreadyExistsError,
    QuizResultPersistenceError,
)
from backend.app.services.text_extraction_service import ExtractedMaterial
from backend.app.services.upload_store import StoredUpload

TEST_PASSWORD = "test-only-password"
TEST_TOKEN_SETTINGS = SimpleNamespace(
    jwt_secret_key="test-only-quiz-secret-longer-than-32-bytes",
    jwt_algorithm="HS256",
    access_token_expire_minutes=60,
)
STUDY_MATERIAL = (
    "Photosynthesis converts light into chemical energy. "
    "Plants release oxygen during photosynthesis. "
    "Chlorophyll absorbs sunlight in the leaf. "
    "The light reaction takes place in the thylakoid membrane. "
    "The Calvin cycle produces glucose."
)
QUESTION_FIXTURES: tuple[dict[str, object], ...] = (
    {
        "question_text": "What does photosynthesis convert light into?",
        "option_a": "Heat energy",
        "option_b": "Chemical energy",
        "option_c": "Sound energy",
        "option_d": "Nuclear energy",
        "correct_option": "B",
        "explanation": (
            "The material states that photosynthesis converts light into "
            "chemical energy."
        ),
        "source_snippet": "Photosynthesis converts light into chemical energy.",
    },
    {
        "question_text": "What do plants release during photosynthesis?",
        "option_a": "Nitrogen",
        "option_b": "Glucose",
        "option_c": "Oxygen",
        "option_d": "Carbon monoxide",
        "correct_option": "C",
        "explanation": "The material states that plants release oxygen.",
        "source_snippet": "Plants release oxygen during photosynthesis.",
    },
    {
        "question_text": "What absorbs sunlight in the leaf?",
        "option_a": "Chlorophyll",
        "option_b": "Glucose",
        "option_c": "Oxygen",
        "option_d": "The Calvin cycle",
        "correct_option": "A",
        "explanation": "The material states that chlorophyll absorbs sunlight.",
        "source_snippet": "Chlorophyll absorbs sunlight in the leaf.",
    },
    {
        "question_text": "Where does the light reaction take place?",
        "option_a": "In the leaf vein",
        "option_b": "In the thylakoid membrane",
        "option_c": "In the nucleus",
        "option_d": "In the cell wall",
        "correct_option": "B",
        "explanation": (
            "The material states that the light reaction takes place in the "
            "thylakoid membrane."
        ),
        "source_snippet": "The light reaction takes place in the thylakoid membrane.",
    },
    {
        "question_text": "What does the Calvin cycle produce?",
        "option_a": "Oxygen",
        "option_b": "Sunlight",
        "option_c": "Chlorophyll",
        "option_d": "Glucose",
        "correct_option": "D",
        "explanation": "The material states that the Calvin cycle produces glucose.",
        "source_snippet": "The Calvin cycle produces glucose.",
    },
)


def quiz_settings(
    *,
    api_key: str = "test-only-gemini-key",
    gemini_model: str = "test-model",
    max_source_chars: int = 30_000,
) -> SimpleNamespace:
    """Return safe, predictable quiz-generation settings."""
    return SimpleNamespace(
        gemini_api_key=api_key,
        gemini_model=gemini_model,
        max_source_chars=max_source_chars,
    )


def patch_quiz_settings(
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: object,
) -> SimpleNamespace:
    """Replace cached Gemini settings for the duration of one test."""
    settings = quiz_settings(**kwargs)
    monkeypatch.setattr(
        quiz_generation_service,
        "get_settings",
        lambda: settings,
    )
    return settings


def make_question(
    position: int,
    *,
    source_snippet: str | None = None,
    **overrides: object,
) -> dict[str, object]:
    """Return one valid generated question grounded in the test material."""
    fixture = QUESTION_FIXTURES[position - 1]
    data: dict[str, object] = {
        "position": position,
        "question_text": fixture["question_text"],
        "option_a": fixture["option_a"],
        "option_b": fixture["option_b"],
        "option_c": fixture["option_c"],
        "option_d": fixture["option_d"],
        "correct_option": fixture["correct_option"],
        "explanation": fixture["explanation"],
        "source_snippet": (
            fixture["source_snippet"] if source_snippet is None else source_snippet
        ),
    }
    data.update(overrides)
    return data


def valid_questions(
    *,
    source_snippet: str | None = None,
) -> list[dict[str, object]]:
    """Return five valid questions with question-specific grounded snippets."""
    return [
        make_question(position, source_snippet=source_snippet)
        for position in range(1, len(QUESTION_FIXTURES) + 1)
    ]


def make_payload(questions: list[dict[str, object]]) -> str:
    """Wrap generated questions in the JSON shape expected by the service."""
    return json.dumps({"questions": questions})


def use_fake_gemini(
    monkeypatch: pytest.MonkeyPatch,
    raw_response: str | None = None,
    recorded: dict[str, object] | None = None,
) -> dict[str, object]:
    """Patch the Gemini call so tests never contact the real API."""
    if raw_response is None:
        raw_response = make_payload(valid_questions())
    if recorded is None:
        recorded = {}

    def fake_call(prompt: str, settings: object) -> str:
        recorded["prompt"] = prompt
        recorded["settings"] = settings
        return raw_response

    monkeypatch.setattr(quiz_generation_service, "_call_gemini", fake_call)
    return recorded


def fail_if_gemini_called(prompt: str, settings: object) -> str:
    """Guard tests that must reject input before any Gemini call."""
    raise AssertionError("Gemini should not have been called")


def store_material(
    owner_id: int,
    *,
    text: str = STUDY_MATERIAL,
    source_name: str = "notes.txt",
    file_type: str = "txt",
) -> StoredUpload:
    """Store extracted material directly in the isolated test upload store."""
    return upload_store.save_upload(
        owner_id,
        ExtractedMaterial(
            source_name=source_name,
            file_type=file_type,
            text=text,
            char_count=len(text),
        ),
    )


@pytest.fixture(autouse=True)
def isolated_upload_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every quiz API test a fresh in-memory upload store."""
    monkeypatch.setattr(upload_store, "_uploads_by_id", {})
    monkeypatch.setattr(upload_store, "_current_upload_by_owner", {})


@pytest.fixture(autouse=True)
def isolated_active_quiz_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every quiz API test a fresh in-memory active quiz store."""
    monkeypatch.setattr(active_quiz_store, "_quizzes_by_id", {})
    monkeypatch.setattr(active_quiz_store, "_quiz_ids_by_owner", {})


@pytest.fixture
def quizzes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker]]:
    """Provide a client backed by a fresh database and fake Gemini settings."""
    monkeypatch.setattr(token_service, "get_settings", lambda: TEST_TOKEN_SETTINGS)
    patch_quiz_settings(monkeypatch)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Iterator[Session]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield client, test_session_factory
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def register_and_login(
    client: TestClient,
    email: str,
) -> tuple[int, dict[str, str]]:
    """Create one user and return their id plus bearer headers."""
    registered = client.post(
        "/auth/register",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert registered.status_code == 201

    logged_in = client.post(
        "/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert logged_in.status_code == 200

    token = logged_in.json()["access_token"]
    return registered.json()["id"], {"Authorization": f"Bearer {token}"}


def generate_quiz(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    email: str,
    *,
    source_name: str = "notes.txt",
) -> tuple[int, dict[str, str], str]:
    """Create one user and generate a quiz for submission tests."""
    owner_id, headers = register_and_login(client, email)
    stored = store_material(owner_id, source_name=source_name)
    use_fake_gemini(monkeypatch)

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )
    assert response.status_code == 200
    return owner_id, headers, response.json()["quiz_id"]


def generate_quiz_for_owner(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    owner_id: int,
    headers: dict[str, str],
    *,
    source_name: str = "notes.txt",
) -> str:
    """Generate another quiz for an already registered owner."""
    stored = store_material(owner_id, source_name=source_name)
    use_fake_gemini(monkeypatch)

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 200
    return response.json()["quiz_id"]


def save_result_for_owner(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    owner_id: int,
    headers: dict[str, str],
    *,
    source_name: str = "notes.txt",
    selected: dict[int, str] | None = None,
) -> str:
    """Create one completed result for an already registered owner."""
    quiz_id = generate_quiz_for_owner(
        client,
        monkeypatch,
        owner_id,
        headers,
        source_name=source_name,
    )
    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id, selected),
    )

    assert response.status_code == 200
    return quiz_id


def correct_selections() -> dict[int, str]:
    """Return the correct option for every test question position."""
    return {
        position: str(QUESTION_FIXTURES[position - 1]["correct_option"])
        for position in range(1, len(QUESTION_FIXTURES) + 1)
    }


def submission_body(
    quiz_id: str,
    selected: dict[int, str] | None = None,
    *,
    positions: list[int] | None = None,
) -> dict[str, object]:
    """Build a submission body, optionally overriding answers or positions."""
    selections = correct_selections() if selected is None else selected
    if positions is None:
        positions = list(selections)

    return {
        "quiz_id": quiz_id,
        "answers": [
            {
                "position": position,
                "selected_option": selections.get(position, "A"),
            }
            for position in positions
        ],
    }


def saved_result_count(session_factory: sessionmaker, quiz_id: str) -> int:
    """Count saved result rows for one quiz id."""
    with session_factory() as db:
        return int(
            db.execute(
                select(func.count())
                .select_from(QuizResult)
                .where(QuizResult.quiz_id == quiz_id)
            ).scalar_one()
        )


def saved_result_id(session_factory: sessionmaker, quiz_id: str) -> int:
    """Return the database id of one saved result."""
    with session_factory() as db:
        return int(
            db.execute(
                select(QuizResult.id).where(QuizResult.quiz_id == quiz_id)
            ).scalar_one()
        )


def saved_item_count(session_factory: sessionmaker, quiz_id: str) -> int:
    """Count saved review items belonging to one quiz id."""
    with session_factory() as db:
        return int(
            db.execute(
                select(func.count())
                .select_from(QuizResultItem)
                .join(QuizResult, QuizResultItem.result_id == QuizResult.id)
                .where(QuizResult.quiz_id == quiz_id)
            ).scalar_one()
        )


def saved_result_snapshot(
    session_factory: sessionmaker,
    quiz_id: str,
) -> tuple[dict[str, object], list[dict[str, object]]] | None:
    """Return plain data from one saved result without detached ORM objects."""
    with session_factory() as db:
        row = db.execute(
            select(QuizResult).where(QuizResult.quiz_id == quiz_id)
        ).scalar_one_or_none()
        if row is None:
            return None

        items = (
            db.execute(
                select(QuizResultItem)
                .where(QuizResultItem.result_id == row.id)
                .order_by(QuizResultItem.position)
            )
            .scalars()
            .all()
        )
        return (
            {
                "id": row.id,
                "user_id": row.user_id,
                "quiz_id": row.quiz_id,
                "mode": row.mode,
                "topic": row.topic,
                "source_name": row.source_name,
                "difficulty": row.difficulty,
                "question_count": row.question_count,
                "score": row.score,
                "percentage": row.percentage,
            },
            [
                {
                    "position": item.position,
                    "question_text": item.question_text,
                    "option_a": item.option_a,
                    "option_b": item.option_b,
                    "option_c": item.option_c,
                    "option_d": item.option_d,
                    "correct_option": item.correct_option,
                    "selected_option": item.selected_option,
                    "is_correct": item.is_correct,
                    "explanation": item.explanation,
                    "source_snippet": item.source_snippet,
                }
                for item in items
            ],
        )


def test_authenticated_user_can_generate_quiz_from_own_upload(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "quiz-owner@example.com")
    stored = store_material(owner_id)
    recorded = use_fake_gemini(monkeypatch)

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Medium",
            "question_count": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"quiz_id", "difficulty", "question_count", "questions"}
    assert data["quiz_id"]
    assert data["difficulty"] == "Medium"
    assert data["question_count"] == 5
    assert len(data["questions"]) == 5
    assert STUDY_MATERIAL in recorded["prompt"]


def test_generated_quiz_response_hides_answers_and_explanations(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "quiz-privacy@example.com")
    stored = store_material(owner_id)
    use_fake_gemini(monkeypatch)

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 200
    questions = response.json()["questions"]

    for position, question in enumerate(questions, start=1):
        expected = QUESTION_FIXTURES[position - 1]
        assert set(question) == {
            "position",
            "question_text",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "source_snippet",
        }
        assert question["position"] == position
        assert question["question_text"] == expected["question_text"]
        assert question["option_a"] == expected["option_a"]
        assert question["option_b"] == expected["option_b"]
        assert question["option_c"] == expected["option_c"]
        assert question["option_d"] == expected["option_d"]
        assert question["source_snippet"] == expected["source_snippet"]
        assert "correct_option" not in question
        assert "explanation" not in question


def test_generated_quiz_is_saved_in_active_store_with_full_answer_key(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "quiz-store@example.com")
    stored_upload = store_material(owner_id)
    use_fake_gemini(monkeypatch)

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored_upload.upload_id,
            "difficulty": "Hard",
            "question_count": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()
    quiz_id = data["quiz_id"]
    assert len(quiz_id) == 32

    active_quiz = active_quiz_store.get_owned_quiz(quiz_id, owner_id)

    assert active_quiz.quiz_id == quiz_id
    assert active_quiz.owner_id == owner_id
    assert active_quiz.difficulty == "Hard"
    assert active_quiz.question_count == 5
    assert active_quiz.submitted is False
    assert len(active_quiz.questions) == 5

    for position, (question, expected) in enumerate(
        zip(active_quiz.questions, QUESTION_FIXTURES),
        start=1,
    ):
        assert question.position == position
        assert question.question_text == expected["question_text"]
        assert question.correct_option == expected["correct_option"]
        assert question.explanation == expected["explanation"]
        assert question.source_snippet == expected["source_snippet"]

    with pytest.raises(active_quiz_store.ActiveQuizNotFoundError):
        active_quiz_store.get_owned_quiz(quiz_id, owner_id + 1)

    for question in data["questions"]:
        assert "correct_option" not in question
        assert "explanation" not in question


def test_uploaded_quiz_requires_authentication(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, _ = register_and_login(client, "quiz-auth-owner@example.com")
    stored = store_material(owner_id)
    recorded = use_fake_gemini(monkeypatch)

    response = client.post(
        "/quizzes/uploaded",
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 401
    assert "prompt" not in recorded


def test_unknown_upload_returns_not_found(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    _, headers = register_and_login(client, "quiz-unknown@example.com")
    monkeypatch.setattr(
        quiz_generation_service,
        "_call_gemini",
        fail_if_gemini_called,
    )

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": "unknown-upload-id",
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Upload not found."}


def test_another_users_upload_returns_same_not_found_response(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, _ = register_and_login(client, "quiz-owner-a@example.com")
    _, other_headers = register_and_login(client, "quiz-owner-b@example.com")
    stored = store_material(owner_id)
    monkeypatch.setattr(
        quiz_generation_service,
        "_call_gemini",
        fail_if_gemini_called,
    )
    payload = {"difficulty": "Hard", "question_count": 5}

    unknown = client.post(
        "/quizzes/uploaded",
        headers=other_headers,
        json={**payload, "upload_id": "unknown-upload-id"},
    )
    wrong_owner = client.post(
        "/quizzes/uploaded",
        headers=other_headers,
        json={**payload, "upload_id": stored.upload_id},
    )

    assert unknown.status_code == 404
    assert wrong_owner.status_code == 404
    assert wrong_owner.json() == unknown.json()
    assert wrong_owner.json() == {"detail": "Upload not found."}


@pytest.mark.parametrize(
    "payload",
    [
        {"upload_id": "upload-id", "difficulty": "Very Hard", "question_count": 5},
        {"upload_id": "upload-id", "difficulty": "Easy", "question_count": 7},
        {"upload_id": "   ", "difficulty": "Easy", "question_count": 5},
    ],
    ids=["invalid-difficulty", "invalid-question-count", "blank-upload-id"],
)
def test_invalid_request_payloads_are_rejected_before_generation(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    client, _ = quizzes_client
    _, headers = register_and_login(client, "invalid-request@example.com")
    monkeypatch.setattr(
        quiz_generation_service,
        "_call_gemini",
        fail_if_gemini_called,
    )

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


def test_empty_stored_material_returns_bad_gateway(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "empty-material@example.com")
    stored = store_material(owner_id, text="   ")
    monkeypatch.setattr(
        quiz_generation_service,
        "_call_gemini",
        fail_if_gemini_called,
    )

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 502
    assert "Study material is empty" in response.json()["detail"]


def test_oversized_stored_material_returns_bad_gateway(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    patch_quiz_settings(monkeypatch, max_source_chars=20)
    owner_id, headers = register_and_login(client, "oversized-material@example.com")
    stored = store_material(owner_id)
    monkeypatch.setattr(
        quiz_generation_service,
        "_call_gemini",
        fail_if_gemini_called,
    )

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 502
    assert "too large" in response.json()["detail"]


def test_gemini_failure_returns_friendly_bad_gateway(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "gemini-failure@example.com")
    stored = store_material(owner_id)

    def raise_timeout(prompt: str, settings: object) -> str:
        raise TimeoutError("internal timeout detail must not be exposed")

    monkeypatch.setattr(quiz_generation_service, "_call_gemini", raise_timeout)

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Quiz generation failed. Please try again."
    }
    assert "internal timeout detail must not be exposed" not in response.text


def test_invalid_gemini_json_returns_bad_gateway(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "invalid-gemini-json@example.com")
    stored = store_material(owner_id)
    use_fake_gemini(monkeypatch, raw_response="not valid json")

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The generated quiz was invalid. Please try again."
    }


def test_ungrounded_gemini_output_returns_bad_gateway(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "ungrounded-output@example.com")
    stored = store_material(owner_id)
    invalid_questions = valid_questions(
        source_snippet="A fact that is not in the study material."
    )
    use_fake_gemini(
        monkeypatch,
        raw_response=make_payload(invalid_questions),
    )

    response = client.post(
        "/quizzes/uploaded",
        headers=headers,
        json={
            "upload_id": stored.upload_id,
            "difficulty": "Easy",
            "question_count": 5,
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "The generated quiz was not grounded in the supplied material. "
            "Please try again."
        )
    }


def test_successful_submission_returns_score_and_per_question_review(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    _, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-review@example.com"
    )
    selected = correct_selections()
    selected[2] = "A"
    selected[4] = "A"

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id, selected),
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "quiz_id",
        "score",
        "total_questions",
        "percentage",
        "results",
    }
    assert data["quiz_id"] == quiz_id
    assert data["score"] == 3
    assert data["total_questions"] == 5
    assert data["percentage"] == 60.0

    results = data["results"]
    assert [item["position"] for item in results] == [1, 2, 3, 4, 5]
    for position, (item, expected) in enumerate(
        zip(results, QUESTION_FIXTURES),
        start=1,
    ):
        assert set(item) == {
            "position",
            "question_text",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "source_snippet",
            "correct_option",
            "selected_option",
            "is_correct",
            "explanation",
        }
        assert item["question_text"] == expected["question_text"]
        assert item["option_a"] == expected["option_a"]
        assert item["option_b"] == expected["option_b"]
        assert item["option_c"] == expected["option_c"]
        assert item["option_d"] == expected["option_d"]
        assert item["source_snippet"] == expected["source_snippet"]
        assert item["correct_option"] == expected["correct_option"]
        assert item["selected_option"] == selected[position]
        assert item["is_correct"] is (
            selected[position] == expected["correct_option"]
        )
        assert item["explanation"] == expected["explanation"]


def test_successful_submission_marks_quiz_as_submitted(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-marked@example.com"
    )
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id),
    )

    assert response.status_code == 200
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is True


def test_submission_requires_authentication(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, _, quiz_id = generate_quiz(
        client, monkeypatch, "submit-auth@example.com"
    )

    response = client.post(
        "/quizzes/submit",
        json=submission_body(quiz_id),
    )

    assert response.status_code == 401
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False
    assert saved_result_count(session_factory, quiz_id) == 0


def test_unknown_quiz_returns_not_found(quizzes_client) -> None:
    client, _ = quizzes_client
    _, headers = register_and_login(client, "submit-unknown@example.com")

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body("does-not-exist"),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Quiz not found."}


def test_another_users_quiz_returns_same_not_found_response(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, _, quiz_id = generate_quiz(
        client, monkeypatch, "submit-hidden-owner@example.com"
    )
    _, other_headers = register_and_login(client, "submit-hidden-other@example.com")

    unknown = client.post(
        "/quizzes/submit",
        headers=other_headers,
        json=submission_body("does-not-exist"),
    )
    wrong_owner = client.post(
        "/quizzes/submit",
        headers=other_headers,
        json=submission_body(quiz_id),
    )

    assert unknown.status_code == 404
    assert wrong_owner.status_code == 404
    assert wrong_owner.json() == unknown.json()
    assert wrong_owner.json() == {"detail": "Quiz not found."}
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False
    assert saved_result_count(session_factory, quiz_id) == 0


@pytest.mark.parametrize("case", ["invalid-option", "duplicate-position"])
def test_invalid_submission_bodies_are_rejected_by_request_validation(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    client, _ = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-bad-body@example.com"
    )

    if case == "invalid-option":
        selected = correct_selections()
        selected[1] = "E"
        body = submission_body(quiz_id, selected)
    else:
        body = submission_body(quiz_id, positions=[1, 1, 2, 3, 4])

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=body,
    )

    assert response.status_code == 422
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False


@pytest.mark.parametrize(
    "positions",
    [
        [1, 2, 3, 4],
        [1, 2, 3, 4, 5, 6],
        [1, 2, 99, 4, 5],
    ],
    ids=["missing", "extra", "out-of-range"],
)
def test_invalid_answer_coverage_returns_422_without_marking_submitted(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
    positions: list[int],
) -> None:
    client, _ = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-coverage@example.com"
    )

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id, positions=positions),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Submit exactly one answer for every quiz question."
    )
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False


def test_invalid_submission_leaves_quiz_available_for_correction(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-retry@example.com"
    )

    invalid = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id, positions=[1, 2, 3, 4]),
    )
    assert invalid.status_code == 422
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False

    corrected = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id),
    )
    assert corrected.status_code == 200
    assert corrected.json()["score"] == 5


def test_repeated_submission_returns_conflict(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    _, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-repeat@example.com"
    )
    body = submission_body(quiz_id)

    first = client.post("/quizzes/submit", headers=headers, json=body)
    second = client.post("/quizzes/submit", headers=headers, json=body)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": "Quiz has already been submitted."}
    assert saved_result_count(session_factory, quiz_id) == 1
    assert saved_item_count(session_factory, quiz_id) == 5


def test_another_user_cannot_submit_owned_quiz(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, owner_headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-owner-only@example.com"
    )
    _, other_headers = register_and_login(client, "submit-intruder@example.com")

    denied = client.post(
        "/quizzes/submit",
        headers=other_headers,
        json=submission_body(quiz_id),
    )
    assert denied.status_code == 404
    assert denied.json() == {"detail": "Quiz not found."}
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False
    assert saved_result_count(session_factory, quiz_id) == 0

    allowed = client.post(
        "/quizzes/submit",
        headers=owner_headers,
        json=submission_body(quiz_id),
    )
    assert allowed.status_code == 200
    assert saved_result_count(session_factory, quiz_id) == 1


def test_two_simultaneous_submissions_cannot_both_succeed(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, _ = quizzes_client
    owner_id, _, quiz_id = generate_quiz(
        client, monkeypatch, "submit-concurrent@example.com"
    )
    barrier = threading.Barrier(2)
    body = submission_body(quiz_id)

    # The fixture's in-memory database uses one shared SQLite connection. Use a
    # temporary file with separate connections so the two requests exercise the
    # database uniqueness rule instead of fighting over one connection.
    database_path = tmp_path / "concurrent_results.db"
    concurrent_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
        poolclass=NullPool,
    )
    Base.metadata.create_all(bind=concurrent_engine)
    concurrent_factory = sessionmaker(
        bind=concurrent_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    with concurrent_factory() as db:
        db.add(
            User(
                id=owner_id,
                email="concurrent-results@example.com",
                password_hash="test-only-hash",
            )
        )
        db.commit()

    def override_concurrent_db() -> Iterator[Session]:
        db = concurrent_factory()
        try:
            yield db
        finally:
            db.close()

    had_previous_db_override = get_db in app.dependency_overrides
    previous_db_override = app.dependency_overrides.get(get_db)
    had_previous_user_override = get_current_user in app.dependency_overrides
    previous_user_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_db] = override_concurrent_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=owner_id)
    try:
        def submit(_: int) -> int:
            barrier.wait()
            return client.post("/quizzes/submit", json=body).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, range(2)))
    finally:
        if had_previous_user_override:
            app.dependency_overrides[get_current_user] = previous_user_override
        else:
            app.dependency_overrides.pop(get_current_user, None)
        if had_previous_db_override:
            app.dependency_overrides[get_db] = previous_db_override
        else:
            app.dependency_overrides.pop(get_db, None)
        concurrent_engine.dispose()

    assert sorted(statuses) == [200, 409]
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is True
    assert saved_result_count(concurrent_factory, quiz_id) == 1
    assert saved_item_count(concurrent_factory, quiz_id) == 5


def test_successful_submission_persists_one_complete_result(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client,
        monkeypatch,
        "submit-persist@example.com",
        source_name="chapter-1.pdf",
    )
    selected = correct_selections()
    selected[2] = "A"
    selected[4] = "A"

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id, selected),
    )

    assert response.status_code == 200
    assert saved_result_count(session_factory, quiz_id) == 1
    assert saved_item_count(session_factory, quiz_id) == 5

    snapshot = saved_result_snapshot(session_factory, quiz_id)
    assert snapshot is not None
    row, items = snapshot
    assert row["user_id"] == owner_id
    assert row["quiz_id"] == quiz_id
    assert row["mode"] == "uploaded"
    assert row["topic"] is None
    assert row["source_name"] == "chapter-1.pdf"
    assert row["difficulty"] == "Easy"
    assert row["question_count"] == 5
    assert row["score"] == 3
    assert row["percentage"] == 60.0
    assert [item["position"] for item in items] == [1, 2, 3, 4, 5]

    for position, (item, expected) in enumerate(
        zip(items, QUESTION_FIXTURES),
        start=1,
    ):
        assert item["question_text"] == expected["question_text"]
        assert item["option_a"] == expected["option_a"]
        assert item["option_b"] == expected["option_b"]
        assert item["option_c"] == expected["option_c"]
        assert item["option_d"] == expected["option_d"]
        assert item["correct_option"] == expected["correct_option"]
        assert item["selected_option"] == selected[position]
        assert item["is_correct"] is (
            selected[position] == expected["correct_option"]
        )
        assert item["explanation"] == expected["explanation"]
        assert item["source_snippet"] == expected["source_snippet"]


@pytest.mark.parametrize(
    "case",
    ["invalid-option", "missing-position"],
    ids=["invalid-option", "missing-position"],
)
def test_invalid_submissions_create_no_saved_results(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    client, session_factory = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-no-save@example.com"
    )

    if case == "invalid-option":
        selected = correct_selections()
        selected[1] = "E"
        body = submission_body(quiz_id, selected)
    else:
        body = submission_body(quiz_id, positions=[1, 2, 3, 4])

    response = client.post("/quizzes/submit", headers=headers, json=body)

    assert response.status_code == 422
    assert saved_result_count(session_factory, quiz_id) == 0
    assert saved_item_count(session_factory, quiz_id) == 0
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False


def test_duplicate_result_error_returns_existing_conflict(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-duplicate-result@example.com"
    )

    def raise_duplicate(*_args: object, **_kwargs: object) -> None:
        raise QuizResultAlreadyExistsError("duplicate detail must not be exposed")

    monkeypatch.setattr(quizzes_api, "save_quiz_result", raise_duplicate)

    response = client.post(
        "/quizzes/submit",
        headers=headers,
        json=submission_body(quiz_id),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Quiz has already been submitted."}
    assert "duplicate detail must not be exposed" not in response.text
    assert saved_result_count(session_factory, quiz_id) == 0
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False


def test_persistence_failure_returns_503_and_allows_retry(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, headers, quiz_id = generate_quiz(
        client, monkeypatch, "submit-db-failure@example.com"
    )
    body = submission_body(quiz_id)
    real_save = quizzes_api.save_quiz_result
    should_fail = {"value": True}

    def fail_once(*args: object, **kwargs: object) -> None:
        if should_fail["value"]:
            raise QuizResultPersistenceError(
                "internal database detail must not be exposed"
            )
        real_save(*args, **kwargs)

    monkeypatch.setattr(quizzes_api, "save_quiz_result", fail_once)

    failed = client.post("/quizzes/submit", headers=headers, json=body)

    assert failed.status_code == 503
    assert failed.json() == {
        "detail": "Quiz result could not be saved. Please try again."
    }
    assert "internal database detail must not be exposed" not in failed.text
    assert saved_result_count(session_factory, quiz_id) == 0
    assert saved_item_count(session_factory, quiz_id) == 0
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is False

    should_fail["value"] = False
    retried = client.post("/quizzes/submit", headers=headers, json=body)

    assert retried.status_code == 200
    assert saved_result_count(session_factory, quiz_id) == 1
    assert active_quiz_store.get_owned_quiz(quiz_id, owner_id).submitted is True


def test_empty_history_returns_empty_list(quizzes_client) -> None:
    client, _ = quizzes_client
    _, headers = register_and_login(client, "history-empty@example.com")

    response = client.get("/quizzes/results", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


def test_history_lists_completed_results_newest_first(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "history-order@example.com")
    quiz_ids = [
        save_result_for_owner(
            client,
            monkeypatch,
            owner_id,
            headers,
            source_name=source_name,
        )
        for source_name in ("first.txt", "second.txt", "third.txt")
    ]

    response = client.get("/quizzes/results", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert [row["quiz_id"] for row in data] == list(reversed(quiz_ids))


def test_history_includes_only_the_authenticated_users_results(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, owner_headers = register_and_login(client, "history-owner@example.com")
    other_id, other_headers = register_and_login(client, "history-other@example.com")
    owner_quiz_id = save_result_for_owner(
        client,
        monkeypatch,
        owner_id,
        owner_headers,
        source_name="owner-notes.txt",
    )
    other_quiz_id = save_result_for_owner(
        client,
        monkeypatch,
        other_id,
        other_headers,
        source_name="other-notes.txt",
    )

    owner_history = client.get("/quizzes/results", headers=owner_headers)
    other_history = client.get("/quizzes/results", headers=other_headers)

    assert owner_history.status_code == 200
    assert other_history.status_code == 200
    assert [row["quiz_id"] for row in owner_history.json()] == [owner_quiz_id]
    assert [row["quiz_id"] for row in other_history.json()] == [other_quiz_id]


def test_history_summaries_hide_question_review_details(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = quizzes_client
    owner_id, headers = register_and_login(client, "history-summary@example.com")
    save_result_for_owner(
        client,
        monkeypatch,
        owner_id,
        headers,
        source_name="summary-notes.txt",
    )

    response = client.get("/quizzes/results", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert set(data[0]) == {
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
    }
    for forbidden in (
        "results",
        "correct_option",
        "selected_option",
        "explanation",
        "source_snippet",
    ):
        assert forbidden not in response.text


def test_individual_result_detail_returns_complete_saved_review(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, headers = register_and_login(client, "history-detail@example.com")
    selected = correct_selections()
    selected[2] = "A"
    selected[4] = "A"
    quiz_id = save_result_for_owner(
        client,
        monkeypatch,
        owner_id,
        headers,
        source_name="detail-review.pdf",
        selected=selected,
    )
    result_id = saved_result_id(session_factory, quiz_id)

    response = client.get(f"/quizzes/results/{result_id}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
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
    assert data["id"] == result_id
    assert data["quiz_id"] == quiz_id
    assert data["mode"] == "uploaded"
    assert data["topic"] is None
    assert data["source_name"] == "detail-review.pdf"
    assert data["difficulty"] == "Easy"
    assert data["question_count"] == 5
    assert data["total_questions"] == 5
    assert data["score"] == 3
    assert data["percentage"] == 60.0
    assert len(data["results"]) == 5

    for position, (item, expected) in enumerate(
        zip(data["results"], QUESTION_FIXTURES),
        start=1,
    ):
        assert set(item) == {
            "position",
            "question_text",
            "option_a",
            "option_b",
            "option_c",
            "option_d",
            "source_snippet",
            "correct_option",
            "selected_option",
            "is_correct",
            "explanation",
        }
        assert item["position"] == position
        assert item["question_text"] == expected["question_text"]
        assert item["option_a"] == expected["option_a"]
        assert item["option_b"] == expected["option_b"]
        assert item["option_c"] == expected["option_c"]
        assert item["option_d"] == expected["option_d"]
        assert item["source_snippet"] == expected["source_snippet"]
        assert item["correct_option"] == expected["correct_option"]
        assert item["selected_option"] == selected[position]
        assert item["is_correct"] is (
            selected[position] == expected["correct_option"]
        )
        assert item["explanation"] == expected["explanation"]


def test_individual_result_review_items_are_in_position_order(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, headers = register_and_login(client, "history-order-items@example.com")
    quiz_id = save_result_for_owner(client, monkeypatch, owner_id, headers)
    result_id = saved_result_id(session_factory, quiz_id)

    response = client.get(f"/quizzes/results/{result_id}", headers=headers)

    assert response.status_code == 200
    assert [item["position"] for item in response.json()["results"]] == [1, 2, 3, 4, 5]


def test_result_detail_hides_other_users_result_and_unknown_id(
    quizzes_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = quizzes_client
    owner_id, owner_headers = register_and_login(
        client,
        "history-hidden-owner@example.com",
    )
    _, other_headers = register_and_login(
        client,
        "history-hidden-other@example.com",
    )
    quiz_id = save_result_for_owner(client, monkeypatch, owner_id, owner_headers)
    result_id = saved_result_id(session_factory, quiz_id)

    other_users_result = client.get(
        f"/quizzes/results/{result_id}",
        headers=other_headers,
    )
    unknown_result = client.get(
        "/quizzes/results/999999",
        headers=other_headers,
    )

    assert other_users_result.status_code == 404
    assert unknown_result.status_code == 404
    assert other_users_result.json() == unknown_result.json()
    assert other_users_result.json() == {"detail": "Quiz result not found."}


@pytest.mark.parametrize("path", ["/quizzes/results", "/quizzes/results/1"])
def test_history_endpoints_require_authentication(quizzes_client, path: str) -> None:
    client, _ = quizzes_client

    response = client.get(path)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("raw_result_id", "expected_status"),
    [("not-an-int", 422), ("0", 404)],
)
def test_invalid_result_ids_are_handled_safely(
    quizzes_client,
    raw_result_id: str,
    expected_status: int,
) -> None:
    client, _ = quizzes_client
    _, headers = register_and_login(client, "history-invalid-id@example.com")

    response = client.get(f"/quizzes/results/{raw_result_id}", headers=headers)

    assert response.status_code == expected_status
    if expected_status == 404:
        assert response.json() == {"detail": "Quiz result not found."}
