"""Bounded in-memory multipart parsing for uploaded study material.

FastAPI's automatic ``UploadFile`` parsing uses Starlette's default 1 MiB spool
threshold. This module keeps accepted uploads in memory and rejects oversized
file parts while they are being parsed, before excess bytes are written.
"""

from collections.abc import AsyncGenerator

from starlette.datastructures import FormData, Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request

from ..config import Settings

_FILE_FIELD_NAME = "file"
_WRONG_CONTENT_TYPE_MESSAGE = "Expected a multipart/form-data upload."
_UNEXPECTED_FORM_DATA_MESSAGE = "Upload exactly one file in the 'file' field."
_TOO_LARGE_MESSAGE = "Uploaded file exceeds the maximum allowed size."


class UploadMultipartError(MultiPartException):
    """Raised when a multipart upload does not match the expected shape."""


class UploadTooLargeError(UploadMultipartError):
    """Raised when a file part exceeds the configured byte limit."""


class LimitedMultipartParser(MultiPartParser):
    """Starlette multipart parser with an in-memory per-file byte limit."""

    def __init__(
        self,
        headers: Headers,
        stream: AsyncGenerator[bytes, None],
        *,
        max_file_bytes: int,
        spool_max_size: int,
        max_files: int = 1,
        max_fields: int = 0,
        max_part_size: int = 1024 * 1024,
    ) -> None:
        super().__init__(
            headers,
            stream,
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=max_part_size,
        )
        self.max_file_bytes = max_file_bytes
        self.spool_max_size = spool_max_size
        self._current_file_bytes = 0

    def on_part_begin(self) -> None:
        """Reset the per-file byte counter for each new part."""
        super().on_part_begin()
        self._current_file_bytes = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        """Reject excess file bytes before Starlette queues them for writing."""
        if self._current_part.file is not None:
            incoming_bytes = end - start
            if self._current_file_bytes + incoming_bytes > self.max_file_bytes:
                raise UploadTooLargeError(_TOO_LARGE_MESSAGE)
            self._current_file_bytes += incoming_bytes

        super().on_part_data(data, start, end)


async def parse_single_upload(
    request: Request,
    settings: Settings,
) -> tuple[FormData, UploadFile]:
    """Parse exactly one in-memory file from a bounded multipart request."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise UploadMultipartError(_WRONG_CONTENT_TYPE_MESSAGE)

    parser = LimitedMultipartParser(
        headers=request.headers,
        stream=request.stream(),
        max_file_bytes=settings.max_upload_bytes,
        spool_max_size=settings.max_upload_bytes,
        max_files=1,
        max_fields=0,
        max_part_size=settings.max_upload_bytes,
    )
    form = await parser.parse()

    try:
        items = form.multi_items()
        if len(items) != 1:
            raise UploadMultipartError(_UNEXPECTED_FORM_DATA_MESSAGE)

        field_name, value = items[0]
        if field_name != _FILE_FIELD_NAME or not isinstance(value, UploadFile):
            raise UploadMultipartError(_UNEXPECTED_FORM_DATA_MESSAGE)
    except BaseException:
        await form.close()
        raise

    return form, value
