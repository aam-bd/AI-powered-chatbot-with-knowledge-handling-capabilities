"""Celery application configuration and beat schedule."""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "chatbot_workers",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "reconcile-stale-documents": {
            "task": "app.workers.tasks_reconcile.reconcile_stale_documents_task",
            "schedule": 300.0,  # Every 5 minutes
        },
    },
)

# Explicitly import task modules so worker and beat register them immediately
import app.workers.tasks_ingestion
import app.workers.tasks_deletion
import app.workers.tasks_reconcile
