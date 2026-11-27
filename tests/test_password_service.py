"""Unit tests for the password hashing service."""

from backend.app.services.password_service import hash_password, verify_password


def test_hash_password_returns_an_argon2id_hash() -> None:
    password = "temporary-test-password"

    stored_hash = hash_password(password)

    assert stored_hash
    assert stored_hash.startswith("$argon2id$")


def test_hashed_password_is_not_plaintext() -> None:
    password = "another-temporary-password"

    stored_hash = hash_password(password)

    assert stored_hash != password


def test_correct_password_verifies() -> None:
    password = "correct-test-password"
    stored_hash = hash_password(password)

    assert verify_password(password, stored_hash) is True


def test_incorrect_password_does_not_verify() -> None:
    password = "original-test-password"
    stored_hash = hash_password(password)

    assert verify_password("wrong-test-password", stored_hash) is False


def test_different_password_does_not_verify_against_original_hash() -> None:
    original_password = "first-test-password"
    different_password = "second-test-password"
    stored_hash = hash_password(original_password)

    assert verify_password(different_password, stored_hash) is False
