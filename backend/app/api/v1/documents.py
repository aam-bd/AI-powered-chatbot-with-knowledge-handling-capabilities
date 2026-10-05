"""Admin Document lifecycle API endpoints: upload, update, list, status, and two-phase delete."""
import hashlib
import json
import os
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    File,
    Query,
    status,
)
from fastapi.responses import JSONResponse
from qdrant_client.http import models as qmodels
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.core.security import require_admin
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.db.session import get_db
from app.models.schemas import (
    DocumentResponse,
    DocumentStatusResponse,
    DocumentAcceptedResponse,
    DocumentUrlCreateRequest,
    ErrorResponse,
)
from app.models.sql_models import Document, User
from app.services.parsers.web import validate_ssrf_url
from app.workers.tasks_ingestion import ingest_document_task
from app.workers.tasks_deletion import delete_document_task

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "docx", "md", "txt"}
UPLOAD_DIR = os.path.abspath(os.getenv("UPLOAD_DIR", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


def validate_file_content(content: bytes, ext: str, max_bytes: int):
    """Validate file size and magic bytes."""
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_MB}MB.",
        )

    if ext == "pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid PDF file format (magic bytes mismatch).",
            )
    elif ext == "docx":
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid DOCX file format (magic bytes mismatch).",
            )
    elif ext in ("md", "txt"):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Text document must be valid UTF-8.",
            )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentAcceptedResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file format or validation error"},
        409: {"description": "Duplicate document content"},
        413: {"model": ErrorResponse, "description": "File too large"},
    },
)
async def upload_document(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only document upload endpoint supporting multipart file or JSON web URL."""
    content_type = request.headers.get("content-type", "")
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    if "application/json" in content_type:
        try:
            body = await request.json()
            url_req = DocumentUrlCreateRequest(**body)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON body: {exc}",
            )

        # Validate URL for SSRF protection
        validate_ssrf_url(url_req.url, settings.ALLOWED_URL_DOMAINS)

        # Compute deterministic SHA256 of normalized URL
        url_hash = hashlib.sha256(url_req.url.strip().encode("utf-8")).hexdigest()

        # Duplicate check against non-deleted documents
        existing = await db.execute(
            select(Document).where(
                Document.sha256 == url_hash,
                Document.status != "deleting",
            )
        )
        existing_doc = existing.scalar_one_or_none()
        if existing_doc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "A document with identical content already exists.",
                    "code": "DUPLICATE_DOCUMENT",
                    "existing_document_id": str(existing_doc.id),
                },
            )

        doc = Document(
            id=uuid.uuid4(),
            name=url_req.name or url_req.url,
            source_type="url",
            source_uri=url_req.url,
            sha256=url_hash,
            size_bytes=len(url_req.url.encode("utf-8")),
            status="pending",
            active_version=None,
            pending_version=1,
            created_by=admin.id,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        task = ingest_document_task.delay(str(doc.id), version=1)

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "document_id": str(doc.id),
                "task_id": task.id if task else None,
                "status": "accepted",
                "message": "URL ingestion initiated.",
            },
        )

    elif "multipart/form-data" in content_type:
        form = await request.form()
        file_obj = form.get("file")
        if not file_obj or not hasattr(file_obj, "filename"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Form field 'file' is required.",
            )

        filename = file_obj.filename or "uploaded_file"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file extension '{ext}'. Allowed: {sorted(list(ALLOWED_EXTENSIONS))}",
            )

        content = await file_obj.read()
        validate_file_content(content, ext, max_bytes)

        file_hash = hashlib.sha256(content).hexdigest()

        # Duplicate check against non-deleted documents
        existing = await db.execute(
            select(Document).where(
                Document.sha256 == file_hash,
                Document.status != "deleting",
            )
        )
        existing_doc = existing.scalar_one_or_none()
        if existing_doc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": "A document with identical content already exists.",
                    "code": "DUPLICATE_DOCUMENT",
                    "existing_document_id": str(existing_doc.id),
                },
            )

        doc_id = uuid.uuid4()
        storage_path = os.path.join(UPLOAD_DIR, f"{doc_id}.{ext}")
        with open(storage_path, "wb") as f:
            f.write(content)

        doc = Document(
            id=doc_id,
            name=filename,
            source_type=ext,
            source_uri=storage_path,
            sha256=file_hash,
            size_bytes=len(content),
            status="pending",
            active_version=None,
            pending_version=1,
            created_by=admin.id,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        task = ingest_document_task.delay(str(doc.id), version=1)

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "document_id": str(doc.id),
                "task_id": task.id if task else None,
                "status": "accepted",
                "message": "File upload accepted for ingestion.",
            },
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type must be 'multipart/form-data' or 'application/json'.",
        )


@router.put(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentAcceptedResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file format or validation error"},
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def update_document(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only endpoint to update an existing document, creating a new pending version."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.status != "deleting")
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    filename = file.filename or doc.name
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Allowed: {sorted(list(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    validate_file_content(content, ext, max_bytes)

    file_hash = hashlib.sha256(content).hexdigest()

    # Check duplicate against other documents
    existing = await db.execute(
        select(Document).where(
            Document.sha256 == file_hash,
            Document.id != doc.id,
            Document.status != "deleting",
        )
    )
    if existing.scalar_one_or_none():
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "A different document with identical content already exists.",
                "code": "DUPLICATE_DOCUMENT",
            },
        )

    new_version = (doc.active_version or 0) + 1
    new_storage_path = os.path.join(UPLOAD_DIR, f"{doc.id}_v{new_version}.{ext}")
    with open(new_storage_path, "wb") as f:
        f.write(content)

    doc.name = filename
    doc.source_type = ext
    doc.source_uri = new_storage_path
    doc.sha256 = file_hash
    doc.size_bytes = len(content)
    doc.pending_version = new_version
    doc.status = "updating"
    await db.commit()

    task = ingest_document_task.delay(str(doc.id), version=new_version)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "document_id": str(doc.id),
            "task_id": task.id if task else None,
            "status": "accepted",
            "message": f"Document update accepted for version {new_version}.",
        },
    )


@router.get(
    "",
    response_model=List[DocumentResponse],
)
async def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only list of documents."""
    query = select(Document).where(Document.status != "deleting")
    if status_filter:
        query = query.where(Document.status == status_filter)
    query = query.offset(skip).limit(limit).order_by(Document.created_at.desc())

    result = await db.execute(query)
    docs = result.scalars().all()
    return list(docs)


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def get_document_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only endpoint to check document status and active/pending versions."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return doc


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DocumentAcceptedResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Document not found"},
    },
)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin-only two-phase delete endpoint.
    
    Phase 1: Instantly marks document status='deleting' and flips Qdrant is_active=False
    so it disappears immediately from query results.
    Phase 2: Dispatches background deletion task to purge Qdrant points and disk file.
    """
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.status != "deleting")
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or already deleting.",
        )

    # Phase 1: Mark status='deleting' in DB
    doc.status = "deleting"
    await db.commit()

    # Phase 1: Instant search hide in Qdrant
    try:
        qc = get_qdrant_client()
        qc.set_payload(
            collection_name=COLLECTION_NAME,
            payload={"is_active": False},
            points=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=str(doc.id)),
                        )
                    ]
                )
            ),
        )
        logger.info(f"Phase 1: Instantly hid document {doc.id} from Qdrant search results.")
    except Exception as q_err:
        logger.warning(f"Could not immediately hide document {doc.id} in Qdrant: {q_err}")

    # Phase 2: Dispatch async purge task
    task = delete_document_task.delay(str(doc.id))

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "document_id": str(doc.id),
            "task_id": task.id if task else None,
            "status": "accepted",
            "message": "Document deletion initiated.",
        },
    )
