"""Qdrant client, collection initialization, and Embedding Guard verification."""
import httpx
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.core.logger import logger

COLLECTION_NAME = "kb_chunks"
META_POINT_ID = "00000000-0000-0000-0000-000000000000"


def get_qdrant_client() -> QdrantClient:
    """Return a synchronous QdrantClient configured with QDRANT_URL."""
    return QdrantClient(url=settings.QDRANT_URL, check_compatibility=False)


async def check_qdrant_health() -> bool:
    """Check connectivity to Qdrant via its HTTP healthz endpoint."""
    url = f"{settings.QDRANT_URL.rstrip('/')}/healthz"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            return resp.status_code == 200
    except Exception as exc:
        logger.warning(f"Qdrant health check failed: {exc}")
        return False


def init_qdrant_collection(client: QdrantClient = None) -> None:
    """Initialize kb_chunks collection with named dense & sparse vectors and payload indexes."""
    qc = client or get_qdrant_client()

    collections = qc.get_collections().collections
    collection_names = [c.name for c in collections]

    if COLLECTION_NAME not in collection_names:
        logger.info(f"Creating Qdrant collection '{COLLECTION_NAME}' with dense dim={settings.EMBEDDING_DIM} and BM25 sparse vector...")
        qc.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": qmodels.VectorParams(
                    size=settings.EMBEDDING_DIM,
                    distance=qmodels.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": qmodels.SparseVectorParams()
            },
        )

        # Create payload indexes for filtering
        qc.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="document_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
        qc.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="is_active",
            field_schema=qmodels.PayloadSchemaType.BOOL,
        )

        # Record embedding guard metadata point
        dummy_dense = [0.0] * settings.EMBEDDING_DIM
        qc.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                qmodels.PointStruct(
                    id=META_POINT_ID,
                    vector={"dense": dummy_dense, "sparse": qmodels.SparseVector(indices=[], values=[])},
                    payload={
                        "_type": "embedding_guard_metadata",
                        "is_active": False,
                        "document_id": "system_meta",
                        "embedding_model": settings.EMBEDDING_MODEL,
                        "embedding_dim": settings.EMBEDDING_DIM,
                    },
                )
            ],
        )
        logger.info(f"Qdrant collection '{COLLECTION_NAME}' initialized successfully.")
    else:
        # Collection already exists, verify embedding guard
        verify_embedding_guard(qc)


def verify_embedding_guard(client: QdrantClient = None) -> None:
    """Verify that current EMBEDDING_MODEL and EMBEDDING_DIM match the Qdrant collection."""
    qc = client or get_qdrant_client()
    try:
        coll_info = qc.get_collection(collection_name=COLLECTION_NAME)
    except Exception as exc:
        raise RuntimeError(f"Failed to inspect Qdrant collection '{COLLECTION_NAME}': {exc}") from exc

    # Check vector dimension
    dense_param = coll_info.config.params.vectors.get("dense")
    if not dense_param:
        raise RuntimeError(f"Qdrant collection '{COLLECTION_NAME}' is missing named 'dense' vector configuration.")

    actual_dim = dense_param.size
    if actual_dim != settings.EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding Guard Mismatch: Qdrant collection '{COLLECTION_NAME}' dimension is {actual_dim}, "
            f"but current configuration EMBEDDING_DIM is {settings.EMBEDDING_DIM}. "
            "Refusing to write to corrupted index. Run scripts/reindex.py to rebuild."
        )

    # Check metadata point if present
    try:
        pts = qc.retrieve(collection_name=COLLECTION_NAME, ids=[META_POINT_ID])
        if pts:
            meta = pts[0].payload or {}
            saved_model = meta.get("embedding_model")
            if saved_model and saved_model != settings.EMBEDDING_MODEL:
                raise RuntimeError(
                    f"Embedding Guard Mismatch: Collection was built with model '{saved_model}', "
                    f"but configuration specifies EMBEDDING_MODEL='{settings.EMBEDDING_MODEL}'. "
                    "Refusing to proceed. Run scripts/reindex.py to re-embed all documents."
                )
    except UnexpectedResponse:
        pass
