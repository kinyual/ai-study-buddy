"""Password hashing service backed by pwdlib's Argon2id recommendation."""

from pwdlib import PasswordHash

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password using pwdlib's recommended settings."""
    return _password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a plaintext password against a stored password hash."""
    return _password_hasher.verify(password, stored_hash)
