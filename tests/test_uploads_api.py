"""Tests for the authenticated study-material upload endpoint."""

import asyncio
from io import BytesIO
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace
from typing import Iterator

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import starlette.formparsers as starlette_formparsers
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException

from backend.app.api import uploads
from backend.app.api.deps import get_db
from backend.app.api.upload_parser import LimitedMultipartParser, UploadTooLargeError
from backend.app.main import app
from backend.app.models import Base
from backend.app.services import token_service, upload_store

TEST_TOKEN_SETTINGS = SimpleNamespace(
    jwt_secret_key="test-only-upload-secret-longer-than-32-bytes",
    jwt_algorithm="HS256",
    access_token_expire_minutes=60,
)
TEST_PASSWORD = "test-only-password"
STUDY_TEXT = "Photosynthesis converts light into chemical energy."
DEFAULT_LIMIT = 5 * 1024 * 1024
LARGE_LIMIT = 1024 * 1024 + 64


def upload_settings(
    *,
    max_upload_bytes: int = DEFAULT_LIMIT,
    max_upload_mb: int = 5,
    max_source_chars: int = 30_000,
) -> SimpleNamespace:
    """Return small, predictable settings for upload endpoint tests."""
    return SimpleNamespace(
        max_upload_bytes=max_upload_bytes,
        max_upload_mb=max_upload_mb,
        max_source_chars=max_source_chars,
    )


def make_pdf(text: str) -> bytes:
    """Build a small in-memory PDF with selectable text."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 18 Tf 72 700 Td ({escaped}) Tj ET".encode("utf-8")

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    content = DecodedStreamObject()
    content.set_data(stream)
    page[NameObject("/Contents")] = writer._add_object(content)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_docx(text: str) -> bytes:
    """Build a small in-memory DOCX with one paragraph."""
    document = Document()
    document.add_paragraph(text)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def assert_spools_closed(spools: list[object]) -> None:
    """Check that every temporary in-memory spool was closed."""
    assert all(getattr(spool, "close_count", 0) == 1 for spool in spools)


def assert_no_disk_rollover(spools: list[object], max_size: int) -> None:
    """Check that uploaded file bytes stayed in memory."""
    assert spools
    assert all(getattr(spool, "_max_size", None) == max_size for spool in spools)
    assert all(getattr(spool, "_rolled", True) is False for spool in spools)


@pytest.fixture(autouse=True)
def isolated_upload_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every upload API test a fresh in-memory store."""
    monkeypatch.setattr(upload_store, "_uploads_by_id", {})
    monkeypatch.setattr(upload_store, "_current_upload_by_owner", {})


@pytest.fixture
def tracked_spools(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Record Starlette's spooled temporary files and their closes."""
    created: list[object] = []
    real_spooled_file = starlette_formparsers.SpooledTemporaryFile

    class TrackingSpooledTemporaryFile(real_spooled_file):
        def __init__(self, *args, **kwargs):
            self.close_count = 0
            self.bytes_written = 0
            super().__init__(*args, **kwargs)
            created.append(self)

        def write(self, data):
            self.bytes_written += len(data)
            return super().write(data)

        def close(self):
            self.close_count += 1
            return super().close()

    monkeypatch.setattr(
        starlette_formparsers,
        "SpooledTemporaryFile",
        TrackingSpooledTemporaryFile,
    )
    return created


@pytest.fixture
def uploads_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker]]:
    """Provide an authenticated-capable client backed by a fresh test database."""
    monkeypatch.setattr(token_service, "get_settings", lambda: TEST_TOKEN_SETTINGS)
    monkeypatch.setattr(uploads, "get_settings", lambda: upload_settings())

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


def test_limited_parser_closes_partial_file_when_limit_exceeded(
    tracked_spools: list[object],
) -> None:
    boundary = "BOUNDARY"
    headers = Headers(
        {"content-type": f"multipart/form-data; boundary={boundary}"}
    )
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="partial.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
    accepted_chunk = b"abc"
    oversized_chunk = b"defgh\r\n--BOUNDARY--\r\n"
    limit = 5

    async def body_chunks():
        yield prefix
        yield accepted_chunk
        yield oversized_chunk
        yield b""

    parser = LimitedMultipartParser(
        headers=headers,
        stream=body_chunks(),
        max_file_bytes=limit,
        spool_max_size=limit,
        max_files=1,
        max_fields=0,
        max_part_size=limit,
    )

    with pytest.raises(UploadTooLargeError) as error_info:
        asyncio.run(parser.parse())

    assert isinstance(error_info.value, MultiPartException)
    assert tracked_spools
    partial_file = tracked_spools[0]
    assert getattr(partial_file, "bytes_written", 0) > 0
    assert getattr(partial_file, "close_count", 0) == 1
    assert getattr(partial_file, "_rolled", True) is False


