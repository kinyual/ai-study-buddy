"""Safe text extraction for uploaded study material.

Uploaded bytes are parsed in memory only. They are treated as untrusted data,
never executed, and never written to disk. The extracted text keeps its line
structure so it remains suitable for the Gemini source-snippet grounding check.
"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import OpcError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ..config import Settings

_UNSUPPORTED_EXTENSION_MESSAGE = "Only PDF, DOCX, and TXT files are supported."
_INVALID_PDF_MESSAGE = "This PDF file is malformed or unreadable. Please upload another copy."
_INVALID_DOCX_MESSAGE = (
    "This DOCX file is malformed or unreadable. Please upload another copy."
)
_ENCRYPTED_PDF_MESSAGE = (
    "This PDF is password-protected. Please upload a version without a password."
)
_INVALID_TXT_MESSAGE = (
    "This text file must use UTF-8 encoding. Please save it as UTF-8 and try again."
)
_EMPTY_MESSAGE = "No readable text was found in this file."
_SCANNED_PDF_MESSAGE = (
    "This PDF appears to contain scanned images only. "
    "Please upload a PDF with selectable text."
)
_TOO_LARGE_MESSAGE = "This document contains too much text. Please use a shorter document."

_SUPPORTED_FILE_TYPES = {".txt": "txt", ".pdf": "pdf", ".docx": "docx"}
_PDF_SIGNATURE = b"%PDF-"
_ZIP_SIGNATURE = b"PK\x03\x04"

# pypdf reports parser failures through PyPdfError. ValueError and KeyError can
# also escape when a malformed file references missing objects.
_PDF_ERRORS = (PyPdfError, ValueError, KeyError)

# python-docx can surface OPC, ZIP, missing-part, and XML parsing failures.
# XMLSyntaxError is a SyntaxError subclass, so SyntaxError covers it without
# importing lxml directly.
_DOCX_ERRORS = (
    OpcError,
    BadZipFile,
    KeyError,
    AttributeError,
    SyntaxError,
    ValueError,
)


class MaterialExtractionError(ValueError):
    """Raised when an uploaded file cannot be safely turned into study text."""


@dataclass(frozen=True)
class ExtractedMaterial:
    """Validated text and metadata extracted from one uploaded document."""

    source_name: str
    file_type: str
    text: str
    char_count: int


def extract_material_text(
    filename: str,
    data: bytes,
    settings: Settings,
) -> ExtractedMaterial:
    """Extract validated text from uploaded bytes without writing to disk."""
    source_name = _safe_source_name(filename)
    file_type = _file_type_for(source_name)
    raw_text = _extract_by_type(file_type, data, settings.max_source_chars)
    cleaned_text = _clean_text(raw_text)

    if not cleaned_text:
        if file_type == "pdf":
            raise MaterialExtractionError(_SCANNED_PDF_MESSAGE)
        raise MaterialExtractionError(_EMPTY_MESSAGE)

    if len(cleaned_text) > settings.max_source_chars:
        raise MaterialExtractionError(_TOO_LARGE_MESSAGE)

    return ExtractedMaterial(
        source_name=source_name,
        file_type=file_type,
        text=cleaned_text,
        char_count=len(cleaned_text),
    )


def _safe_source_name(filename: str) -> str:
    """Return a plain file name without any supplied path components."""
    if not isinstance(filename, str):
        raise MaterialExtractionError(_UNSUPPORTED_EXTENSION_MESSAGE)

    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        raise MaterialExtractionError(_UNSUPPORTED_EXTENSION_MESSAGE)
    return name


def _file_type_for(source_name: str) -> str:
    """Map a supported file extension to a simple file-type name."""
    suffix = Path(source_name).suffix.lower()
    file_type = _SUPPORTED_FILE_TYPES.get(suffix)
    if file_type is None:
        raise MaterialExtractionError(_UNSUPPORTED_EXTENSION_MESSAGE)
    return file_type


def _extract_by_type(file_type: str, data: bytes, max_chars: int) -> str:
    """Validate the basic signature, then extract text for one file type."""
    if not isinstance(data, (bytes, bytearray)):
        raise MaterialExtractionError("The uploaded file could not be read.")

    payload = bytes(data)

    if file_type == "txt":
        return _extract_txt(payload)

    if file_type == "pdf":
        if payload.lstrip()[:5] != _PDF_SIGNATURE:
            raise MaterialExtractionError(_INVALID_PDF_MESSAGE)
        return _extract_pdf(payload, max_chars)

    if payload[:4] != _ZIP_SIGNATURE:
        raise MaterialExtractionError(_INVALID_DOCX_MESSAGE)
    return _extract_docx(payload, max_chars)


def _extract_txt(data: bytes) -> str:
    """Decode UTF-8 text, accepting an optional UTF-8 byte-order mark."""
    if b"\x00" in data:
        raise MaterialExtractionError(_INVALID_TXT_MESSAGE)

    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MaterialExtractionError(_INVALID_TXT_MESSAGE) from exc


def _add_text_part(
    parts: list[str],
    total_chars: int,
    text: str,
    max_chars: int,
) -> int:
    """Add one parsed text chunk, failing before any silent truncation."""
    if not text:
        return total_chars

    added_chars = len(text) + (1 if parts else 0)
    if total_chars + added_chars > max_chars:
        raise MaterialExtractionError(_TOO_LARGE_MESSAGE)

    parts.append(text)
    return total_chars + added_chars


def _extract_pdf(data: bytes, max_chars: int) -> str:
    """Extract selectable text from a PDF, stopping as soon as it is too large."""
    parts: list[str] = []
    total_chars = 0

    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise MaterialExtractionError(_ENCRYPTED_PDF_MESSAGE)

        for page in reader.pages:
            page_text = page.extract_text() or ""
            total_chars = _add_text_part(parts, total_chars, page_text, max_chars)
    except MaterialExtractionError:
        raise
    except _PDF_ERRORS as exc:
        raise MaterialExtractionError(_INVALID_PDF_MESSAGE) from exc

    return "\n".join(parts)


def _extract_docx(data: bytes, max_chars: int) -> str:
    """Extract DOCX text incrementally, stopping as soon as it is too large."""
    parts: list[str] = []
    total_chars = 0

    try:
        with ZipFile(BytesIO(data)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise MaterialExtractionError(_INVALID_DOCX_MESSAGE)

        document = Document(BytesIO(data))

        for paragraph in document.paragraphs:
            total_chars = _add_text_part(
                parts, total_chars, paragraph.text, max_chars
            )

        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    total_chars = _add_text_part(
                        parts, total_chars, cell.text, max_chars
                    )
    except MaterialExtractionError:
        raise
    except _DOCX_ERRORS as exc:
        raise MaterialExtractionError(_INVALID_DOCX_MESSAGE) from exc

    return "\n".join(parts)


def _clean_text(text: str) -> str:
    """Normalise line endings while preserving source wording and spacing."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalised.split("\n")]
    return "\n".join(lines).strip()
