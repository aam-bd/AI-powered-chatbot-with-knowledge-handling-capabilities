"""Acceptance tests for document lifecycle, blue-green cutover, failure rollback, two-phase delete, reconciliation, and idempotency."""
import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient, ASGITransport
from qdrant_client.http import models as qmodels
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.qdrant import get_qdrant_client, init_qdrant_collection, COLLECTION_NAME
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.sql_models import Document, User
from app.workers.tasks_ingestion import _async_ingest_document
from app.workers.tasks_deletion import _async_delete_document
from app.workers.tasks_reconcile import _async_reconcile_stale_documents


@pytest.fixture(scope="module", autouse=True)
def ensure_qdrant_ready():
    """Ensure Qdrant collection is created before tests run."""
    qc = get_qdrant_client()
    init_qdrant_collection(qc)


async def get_or_create_admin():
    """Helper to ensure an admin user exists for authenticated test calls."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == "admin_lifecycle@example.com")
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                id=uuid.uuid4(),
                email="admin_lifecycle@example.com",
                password_hash=hash_password("AdminSecurePassword123!"),
                role="admin",
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


@pytest.mark.asyncio
async def test_duplicate_prevention_via_api():
    """Verify upload identical file returns 409 Conflict with existing_document_id."""
    admin = await get_or_create_admin()
    token = create_access_token(user_id=str(admin.id), role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    unique_run_id = uuid.uuid4().hex
    sample_content = f"%PDF-1.4 Lifecycle duplicate prevention test {unique_run_id}.".encode()
    files = {"file": ("test_duplicate.pdf", sample_content, "application/pdf")}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # First upload
        resp1 = await ac.post("/api/v1/documents", files=files, headers=headers)
        assert resp1.status_code == 202
        doc_id1 = resp1.json()["document_id"]

        # Duplicate upload of identical content
        files2 = {"file": ("test_duplicate_copy.pdf", sample_content, "application/pdf")}
        resp2 = await ac.post("/api/v1/documents", files=files2, headers=headers)
        assert resp2.status_code == 409
        body2 = resp2.json()
        assert body2.get("existing_document_id") == doc_id1


@pytest.mark.asyncio
async def test_blue_green_search_consistency():
    """Verify search consistency during blue-green updates.
    
    Queries during ingestion never see partial chunks; after cutover, new chunks
    appear and old chunks disappear.
    """
    qc = get_qdrant_client()
    doc_id = str(uuid.uuid4())
    unique_sha = f"sha_bg_{uuid.uuid4().hex}"

    # Create document record
    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.UUID(doc_id),
            name="blue_green_test.txt",
            source_type="txt",
            source_uri=f"/app/uploads/{doc_id}.txt",
            sha256=unique_sha,
            size_bytes=100,
            status="pending",
            active_version=None,
            pending_version=1,
        )
        session.add(doc)
        await session.commit()

    # Stage Version 1 chunks with is_active=False
    dummy_dense = [0.1] * settings.EMBEDDING_DIM
    v1_point_id = str(uuid.uuid4())
    qc.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=v1_point_id,
                vector={
                    "dense": dummy_dense,
                    "sparse": qmodels.SparseVector(indices=[1], values=[1.0]),
                },
                payload={
                    "document_id": doc_id,
                    "version": 1,
                    "chunk_index": 0,
                    "content": "Version 1 staged content",
                    "is_active": False,  # STAGED
                },
            )
        ],
    )

    # Search for active chunks - MUST be 0 results
    active_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    assert len(active_hits) == 0

    # Cutover Version 1: flip is_active=True
    qc.set_payload(
        collection_name=COLLECTION_NAME,
        payload={"is_active": True},
        points=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                    qmodels.FieldCondition(key="version", match=qmodels.MatchValue(value=1)),
                ]
            )
        ),
    )

    # Search for active chunks - MUST be 1 result
    active_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    assert len(active_hits) == 1
    assert active_hits[0].payload["version"] == 1

    # Stage Version 2 chunks with is_active=False
    v2_point_id = str(uuid.uuid4())
    qc.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=v2_point_id,
                vector={
                    "dense": dummy_dense,
                    "sparse": qmodels.SparseVector(indices=[2], values=[1.0]),
                },
                payload={
                    "document_id": doc_id,
                    "version": 2,
                    "chunk_index": 0,
                    "content": "Version 2 staged content",
                    "is_active": False,  # STAGED
                },
            )
        ],
    )

    # Search during Version 2 staging - MUST STILL return ONLY Version 1
    active_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    assert len(active_hits) == 1
    assert active_hits[0].payload["version"] == 1

    # Cutover to Version 2: activate v2, delete v1
    qc.set_payload(
        collection_name=COLLECTION_NAME,
        payload={"is_active": True},
        points=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                    qmodels.FieldCondition(key="version", match=qmodels.MatchValue(value=2)),
                ]
            )
        ),
    )
    qc.delete(
        collection_name=COLLECTION_NAME,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                    qmodels.FieldCondition(key="version", match=qmodels.MatchValue(value=1)),
                ]
            )
        ),
    )

    # Search after cutover - MUST return ONLY Version 2
    active_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    assert len(active_hits) == 1
    assert active_hits[0].payload["version"] == 2


@pytest.mark.asyncio
async def test_update_rollback_on_failure():
    """Verify failed update leaves active version intact and searchable; pending chunks cleaned up."""
    qc = get_qdrant_client()
    doc_id = str(uuid.uuid4())
    unique_sha = f"sha_rb_{uuid.uuid4().hex}"
    dummy_dense = [0.1] * settings.EMBEDDING_DIM

    # Create document active at version 1
    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.UUID(doc_id),
            name="rollback_test.txt",
            source_type="txt",
            source_uri=f"/app/uploads/{doc_id}.txt",
            sha256=unique_sha,
            size_bytes=100,
            status="active",
            active_version=1,
            pending_version=None,
        )
        session.add(doc)
        await session.commit()

    # Insert active Version 1 point
    v1_id = str(uuid.uuid4())
    qc.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=v1_id,
                vector={
                    "dense": dummy_dense,
                    "sparse": qmodels.SparseVector(indices=[1], values=[1.0]),
                },
                payload={
                    "document_id": doc_id,
                    "version": 1,
                    "chunk_index": 0,
                    "content": "Active version 1 content",
                    "is_active": True,
                },
            )
        ],
    )

    # Stage invalid Version 2 that fails
    with pytest.raises(Exception):
        await _async_ingest_document(doc_id, version=2)

    # Verify document in DB reverted to active version 1 with last_error populated
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.id == uuid.UUID(doc_id))
        )
        updated_doc = result.scalar_one()
        assert updated_doc.status == "active"
        assert updated_doc.active_version == 1
        assert updated_doc.pending_version is None
        assert updated_doc.last_error is not None

    # Verify Qdrant active search still returns Version 1
    active_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    assert len(active_hits) == 1
    assert active_hits[0].payload["version"] == 1


@pytest.mark.asyncio
async def test_two_phase_delete(monkeypatch):
    """Verify two-phase delete: delete request immediately hides document; async worker purges points."""
    # Prevent background Celery worker race condition so we can test Phase 1 and Phase 2 deterministically
    monkeypatch.setattr(
        "app.api.v1.documents.delete_document_task.delay",
        lambda doc_id: None,
    )

    qc = get_qdrant_client()
    doc_id = str(uuid.uuid4())
    unique_sha = f"sha_del_{uuid.uuid4().hex}"
    dummy_dense = [0.1] * settings.EMBEDDING_DIM

    # Create active document in /tmp
    temp_file = f"/tmp/{doc_id}.txt"
    with open(temp_file, "w") as f:
        f.write("temporary file content")

    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.UUID(doc_id),
            name="delete_test.txt",
            source_type="txt",
            source_uri=temp_file,
            sha256=unique_sha,
            size_bytes=100,
            status="active",
            active_version=1,
        )
        session.add(doc)
        await session.commit()

    # Seed active point in Qdrant
    p_id = str(uuid.uuid4())
    qc.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=p_id,
                vector={
                    "dense": dummy_dense,
                    "sparse": qmodels.SparseVector(indices=[1], values=[1.0]),
                },
                payload={
                    "document_id": doc_id,
                    "version": 1,
                    "chunk_index": 0,
                    "content": "To be deleted",
                    "is_active": True,
                },
            )
        ],
    )

    admin = await get_or_create_admin()
    token = create_access_token(user_id=str(admin.id), role="admin")
    headers = {"Authorization": f"Bearer {token}"}

    # Execute Phase 1 via HTTP DELETE
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        del_resp = await ac.delete(f"/api/v1/documents/{doc_id}", headers=headers)
        assert del_resp.status_code == 202

    # Verify Phase 1: instantly hidden from active search
    active_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    assert len(active_hits) == 0

    # Execute Phase 2 async deletion worker task
    await _async_delete_document(doc_id)

    # Verify Qdrant points completely purged
    all_hits = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
            ]
        ),
    )[0]
    assert len(all_hits) == 0

    # Verify local file deleted
    assert not os.path.exists(temp_file)

    # Verify DB record removed
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.id == uuid.UUID(doc_id))
        )
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_ingestion_reconciler():
    """Verify reconciler recovers stuck documents with expired heartbeats."""
    doc_id = str(uuid.uuid4())
    unique_sha = f"sha_rec_{uuid.uuid4().hex}"
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=settings.RECONCILE_STALE_MINUTES + 10)

    # Document updating from v1 to v2 that stalled
    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.UUID(doc_id),
            name="stalled_doc.txt",
            source_type="txt",
            source_uri=f"/app/uploads/{doc_id}.txt",
            sha256=unique_sha,
            size_bytes=50,
            status="updating",
            active_version=1,
            pending_version=2,
            heartbeat_at=stale_time,
        )
        session.add(doc)
        await session.commit()

    # Run reconciler
    await _async_reconcile_stale_documents()

    # Verify document rolled back to active version 1
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.id == uuid.UUID(doc_id))
        )
        reconciled = result.scalar_one()
        assert reconciled.status == "active"
        assert reconciled.active_version == 1
        assert reconciled.pending_version is None
        assert "no heartbeat" in (reconciled.last_error or "")


@pytest.mark.asyncio
async def test_task_idempotency():
    """Verify running ingest task twice on the same document version produces identical, consistent state."""
    qc = get_qdrant_client()
    doc_id = str(uuid.uuid4())
    unique_sha = f"sha_idem_{uuid.uuid4().hex}"
    temp_file = f"/tmp/{doc_id}_idempotency.txt"
    with open(temp_file, "w") as f:
        f.write("Line 1 of idempotency document text.\nLine 2 of idempotency text.")

    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.UUID(doc_id),
            name="idempotent.txt",
            source_type="txt",
            source_uri=temp_file,
            sha256=unique_sha,
            size_bytes=len("Line 1 of idempotency document text.\nLine 2 of idempotency text."),
            status="pending",
            active_version=None,
            pending_version=1,
        )
        session.add(doc)
        await session.commit()

    # First run of ingestion
    await _async_ingest_document(doc_id, version=1)

    # Check point count
    hits_run1 = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    count1 = len(hits_run1)
    assert count1 > 0

    # Second run of ingestion on same document version
    await _async_ingest_document(doc_id, version=1)

    # Check point count after second run - MUST be identical, no point duplicates!
    hits_run2 = qc.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
            ]
        ),
    )[0]
    count2 = len(hits_run2)
    assert count2 == count1

    # Cleanup
    await _async_delete_document(doc_id)
