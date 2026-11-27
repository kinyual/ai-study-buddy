"""Tests for the owner-scoped in-memory upload store."""

import builtins
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend.app.services import upload_store as service
from backend.app.services.text_extraction_service import ExtractedMaterial


def make_material(
    text: str = "Photosynthesis converts light into chemical energy.",
    *,
    source_name: str = "notes.txt",
    file_type: str = "txt",
) -> ExtractedMaterial:
    """Build extracted material without relying on a real uploaded file."""
    return ExtractedMaterial(
        source_name=source_name,
        file_type=file_type,
        text=text,
        char_count=len(text),
    )


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test a fresh in-memory store."""
    monkeypatch.setattr(service, "_uploads_by_id", {})
    monkeypatch.setattr(service, "_current_upload_by_owner", {})


def test_owner_can_save_and_retrieve_upload() -> None:
    material = make_material()

    stored = service.save_upload(owner_id=7, material=material)
    retrieved = service.get_owned_upload(stored.upload_id, 7)

    assert retrieved == stored
    assert retrieved.owner_id == 7
    assert retrieved.source_name == "notes.txt"
    assert retrieved.file_type == "txt"
    assert retrieved.text == material.text
    assert retrieved.char_count == len(material.text)


def test_generated_ids_are_unique_and_non_empty() -> None:
    upload_ids = [
        service.save_upload(1, make_material(f"Study text {index}")).upload_id
        for index in range(5)
    ]

    assert all(upload_ids)
    assert len(set(upload_ids)) == len(upload_ids)
    assert all(len(upload_id) == 32 for upload_id in upload_ids)
    assert all(
        all(character in "0123456789abcdef" for character in upload_id)
        for upload_id in upload_ids
    )


def test_another_user_gets_the_same_not_found_error_as_an_unknown_id() -> None:
    stored = service.save_upload(1, make_material())

    with pytest.raises(service.UploadNotFoundError) as wrong_owner:
        service.get_owned_upload(stored.upload_id, 2)
    with pytest.raises(service.UploadNotFoundError) as unknown_id:
        service.get_owned_upload("does-not-exist", 2)

    assert type(wrong_owner.value) is type(unknown_id.value)
    assert str(wrong_owner.value) == str(unknown_id.value)


def test_new_upload_replaces_previous_upload_for_same_owner() -> None:
    first = service.save_upload(1, make_material("First study text."))
    second = service.save_upload(
        2,
        make_material("Another user's text.", source_name="other.txt"),
    )
    replacement = service.save_upload(1, make_material("Second study text."))

    assert replacement.upload_id != first.upload_id

    with pytest.raises(service.UploadNotFoundError):
        service.get_owned_upload(first.upload_id, 1)

    assert service.get_owned_upload(replacement.upload_id, 1) == replacement
    assert service.get_owned_upload(second.upload_id, 2) == second

    with service._lock:
        assert len(service._uploads_by_id) == 2


def test_different_users_uploads_remain_independent() -> None:
    first = service.save_upload(
        1,
        make_material("First user text.", source_name="first.txt"),
    )
    second = service.save_upload(
        2,
        make_material("Second user text.", source_name="second.txt", file_type="txt"),
    )

    assert first.upload_id != second.upload_id
    assert service.get_owned_upload(first.upload_id, 1) == first
    assert service.get_owned_upload(second.upload_id, 2) == second

    with pytest.raises(service.UploadNotFoundError):
        service.get_owned_upload(first.upload_id, 2)
    with pytest.raises(service.UploadNotFoundError):
        service.get_owned_upload(second.upload_id, 1)


def test_concurrent_access_keeps_one_current_upload_and_reads_are_safe() -> None:
    def save_upload(index: int) -> service.StoredUpload:
        return service.save_upload(42, make_material(f"Concurrent text {index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        saved_uploads = list(pool.map(save_upload, range(20)))

    with service._lock:
        current_id = service._current_upload_by_owner[42]
        stored_ids = list(service._uploads_by_id)

    assert len(stored_ids) == 1
    assert stored_ids[0] == current_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        reads = list(
            pool.map(
                lambda _: service.get_owned_upload(current_id, 42),
                range(20),
            )
        )

    assert all(upload.upload_id == current_id for upload in reads)

    for upload in saved_uploads:
        if upload.upload_id != current_id:
            with pytest.raises(service.UploadNotFoundError):
                service.get_owned_upload(upload.upload_id, 42)


def test_store_does_not_write_uploads_to_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = builtins.open
    real_os_open = os.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"Unexpected write to {file!r}")
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
        if flags & write_flags:
            raise AssertionError(f"Unexpected os.open write to {path!r}")
        return real_os_open(path, flags, *args, **kwargs)

    def forbidden_file_operation(*args, **kwargs):
        raise AssertionError("Store tried to create a file on disk")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", guarded_open)
        patch.setattr(os, "open", guarded_os_open)
        patch.setattr(tempfile, "NamedTemporaryFile", forbidden_file_operation)
        patch.setattr(tempfile, "TemporaryFile", forbidden_file_operation)
        patch.setattr(tempfile, "mkstemp", forbidden_file_operation)
        patch.setattr(Path, "write_text", forbidden_file_operation)
        patch.setattr(Path, "write_bytes", forbidden_file_operation)

        stored = service.save_upload(1, make_material())
        retrieved = service.get_owned_upload(stored.upload_id, 1)

    assert retrieved == stored
