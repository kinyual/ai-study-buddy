"""Tests for safe in-memory study-material text extraction."""

import builtins
import os
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.app.services import text_extraction_service as service

SOURCE_SENTENCE = "Photosynthesis converts light into chemical energy."


def settings(*, max_source_chars: int = 30_000) -> SimpleNamespace:
    """Return test settings with no dependency on a real .env file."""
    return SimpleNamespace(max_source_chars=max_source_chars)


def make_pdf(text: str, *, password: str | None = None) -> bytes:
    """Build a small in-memory PDF with selectable text."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 18 Tf 72 700 Td ({escaped}) Tj ET"

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    content = DecodedStreamObject()
    content.set_data(stream.encode("utf-8"))
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

    if password is not None:
        writer.encrypt(password)

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    """Build a small in-memory DOCX with the supplied paragraphs."""
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_zip_without_document_xml() -> bytes:
    """Build a ZIP file that looks like a DOCX but is missing its main part."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "This is not a Word document.")
    return buffer.getvalue()


def make_zip_with_document_xml() -> bytes:
    """Build the smallest ZIP that passes the DOCX signature/part checks."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def make_docx_with_replaced_part(part_name: str, replacement: bytes) -> bytes:
    """Replace one part of a valid DOCX to simulate parser-level corruption."""
    source = BytesIO(make_docx(["Original text."]))
    buffer = BytesIO()

    with ZipFile(source, "r") as original, ZipFile(buffer, "w") as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == part_name:
                data = replacement
            output.writestr(item, data)

    return buffer.getvalue()


def test_txt_extraction_returns_source_text() -> None:
    result = service.extract_material_text(
        "notes.txt",
        SOURCE_SENTENCE.encode("utf-8"),
        settings(),
    )

    assert result.source_name == "notes.txt"
    assert result.file_type == "txt"
    assert result.text == SOURCE_SENTENCE
    assert result.char_count == len(SOURCE_SENTENCE)


def test_txt_with_utf8_bom_is_accepted() -> None:
    data = b"\xef\xbb\xbf" + SOURCE_SENTENCE.encode("utf-8")

    result = service.extract_material_text("notes.txt", data, settings())

    assert result.text == SOURCE_SENTENCE


def test_invalid_utf8_txt_is_rejected() -> None:
    with pytest.raises(service.MaterialExtractionError, match="UTF-8"):
        service.extract_material_text("notes.txt", b"Invalid byte: \xff", settings())


def test_txt_with_null_byte_is_rejected() -> None:
    with pytest.raises(service.MaterialExtractionError, match="UTF-8"):
        service.extract_material_text("notes.txt", b"Text\x00with null", settings())


@pytest.mark.parametrize("data", [b"", b"  \t\n\r  "])
def test_empty_txt_is_rejected(data: bytes) -> None:
    with pytest.raises(service.MaterialExtractionError, match="No readable text"):
        service.extract_material_text("notes.txt", data, settings())


@pytest.mark.parametrize(
    "filename",
    ["notes.exe", "notes.doc", "notes", r"..\uploads\notes.png"],
)
def test_unsupported_extensions_are_rejected(filename: str) -> None:
    with pytest.raises(service.MaterialExtractionError, match="Only PDF"):
        service.extract_material_text(filename, b"content", settings())


def test_valid_pdf_text_is_extracted() -> None:
    result = service.extract_material_text(
        "study.PDF",
        make_pdf(SOURCE_SENTENCE),
        settings(),
    )

    assert result.source_name == "study.PDF"
    assert result.file_type == "pdf"
    assert SOURCE_SENTENCE in result.text


def test_scanned_or_empty_pdf_is_rejected() -> None:
    with pytest.raises(service.MaterialExtractionError, match="scanned images"):
        service.extract_material_text("scan.pdf", make_pdf(""), settings())


@pytest.mark.parametrize(
    "data",
    [
        b"not a pdf",
        b"%PDF-1.4\nthis is not a valid PDF\n%%EOF",
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog",
    ],
)
def test_malformed_pdf_is_rejected(data: bytes) -> None:
    with pytest.raises(service.MaterialExtractionError, match="PDF file is malformed"):
        service.extract_material_text("broken.pdf", data, settings())


def test_encrypted_pdf_is_rejected() -> None:
    with pytest.raises(service.MaterialExtractionError, match="password-protected"):
        service.extract_material_text(
            "locked.pdf",
            make_pdf(SOURCE_SENTENCE, password="secret"),
            settings(),
        )


def test_oversized_pdf_is_rejected_without_returning_partial_text() -> None:
    full_text = SOURCE_SENTENCE * 3

    with pytest.raises(service.MaterialExtractionError, match="too much text") as info:
        service.extract_material_text(
            "big.pdf",
            make_pdf(full_text),
            settings(max_source_chars=len(SOURCE_SENTENCE)),
        )

    assert full_text not in str(info.value)


def test_pdf_extraction_stops_collecting_at_the_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def __init__(self, text: str, *, explode: bool = False) -> None:
            self.text = text
            self.explode = explode

        def extract_text(self) -> str:
            if self.explode:
                raise AssertionError("Extraction continued after the limit")
            return self.text

    class FakeReader:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        @property
        def is_encrypted(self) -> bool:
            return False

        @property
        def pages(self) -> list[FakePage]:
            return [FakePage("x" * 11), FakePage("", explode=True)]

    monkeypatch.setattr(service, "PdfReader", FakeReader)

    with pytest.raises(service.MaterialExtractionError, match="too much text"):
        service.extract_material_text(
            "big.pdf",
            b"%PDF-1.4\nignored by the fake reader",
            settings(max_source_chars=10),
        )


def test_valid_docx_text_is_extracted() -> None:
    second_sentence = "Plants release oxygen during photosynthesis."

    result = service.extract_material_text(
        "lesson.docx",
        make_docx([SOURCE_SENTENCE, second_sentence]),
        settings(),
    )

    assert result.file_type == "docx"
    assert SOURCE_SENTENCE in result.text
    assert second_sentence in result.text


def test_docx_table_text_is_extracted() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Chlorophyll"
    table.cell(0, 1).text = "absorbs sunlight"
    buffer = BytesIO()
    document.save(buffer)

    result = service.extract_material_text("table.docx", buffer.getvalue(), settings())

    assert "Chlorophyll" in result.text
    assert "absorbs sunlight" in result.text


@pytest.mark.parametrize(
    "data",
    [
        b"not a docx",
        b"PK\x03\x04not a valid docx",
        make_zip_without_document_xml(),
        make_docx_with_replaced_part("word/document.xml", b"<w:document><unclosed>"),
        make_docx_with_replaced_part("[Content_Types].xml", b"<Types/>"),
    ],
    ids=[
        "not-a-zip",
        "bad-signature",
        "missing-document-xml",
        "corrupt-document-xml",
        "empty-content-types",
    ],
)
def test_malformed_docx_is_rejected(data: bytes) -> None:
    with pytest.raises(service.MaterialExtractionError, match="DOCX file is malformed"):
        service.extract_material_text("broken.docx", data, settings())


def test_oversized_docx_is_rejected_without_returning_partial_text() -> None:
    full_text = SOURCE_SENTENCE * 3

    with pytest.raises(service.MaterialExtractionError, match="too much text") as info:
        service.extract_material_text(
            "big.docx",
            make_docx([full_text]),
            settings(max_source_chars=len(SOURCE_SENTENCE)),
        )

    assert full_text not in str(info.value)


def test_docx_extraction_stops_collecting_at_the_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingParagraph:
        @property
        def text(self) -> str:
            raise AssertionError("Extraction continued after the limit")

    fake_document = SimpleNamespace(
        paragraphs=[SimpleNamespace(text="x" * 11), ExplodingParagraph()],
        tables=[],
    )
    monkeypatch.setattr(service, "Document", lambda stream: fake_document)

    with pytest.raises(service.MaterialExtractionError, match="too much text"):
        service.extract_material_text(
            "big.docx",
            make_zip_with_document_xml(),
            settings(max_source_chars=10),
        )


def test_extracted_txt_over_limit_is_rejected_without_truncation() -> None:
    full_text = "x" * 11

    with pytest.raises(service.MaterialExtractionError, match="too much text") as info:
        service.extract_material_text(
            "long.txt",
            full_text.encode("utf-8"),
            settings(max_source_chars=10),
        )

    assert full_text not in str(info.value)


@pytest.mark.parametrize(
    "filename,data",
    [
        ("notes.txt", SOURCE_SENTENCE.encode("utf-8")),
        ("study.pdf", make_pdf(SOURCE_SENTENCE)),
        ("lesson.docx", make_docx([SOURCE_SENTENCE])),
    ],
    ids=["txt", "pdf", "docx"],
)
def test_extraction_does_not_write_files_to_disk(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    data: bytes,
) -> None:
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
        raise AssertionError("Extraction tried to create a file on disk")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", guarded_open)
        patch.setattr(os, "open", guarded_os_open)
        patch.setattr(tempfile, "NamedTemporaryFile", forbidden_file_operation)
        patch.setattr(tempfile, "TemporaryFile", forbidden_file_operation)
        patch.setattr(tempfile, "mkstemp", forbidden_file_operation)
        patch.setattr(Path, "write_text", forbidden_file_operation)
        patch.setattr(Path, "write_bytes", forbidden_file_operation)

        result = service.extract_material_text(filename, data, settings())

    assert SOURCE_SENTENCE in result.text
