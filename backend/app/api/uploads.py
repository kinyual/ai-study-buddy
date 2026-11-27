"""Authenticated endpoint for uploading temporary study material."""

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.formparsers import MultiPartException
from starlette.requests import Request

from ..config import get_settings
from ..models import User
from ..schemas import UPLOAD_PREVIEW_CHARS, UploadPreviewResponse, UploadResponse
from ..services.text_extraction_service import (
    MaterialExtractionError,
    extract_material_text,
)
from ..services.upload_store import UploadNotFoundError, get_owned_upload, save_upload
from .deps import get_current_user
from .upload_parser import (
    UploadMultipartError,
    UploadTooLargeError,
    parse_single_upload,
)

router = APIRouter(tags=["uploads"])


@router.post("/uploads", response_model=UploadResponse)
async def upload_study_material(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> UploadResponse:
    """Validate, extract, and temporarily store one uploaded document."""
    settings = get_settings()
    form = None

    try:
        form, upload = await parse_single_upload(request, settings)
        data = await upload.read()
        material = extract_material_text(upload.filename or "", data, settings)
        stored = save_upload(current_user.id, material)
    except UploadTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "Uploaded file is too large. "
                f"Maximum size is {settings.max_upload_mb} MB."
            ),
        ) from None
    except (UploadMultipartError, MultiPartException) as exc:
        detail = exc.message if isinstance(exc, MultiPartException) else str(exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from None
    except MaterialExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    finally:
        if form is not None:
            await form.close()

    return UploadResponse(
        upload_id=stored.upload_id,
        source_name=stored.source_name,
        file_type=stored.file_type,
        char_count=stored.char_count,
        preview=stored.text[:UPLOAD_PREVIEW_CHARS],
    )


@router.get("/uploads/{upload_id}", response_model=UploadPreviewResponse)
async def get_upload_preview(
    upload_id: str,
    current_user: User = Depends(get_current_user),
) -> UploadPreviewResponse:
    """Return metadata and a short preview of one owned upload."""
    try:
        stored = get_owned_upload(upload_id, current_user.id)
    except UploadNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found.",
        ) from None

    return UploadPreviewResponse(
        upload_id=stored.upload_id,
        source_name=stored.source_name,
        file_type=stored.file_type,
        char_count=stored.char_count,
        preview=stored.text[:UPLOAD_PREVIEW_CHARS],
    )
