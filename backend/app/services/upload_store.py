"""Owner-scoped in-memory storage for recently uploaded study material.

The prototype stores only extracted text and metadata. Nothing is written to
disk or SQLite, and all uploads disappear when the backend process restarts.
"""

import threading
import uuid
from dataclasses import dataclass

from .text_extraction_service import ExtractedMaterial

_NOT_FOUND_MESSAGE = "Upload not found."


class UploadNotFoundError(LookupError):
    """Raised when an upload is unknown or belongs to another user."""


@dataclass(frozen=True)
class StoredUpload:
    """One extracted upload held temporarily in backend memory."""

    upload_id: str
    owner_id: int
    source_name: str
    file_type: str
    text: str
    char_count: int


_uploads_by_id: dict[str, StoredUpload] = {}
_current_upload_by_owner: dict[int, str] = {}
_lock = threading.Lock()


def save_upload(owner_id: int, material: ExtractedMaterial) -> StoredUpload:
    """Store one upload for an owner, replacing that owner's previous upload."""
    upload_id = uuid.uuid4().hex
    stored = StoredUpload(
        upload_id=upload_id,
        owner_id=owner_id,
        source_name=material.source_name,
        file_type=material.file_type,
        text=material.text,
        char_count=material.char_count,
    )

    with _lock:
        previous_id = _current_upload_by_owner.get(owner_id)
        if previous_id is not None:
            _uploads_by_id.pop(previous_id, None)

        _uploads_by_id[upload_id] = stored
        _current_upload_by_owner[owner_id] = upload_id

    return stored


def get_owned_upload(upload_id: str, owner_id: int) -> StoredUpload:
    """Return an upload only if it belongs to the given owner."""
    with _lock:
        stored = _uploads_by_id.get(upload_id)
        if stored is None or stored.owner_id != owner_id:
            raise UploadNotFoundError(_NOT_FOUND_MESSAGE)
        return stored
