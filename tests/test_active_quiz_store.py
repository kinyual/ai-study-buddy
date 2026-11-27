"""Tests for the owner-scoped in-memory active quiz store."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from backend.app.schemas import GeneratedQuizQuestion
from backend.app.services import active_quiz_store as service


QUESTION_DATA = (
    {
        "question_text": "What does photosynthesis convert light into?",
        "option_a": "Heat energy",
        "option_b": "Chemical energy",
        "option_c": "Sound energy",
        "option_d": "Nuclear energy",
        "correct_option": "B",
        "explanation": "Photosynthesis converts light into chemical energy.",
        "source_snippet": "Photosynthesis converts light into chemical energy.",
    },
    {
        "question_text": "What do plants release during photosynthesis?",
        "option_a": "Nitrogen",
        "option_b": "Glucose",
        "option_c": "Oxygen",
        "option_d": "Carbon monoxide",
        "correct_option": "C",
        "explanation": "Plants release oxygen during photosynthesis.",
        "source_snippet": "Plants release oxygen during photosynthesis.",
    },
    {
        "question_text": "What absorbs sunlight in the leaf?",
        "option_a": "Chlorophyll",
        "option_b": "Glucose",
        "option_c": "Oxygen",
        "option_d": "The Calvin cycle",
        "correct_option": "A",
        "explanation": "Chlorophyll absorbs sunlight in the leaf.",
        "source_snippet": "Chlorophyll absorbs sunlight in the leaf.",
    },
    {
        "question_text": "Where does the light reaction take place?",
        "option_a": "In the leaf vein",
        "option_b": "In the thylakoid membrane",
        "option_c": "In the nucleus",
        "option_d": "In the cell wall",
        "correct_option": "B",
        "explanation": "The light reaction takes place in the thylakoid membrane.",
        "source_snippet": "The light reaction takes place in the thylakoid membrane.",
    },
    {
        "question_text": "What does the Calvin cycle produce?",
        "option_a": "Oxygen",
        "option_b": "Sunlight",
        "option_c": "Chlorophyll",
        "option_d": "Glucose",
        "correct_option": "D",
        "explanation": "The Calvin cycle produces glucose.",
        "source_snippet": "The Calvin cycle produces glucose.",
    },
)


def make_questions() -> list[GeneratedQuizQuestion]:
    """Return valid generated questions with answer-key fields."""
    return [
        GeneratedQuizQuestion(position=position, **data)
        for position, data in enumerate(QUESTION_DATA, start=1)
    ]


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test a fresh in-memory store."""
    monkeypatch.setattr(service, "_quizzes_by_id", {})
    monkeypatch.setattr(service, "_quiz_ids_by_owner", {})


def test_saved_quiz_ids_are_unique_32_character_hex_values() -> None:
    quiz_ids = [
        service.save_quiz(
            owner_id=1,
            difficulty="Easy",
            question_count=5,
            questions=make_questions(),
        ).quiz_id
        for _ in range(5)
    ]

    assert all(quiz_ids)
    assert len(set(quiz_ids)) == len(quiz_ids)
    assert all(len(quiz_id) == 32 for quiz_id in quiz_ids)
    assert all(
        all(character in "0123456789abcdef" for character in quiz_id)
        for quiz_id in quiz_ids
    )


def test_save_quiz_retains_metadata_and_full_questions() -> None:
    questions = make_questions()

    quiz = service.save_quiz(
        owner_id=7,
        difficulty="Medium",
        question_count=5,
        questions=questions,
        source_name="notes.txt",
    )

    assert quiz.owner_id == 7
    assert quiz.difficulty == "Medium"
    assert quiz.question_count == 5
    assert quiz.source_name == "notes.txt"
    assert quiz.submitted is False
    assert isinstance(quiz.questions, tuple)
    assert [item.model_dump() for item in quiz.questions] == [
        item.model_dump() for item in questions
    ]

    for original, stored in zip(questions, quiz.questions):
        assert stored.correct_option == original.correct_option
        assert stored.explanation == original.explanation
        assert stored.source_snippet == original.source_snippet


