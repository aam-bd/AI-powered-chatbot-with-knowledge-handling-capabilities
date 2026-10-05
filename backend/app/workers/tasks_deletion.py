"""Celery task for asynchronous document deletion (Phase 2 of two-phase delete)."""
import asyncio
import os
import uuid
from qdrant_client.http import models as qmodels
from sqlalchemy import select

from app.core.logger import logger
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.db.session import AsyncSessionLocal
from app.models.sql_models import Document
from app.workers.celery_app import celery_app


async def _async_delete_document(document_id: str):
    """Purge Qdrant points, local source file, and PostgreSQL document record."""
    qc = get_qdrant_client()
    doc_uuid = uuid.UUID(document_id)

    logger.info(f"Phase 2 Delete: Purging document {document_id} from Qdrant and storage...")

    # 1. Purge points from Qdrant
    try:
        qc.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="document_id",
                            match=qmodels.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )
        logger.info(f"Purged all vector points for document {document_id} in Qdrant.")
    except Exception as q_err:
        logger.error(f"Error purging Qdrant points for {document_id}: {q_err}")

    # 2. Delete file and database record
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.id == doc_uuid)
        )
        doc = result.scalar_one_or_none()

        if doc:
            # Delete local file if it exists
            if doc.source_type != "url" and doc.source_uri and os.path.exists(doc.source_uri):
                try:
                    os.remove(doc.source_uri)
                    logger.info(f"Removed source file {doc.source_uri} for document {document_id}.")
                except Exception as file_err:
                    logger.warning(f"Could not remove source file {doc.source_uri}: {file_err}")

            await session.delete(doc)
            await session.commit()
            logger.info(f"Deleted document {document_id} record from PostgreSQL.")
        else:
            logger.warning(f"Document {document_id} not found in PostgreSQL during Phase 2 delete.")


@celery_app.task(name="app.workers.tasks_deletion.delete_document_task")
def delete_document_task(document_id: str):
    """Synchronous Celery task wrapper calling async deletion."""
    return asyncio.run(_async_delete_document(document_id))
