"""Periodic Celery task for reconciling stuck or orphaned document ingestion jobs."""
import asyncio
from datetime import datetime, timezone, timedelta
from qdrant_client.http import models as qmodels
from sqlalchemy import select

from app.core.config import settings
from app.core.logger import logger
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.db.session import AsyncSessionLocal
from app.models.sql_models import Document
from app.workers.celery_app import celery_app


async def _async_reconcile_stale_documents():
    """Find documents with stale heartbeats and recover or fail them gracefully."""
    qc = get_qdrant_client()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.RECONCILE_STALE_MINUTES)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(
                Document.status.in_(["processing", "updating"])
            )
        )
        stuck_candidates = result.scalars().all()

        for doc in stuck_candidates:
            last_ping = doc.heartbeat_at or doc.updated_at
            if last_ping < cutoff:
                logger.warning(
                    f"Reconciling stale ingestion for document {doc.id} "
                    f"(status={doc.status}, last_ping={last_ping}, cutoff={cutoff})"
                )

                # Clean up any staged points with is_active=False
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
                                        key="is_active",
                                        match=qmodels.MatchValue(value=False),
                                    ),
                                ]
                            )
                        ),
                    )
                except Exception as q_err:
                    logger.error(f"Error purging staged chunks during reconcile for {doc.id}: {q_err}")

                error_msg = f"Ingestion stalled (no heartbeat for >{settings.RECONCILE_STALE_MINUTES}m)"

                if doc.active_version is not None:
                    # Rollback to active version
                    doc.status = "active"
                    doc.pending_version = None
                    doc.last_error = error_msg
                    doc.heartbeat_at = None
                else:
                    # Mark initial ingestion failed
                    doc.status = "failed"
                    doc.pending_version = None
                    doc.last_error = error_msg
                    doc.heartbeat_at = None

        await session.commit()


@celery_app.task(name="app.workers.tasks_reconcile.reconcile_stale_documents_task")
def reconcile_stale_documents_task():
    """Synchronous Celery task wrapper calling async document reconciliation."""
    return asyncio.run(_async_reconcile_stale_documents())
