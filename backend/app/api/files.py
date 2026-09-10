"""Local file upload endpoint — content-sniffed MIME validation, no execution."""
from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
import magic
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.models.db_models import UploadedFile

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Extensions we accept, and the MIME we record for each. Content sniffing decides
# what the file *is*; the extension only disambiguates text-ish formats that
# libmagic reports generically (a .py file sniffs as text/plain).
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".json": "application/json",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# MIMEs libmagic may legitimately report for the above.
SNIFFED_MIME_WHITELIST = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "image/webp",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/zip",  # OOXML containers sniff as zip on some libmagic builds
    "text/csv",
    "text/plain",
    "text/x-python",
    "text/x-script.python",
    "text/javascript",
    "application/javascript",
    "application/json",
    "application/csv",
    "inode/x-empty",
}


class FileUploadResponse(BaseModel):
    file_id: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str


@router.post("", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile, db: AsyncSession = Depends(get_db)
) -> FileUploadResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    original_name = file.filename or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file extension '{ext}'. Allowed: "
                   f"{', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    sniffed = magic.from_buffer(content, mime=True)
    if sniffed not in SNIFFED_MIME_WHITELIST:
        raise HTTPException(
            status_code=415,
            detail=f"File content is not an accepted type (detected: {sniffed})",
        )

    # Trust the sniffed type when it is specific; fall back to the extension map
    # for the text-ish formats libmagic reports generically.
    generic = {"text/plain", "application/zip", "application/octet-stream", "inode/x-empty"}
    mime_type = ALLOWED_EXTENSIONS[ext] if sniffed in generic else sniffed

    sha256 = hashlib.sha256(content).hexdigest()
    upload_dir = Path(settings.uploads_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / f"{sha256}{ext}"

    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    record = UploadedFile(
        original_filename=original_name,
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=sha256,
        local_path=str(dest),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return FileUploadResponse(
        file_id=record.id,
        original_filename=record.original_filename,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
    )
