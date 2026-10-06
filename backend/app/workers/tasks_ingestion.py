"""Celery task for document ingestion and blue-green updates."""
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from qdrant_client.http import models as qmodels
from sqlalchemy import select

from app.core.logger import logger
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.db.session import AsyncSessionLocal
from app.models.sql_models import Document
from app.services.chunker import chunk_document
from app.services.embedding.factory import get_embedding_service
from app.services.parsers.docx import parse_docx
from app.services.parsers.markdown import parse_markdown
from app.services.parsers.pdf import parse_pdf
from app.services.parsers.text import parse_text
from app.services.parsers.web import parse_web_url
from app.workers.celery_app import celery_app


def parse_source(source_type: str, source_uri: str) -> list:
    """Parse document according to source_type."""
    if source_type == "url":
        return parse_web_url(source_uri)
    elif source_type == "pdf":
        return parse_pdf(source_uri)
    elif source_type == "docx":
        return parse_docx(source_uri)
    elif source_type == "md":
        return parse_markdown(source_uri)
    elif source_type == "txt":
        return parse_text(source_uri)
    else:
        raise ValueError(f"Unsupported source type: {source_type}")


async def _async_ingest_document(document_id: str, version: Optional[int] = None):
    """Core async logic for document ingestion and blue-green updates."""
    qc = get_qdrant_client()
    embedding_service = get_embedding_service()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.id == uuid.UUID(document_id))
        )
        doc = result.scalar_one_or_none()

        if not doc:
            logger.error(f"Document {document_id} not found in database.")
            return

        if doc.status == "deleting":
            logger.info(f"Document {document_id} is marked for deletion. Aborting ingest.")
            return

        # Determine target version
        target_version = version or doc.pending_version or (
            (doc.active_version + 1) if doc.active_version else 1
        )
        old_version = doc.active_version

        # Transition status and update heartbeat
        if doc.active_version is None:
            doc.status = "processing"
        else:
            doc.status = "updating"

        doc.pending_version = target_version
        doc.heartbeat_at = datetime.now(timezone.utc)
        await session.commit()

        try:
            logger.info(f"Beginning parsing for document {document_id} (version={target_version}, type={doc.source_type})...")
            parsed_blocks = parse_source(doc.source_type, doc.source_uri)

            doc.heartbeat_at = datetime.now(timezone.utc)
            await session.commit()

            chunks = chunk_document(parsed_blocks, str(doc.id), target_version)
            if not chunks:
                raise ValueError("No text content could be extracted from document.")

            logger.info(f"Generated {len(chunks)} chunk(s) for document {document_id}. Embedding and staging...")

            # Embed and stage in Qdrant with is_active=False
            batch_size = 32
            for i in range(0, len(chunks), batch_size):
                batch_chunks = chunks[i : i + batch_size]
                texts = [c.content for c in batch_chunks]

                dense_vecs = embedding_service.embed_texts(texts)
                sparse_vecs = embedding_service.embed_sparse(texts)

                points = []
                for chunk, dense, sparse in zip(batch_chunks, dense_vecs, sparse_vecs):
                    payload = chunk.to_payload()
                    payload["document_name"] = doc.name
                    payload["is_active"] = False  # Hidden from queries during staging

                    points.append(
                        qmodels.PointStruct(
                            id=chunk.chunk_id,
                            vector={
                                "dense": dense,
                                "sparse": qmodels.SparseVector(
                                    indices=sparse.indices,
                                    values=sparse.values,
                                ),
                            },
                            payload=payload,
                        )
                    )

                qc.upsert(collection_name=COLLECTION_NAME, points=points)

                # Keep heartbeat updated
                doc.heartbeat_at = datetime.now(timezone.utc)
                await session.commit()

            # Cutover: Flip new version to is_active=True
            logger.info(f"Staging complete for document {document_id}. Performing cutover to version {target_version}...")
            qc.set_payload(
                collection_name=COLLECTION_NAME,
                payload={"is_active": True},
                points=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=str(doc.id)),
                            ),
                            qmodels.FieldCondition(
                                key="version",
                                match=qmodels.MatchValue(value=target_version),
                            ),
                        ]
                    )
                ),
            )

            # Purge previous version chunks if this was an update
            if old_version is not None and old_version != target_version:
                logger.info(f"Purging old chunks for document {document_id} (version={old_version})...")
                qc.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=qmodels.FilterSelector(
                        filter=qmodels.Filter(
                            must=[
                                qmodels.FieldCondition(
                                    key="document_id",
                                    match=qmodels.MatchValue(value=str(doc.id)),
                                ),
                                qmodels.FieldCondition(
                                    key="version",
                                    match=qmodels.MatchValue(value=old_version),
                                ),
                            ]
                        )
                    ),
                )

            # Update database status to active
            doc.active_version = target_version
            doc.pending_version = None
            doc.status = "active"
            doc.last_error = None
            doc.heartbeat_at = None
            await session.commit()
            logger.info(f"Successfully activated document {document_id} at version {target_version}.")

        except Exception as exc:
            logger.error(f"Ingestion failed for document {document_id}: {exc}", exc_info=True)

            # Clean up staged unactivated chunks
            try:
                qc.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=qmodels.FilterSelector(
                        filter=qmodels.Filter(
                            must=[
                                qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=str(doc.id)),
                            ),
                            qmodels.FieldCondition(
                                key="version",
                                match=qmodels.MatchValue(value=target_version),
                            ),
                            qmodels.FieldCondition(
                                key="is_active",
                                match=qmodels.MatchValue(value=False),
                            ),
                        ]
                    )
                ),
            )
            except Exception as cleanup_err:
                logger.warning(f"Error during staged chunks cleanup for {document_id}: {cleanup_err}")

            # Revert or mark failed in DB
            if old_version is not None:
                # Update failed: rollback to existing active version
                doc.status = "active"
                doc.pending_version = None
                doc.last_error = str(exc)
                doc.heartbeat_at = None
            else:
                # First-time ingestion failed
                doc.status = "failed"
                doc.pending_version = None
                doc.last_error = str(exc)
                doc.heartbeat_at = None

            await session.commit()
            raise


@celery_app.task(name="app.workers.tasks_ingestion.ingest_document_task")
def ingest_document_task(document_id: str, version: Optional[int] = None):
    """Synchronous Celery task wrapper calling async ingestion."""
    return asyncio.run(_async_ingest_document(document_id, version))