def test_correct_owner_can_retrieve_quiz() -> None:
    questions = make_questions()
    saved = service.save_quiz(9, "Hard", 5, questions)

    retrieved = service.get_owned_quiz(saved.quiz_id, 9)

    assert retrieved == saved
    assert [item.model_dump() for item in retrieved.questions] == [
        item.model_dump() for item in questions
    ]


def test_wrong_owner_gets_the_same_not_found_error_as_unknown_id() -> None:
    saved = service.save_quiz(1, "Easy", 5, make_questions())

    with pytest.raises(service.ActiveQuizNotFoundError) as wrong_owner:
        service.get_owned_quiz(saved.quiz_id, 2)
    with pytest.raises(service.ActiveQuizNotFoundError) as unknown_id:
        service.get_owned_quiz("does-not-exist", 2)

    assert type(wrong_owner.value) is type(unknown_id.value)
    assert str(wrong_owner.value) == str(unknown_id.value)


def test_mutating_questions_passed_to_save_does_not_change_stored_quiz() -> None:
    questions = make_questions()
    saved = service.save_quiz(3, "Easy", 5, questions)

    questions[0].question_text = "Mutated question"
    questions[0].correct_option = "A"
    questions[0].explanation = "Mutated explanation"
    questions[0].source_snippet = "Mutated snippet"
    questions.pop()

    stored = service.get_owned_quiz(saved.quiz_id, 3)

    assert len(stored.questions) == 5
    assert stored.questions[0].question_text == "What does photosynthesis convert light into?"
    assert stored.questions[0].correct_option == "B"
    assert stored.questions[0].explanation == (
        "Photosynthesis converts light into chemical energy."
    )
    assert stored.questions[0].source_snippet == (
        "Photosynthesis converts light into chemical energy."
    )


def test_mutating_retrieved_questions_does_not_change_stored_quiz() -> None:
    saved = service.save_quiz(4, "Medium", 5, make_questions())

    retrieved = service.get_owned_quiz(saved.quiz_id, 4)
    retrieved.questions[0].correct_option = "A"
    retrieved.questions[0].explanation = "Mutated explanation"
    retrieved.questions[0].source_snippet = "Mutated snippet"

    stored = service.get_owned_quiz(saved.quiz_id, 4)

    assert stored.questions[0].correct_option == "B"
    assert stored.questions[0].explanation == (
        "Photosynthesis converts light into chemical energy."
    )
    assert stored.questions[0].source_snippet == (
        "Photosynthesis converts light into chemical energy."
    )


def test_active_quiz_dataclass_rejects_field_replacement() -> None:
    quiz = service.save_quiz(5, "Easy", 5, make_questions())

    with pytest.raises(FrozenInstanceError):
        quiz.owner_id = 6


def test_first_submission_marks_quiz_and_second_does_not() -> None:
    saved = service.save_quiz(6, "Easy", 5, make_questions())

    assert service.mark_quiz_submitted(saved.quiz_id, 6) is True
    assert service.mark_quiz_submitted(saved.quiz_id, 6) is False
    assert service.get_owned_quiz(saved.quiz_id, 6).submitted is True


def test_submission_rejects_unknown_id_and_wrong_owner() -> None:
    saved = service.save_quiz(1, "Easy", 5, make_questions())

    with pytest.raises(service.ActiveQuizNotFoundError):
        service.mark_quiz_submitted("does-not-exist", 1)
    with pytest.raises(service.ActiveQuizNotFoundError):
        service.mark_quiz_submitted(saved.quiz_id, 2)


def test_concurrent_submissions_mark_quiz_exactly_once() -> None:
    worker_count = 8
    barrier = threading.Barrier(worker_count)
    saved = service.save_quiz(8, "Hard", 5, make_questions())

    def submit(_: int) -> bool:
        barrier.wait()
        return service.mark_quiz_submitted(saved.quiz_id, 8)

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(submit, range(worker_count)))

    assert results.count(True) == 1
    assert results.count(False) == worker_count - 1
    assert service.get_owned_quiz(saved.quiz_id, 8).submitted is True