def test_unauthenticated_upload_is_rejected(uploads_client) -> None:
    client, _ = uploads_client

    response = client.post(
        "/uploads",
        files={"file": ("notes.txt", STUDY_TEXT.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 401


def test_authenticated_txt_upload_succeeds(uploads_client) -> None:
    client, _ = uploads_client
    user_id, headers = register_and_login(client, "txt-upload@example.com")

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("notes.txt", STUDY_TEXT.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "upload_id",
        "source_name",
        "file_type",
        "char_count",
        "preview",
    }
    assert data["upload_id"]
    assert data["source_name"] == "notes.txt"
    assert data["file_type"] == "txt"
    assert data["char_count"] == len(STUDY_TEXT)
    assert data["preview"] == STUDY_TEXT

    with upload_store._lock:
        stored = upload_store._uploads_by_id[data["upload_id"]]
    assert stored.owner_id == user_id
    assert stored.text == STUDY_TEXT


@pytest.mark.parametrize(
    "filename,file_bytes,file_type",
    [
        ("study.pdf", make_pdf(STUDY_TEXT), "pdf"),
        ("lesson.docx", make_docx(STUDY_TEXT), "docx"),
    ],
    ids=["pdf", "docx"],
)
def test_authenticated_pdf_and_docx_uploads_succeed(
    uploads_client,
    filename: str,
    file_bytes: bytes,
    file_type: str,
) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "document-upload@example.com")

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": (filename, file_bytes, "application/octet-stream")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["source_name"] == filename
    assert data["file_type"] == file_type
    assert STUDY_TEXT in data["preview"]


def test_upload_response_contains_only_an_800_character_preview(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "preview@example.com")
    text = "Study text." * 100

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("long.txt", text.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["char_count"] == len(text)
    assert data["preview"] == text[:800]
    assert len(data["preview"]) == 800


def test_file_larger_than_one_mib_succeeds_without_disk_rollover(
    uploads_client,
    tracked_spools: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "large-file@example.com")
    file_bytes = b"x" * (LARGE_LIMIT - 100)
    monkeypatch.setattr(
        uploads,
        "get_settings",
        lambda: upload_settings(
            max_upload_bytes=LARGE_LIMIT,
            max_upload_mb=1,
            max_source_chars=LARGE_LIMIT,
        ),
    )

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("large.txt", file_bytes, "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["char_count"] == len(file_bytes)
    assert_no_disk_rollover(tracked_spools, LARGE_LIMIT)
    assert_spools_closed(tracked_spools)


def test_file_exactly_at_limit_succeeds(
    uploads_client,
    tracked_spools: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "exact-limit@example.com")
    file_bytes = b"y" * LARGE_LIMIT
    monkeypatch.setattr(
        uploads,
        "get_settings",
        lambda: upload_settings(
            max_upload_bytes=LARGE_LIMIT,
            max_upload_mb=1,
            max_source_chars=LARGE_LIMIT,
        ),
    )

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("exact.txt", file_bytes, "text/plain")},
    )

    assert response.status_code == 200
    assert response.json()["char_count"] == LARGE_LIMIT
    assert_no_disk_rollover(tracked_spools, LARGE_LIMIT)
    assert_spools_closed(tracked_spools)


def test_file_one_byte_over_limit_returns_413(
    uploads_client,
    tracked_spools: list[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "over-limit@example.com")
    monkeypatch.setattr(
        uploads,
        "get_settings",
        lambda: upload_settings(
            max_upload_bytes=LARGE_LIMIT,
            max_upload_mb=1,
            max_source_chars=LARGE_LIMIT,
        ),
    )

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("over.txt", b"z" * (LARGE_LIMIT + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    with upload_store._lock:
        assert upload_store._uploads_by_id == {}
    assert_no_disk_rollover(tracked_spools, LARGE_LIMIT)
    assert_spools_closed(tracked_spools)


def test_unexpected_form_field_is_rejected(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "unexpected-field@example.com")

    response = client.post(
        "/uploads",
        headers=headers,
        data={"owner_id": "999"},
        files={"file": ("notes.txt", STUDY_TEXT.encode("utf-8"), "text/plain")},
    )

    assert response.status_code == 400
    with upload_store._lock:
        assert upload_store._uploads_by_id == {}


def test_additional_file_is_rejected(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "additional-file@example.com")

    response = client.post(
        "/uploads",
        headers=headers,
        files=[
            ("file", ("first.txt", STUDY_TEXT.encode("utf-8"), "text/plain")),
            ("extra", ("second.txt", b"More text.", "text/plain")),
        ],
    )

    assert response.status_code == 400
    with upload_store._lock:
        assert upload_store._uploads_by_id == {}


def test_malformed_multipart_data_is_rejected(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "malformed-multipart@example.com")
    headers = {**headers, "Content-Type": "multipart/form-data; boundary=BOUNDARY"}

    response = client.post(
        "/uploads",
        headers=headers,
        content=b"this is not valid multipart data",
    )

    assert response.status_code == 400
    with upload_store._lock:
        assert upload_store._uploads_by_id == {}


def test_unsupported_file_extension_is_rejected(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "unsupported@example.com")

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("notes.exe", b"content", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "Only PDF, DOCX, and TXT" in response.json()["detail"]


@pytest.mark.parametrize(
    "filename,file_bytes,expected_detail",
    [
        (
            "broken.pdf",
            b"%PDF-1.4\nnot a valid PDF\n%%EOF",
            "PDF file is malformed",
        ),
        ("empty.txt", b"  \n\t  ", "No readable text"),
        ("broken.docx", b"PK\x03\x04not a docx", "DOCX file is malformed"),
    ],
    ids=["malformed-pdf", "empty-txt", "malformed-docx"],
)
def test_malformed_or_empty_documents_return_clear_errors(
    uploads_client,
    filename: str,
    file_bytes: bytes,
    expected_detail: str,
) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "invalid-document@example.com")

    response = client.post(
        "/uploads",
        headers=headers,
        files={"file": (filename, file_bytes, "application/octet-stream")},
    )

    assert response.status_code == 400
    assert expected_detail in response.json()["detail"]


def test_failed_upload_does_not_replace_previous_success(
    uploads_client,
    tracked_spools: list[object],
) -> None:
    client, _ = uploads_client
    user_id, headers = register_and_login(client, "replace@example.com")
    first_text = "First successful upload."

    first = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("first.txt", first_text.encode("utf-8"), "text/plain")},
    )
    assert first.status_code == 200
    upload_id = first.json()["upload_id"]

    failed = client.post(
        "/uploads",
        headers=headers,
        files={
            "file": (
                "broken.pdf",
                b"%PDF-1.4\nnot a valid PDF\n%%EOF",
                "application/pdf",
            )
        },
    )
    assert failed.status_code == 400

    with upload_store._lock:
        assert list(upload_store._uploads_by_id) == [upload_id]
    stored = upload_store.get_owned_upload(upload_id, user_id)
    assert stored.text == first_text
    assert tracked_spools
    assert_spools_closed(tracked_spools)


def test_authenticated_user_can_retrieve_own_upload_preview(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "preview-owner@example.com")

    uploaded = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("notes.txt", STUDY_TEXT.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200
    upload_id = uploaded.json()["upload_id"]

    response = client.get(f"/uploads/{upload_id}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "upload_id",
        "source_name",
        "file_type",
        "char_count",
        "preview",
    }
    assert data == uploaded.json()
    assert data["upload_id"] == upload_id
    assert data["source_name"] == "notes.txt"
    assert data["file_type"] == "txt"
    assert data["char_count"] == len(STUDY_TEXT)
    assert data["preview"] == STUDY_TEXT


def test_upload_preview_requires_authentication(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "preview-auth@example.com")

    uploaded = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("notes.txt", STUDY_TEXT.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200

    response = client.get(f"/uploads/{uploaded.json()['upload_id']}")

    assert response.status_code == 401


def test_unknown_upload_id_returns_404(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "unknown-preview@example.com")

    response = client.get("/uploads/unknown-upload-id", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Upload not found."}


def test_wrong_owner_gets_same_404_as_unknown_upload(uploads_client) -> None:
    client, _ = uploads_client
    _, owner_headers = register_and_login(client, "preview-owner-a@example.com")
    _, other_headers = register_and_login(client, "preview-owner-b@example.com")

    uploaded = client.post(
        "/uploads",
        headers=owner_headers,
        files={"file": ("notes.txt", STUDY_TEXT.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200
    upload_id = uploaded.json()["upload_id"]

    unknown = client.get("/uploads/unknown-upload-id", headers=other_headers)
    wrong_owner = client.get(f"/uploads/{upload_id}", headers=other_headers)

    assert unknown.status_code == 404
    assert wrong_owner.status_code == 404
    assert wrong_owner.json() == unknown.json()
    assert wrong_owner.json() == {"detail": "Upload not found."}


def test_retrieved_preview_is_limited_to_800_characters(uploads_client) -> None:
    client, _ = uploads_client
    _, headers = register_and_login(client, "long-preview@example.com")
    text = "Study text." * 100

    uploaded = client.post(
        "/uploads",
        headers=headers,
        files={"file": ("long.txt", text.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 200

    response = client.get(f"/uploads/{uploaded.json()['upload_id']}", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["preview"] == text[:800]
    assert len(data["preview"]) == 800
    assert data["char_count"] == len(text)
