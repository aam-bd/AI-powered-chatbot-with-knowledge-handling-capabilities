"""CLI script to re-embed all active documents from source files/URLs into Qdrant.

Used when EMBEDDING_MODEL or EMBEDDING_DIM changes.
Usage:
    python -m scripts.reindex [--batch-size 32] [--recreate-collection]
"""
import argparse
import asyncio
import os
import sys
from typing import List

from qdrant_client.http import models as qmodels
from sqlalchemy import select

from app.core.config import settings
from app.core.logger import logger
from app.db.qdrant import (
    get_qdrant_client,
    init_qdrant_collection,
    COLLECTION_NAME,
    META_POINT_ID,
)
from app.db.session import AsyncSessionLocal
from app.models.sql_models import Document
from app.services.chunker import chunk_document
from app.services.embedding.factory import get_embedding_service
from app.services.parsers.docx import parse_docx
from app.services.parsers.markdown import parse_markdown
from app.services.parsers.pdf import parse_pdf
from app.services.parsers.text import parse_text
from app.services.parsers.web import parse_web_url


async def get_active_documents() -> List[Document]:
    """Retrieve all active documents from PostgreSQL."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Document).where(Document.status == "active")
        )
        return list(result.scalars().all())


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


async def reindex_all(recreate_collection: bool = False, batch_size: int = 32):
    """Re-embed and re-index all active documents."""
    qc = get_qdrant_client()
    embedding_service = get_embedding_service()

    if recreate_collection:
        logger.info(f"Recreating Qdrant collection '{COLLECTION_NAME}'...")
        try:
            qc.delete_collection(collection_name=COLLECTION_NAME)
        except Exception:
            pass
        init_qdrant_collection(qc)
    else:
        init_qdrant_collection(qc)

    documents = await get_active_documents()
    logger.info(f"Found {len(documents)} active document(s) to reindex.")

    total_chunks_reindexed = 0

    for doc in documents:
        doc_id_str = str(doc.id)
        version = doc.active_version or 1
        logger.info(f"Reindexing document: {doc.name} (id={doc_id_str}, version={version})")

        try:
            parsed_blocks = parse_source(doc.source_type, doc.source_uri)
            chunks = chunk_document(parsed_blocks, doc_id_str, version)
            if not chunks:
                logger.warning(f"No chunks extracted for document {doc_id_str}, skipping.")
                continue

            # Delete old points for this document in Qdrant before re-inserting
            qc.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=doc_id_str),
                            )
                        ]
                    )
                ),
            )

            # Embed and upsert in batches
            for i in range(0, len(chunks), batch_size):
                batch_chunks = chunks[i : i + batch_size]
                texts = [c.content for c in batch_chunks]

                dense_vecs = embedding_service.embed_texts(texts)
                sparse_vecs = embedding_service.embed_sparse(texts)

                points = []
                for chunk, dense, sparse in zip(batch_chunks, dense_vecs, sparse_vecs):
                    payload = chunk.to_payload()
                    payload["is_active"] = True

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
                total_chunks_reindexed += len(points)

            logger.info(f"Successfully reindexed document {doc_id_str} ({len(chunks)} chunks).")

        except Exception as exc:
            logger.error(f"Failed to reindex document {doc_id_str}: {exc}", exc_info=True)

    # Update metadata sentinel point with current model and dim
    qc.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=META_POINT_ID,
                vector={
                    "dense": [0.0] * settings.EMBEDDING_DIM,
                    "sparse": qmodels.SparseVector(indices=[], values=[]),
                },
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

    logger.info(f"Reindexing complete. Reindexed {total_chunks_reindexed} chunk(s) across {len(documents)} document(s).")


def main():
    parser = argparse.ArgumentParser(description="Re-index active documents into Qdrant.")
    parser.add_argument("--recreate-collection", action="store_true", help="Drop and recreate Qdrant collection before indexing")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size for embedding and upserting")
    args = parser.parse_args()

    asyncio.run(reindex_all(recreate_collection=args.recreate_collection, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
