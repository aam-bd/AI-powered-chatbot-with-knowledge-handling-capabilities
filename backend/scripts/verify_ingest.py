"""Verification script to test live ingestion of sample_kb files via API and check Qdrant points."""
import time
import httpx
from qdrant_client.http import models as qmodels
from app.db.qdrant import get_qdrant_client, COLLECTION_NAME
from app.core.config import settings

BASE_URL = "http://localhost:8000/api/v1"


def main():
    print("=== Step 1: Login as Admin ===")
    with httpx.Client(timeout=30.0) as client:
        login_resp = client.post(
            f"{BASE_URL}/auth/login",
            json={"email": settings.ADMIN_EMAIL, "password": settings.ADMIN_PASSWORD.get_secret_value()},
        )
        if login_resp.status_code != 200:
            print(f"Failed to login: {login_resp.status_code} {login_resp.text}")
            return
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("Logged in successfully. Token acquired.")

        files_to_upload = [
            "/app/sample_kb/CSE446 Lecture 1.pdf",
            "/app/sample_kb/CSE446 Lecture 2.pdf",
        ]

        doc_ids = []
        for file_path in files_to_upload:
            filename = file_path.split("/")[-1]
            print(f"\n=== Step 2: Ingesting {filename} via POST /documents ===")
            with open(file_path, "rb") as f:
                content = f.read()

            upload_resp = client.post(
                f"{BASE_URL}/documents",
                files={"file": (filename, content, "application/pdf")},
                headers=headers,
            )
            print(f"Upload response: {upload_resp.status_code} {upload_resp.json()}")
            if upload_resp.status_code not in (202, 409):
                raise RuntimeError(f"Unexpected upload response: {upload_resp.status_code}")

            if upload_resp.status_code == 202:
                doc_id = upload_resp.json()["document_id"]
            else:
                doc_id = upload_resp.json()["existing_document_id"]
                print(f"Document already uploaded with ID: {doc_id}")
            doc_ids.append(doc_id)

        print("\n=== Step 3: Polling Document Status Until 'active' ===")
        for doc_id in doc_ids:
            start_time = time.time()
            while True:
                status_resp = client.get(f"{BASE_URL}/documents/{doc_id}/status", headers=headers)
                data = status_resp.json()
                st = data.get("status")
                err = data.get("last_error")
                print(f"Doc {doc_id} status: {st} (active_ver={data.get('active_version')}, err={err})")
                if st == "active":
                    print(f"SUCCESS: Document {doc_id} reached 'active' state!")
                    break
                elif st == "failed":
                    raise RuntimeError(f"Document ingestion failed for {doc_id}: {err}")

                if time.time() - start_time > 120:
                    raise TimeoutError(f"Document {doc_id} timed out waiting for active state.")
                time.sleep(3)

    print("\n=== Step 4: Verifying Qdrant Collection 'kb_chunks' ===")
    qc = get_qdrant_client()
    coll = qc.get_collection(COLLECTION_NAME)
    print(f"Total points in collection '{COLLECTION_NAME}': {coll.points_count}")
    dense_param = coll.config.params.vectors.get("dense")
    print(f"Dense vector dimension: {dense_param.size} (Distance: {dense_param.distance})")
    assert dense_param.size == 1024, f"Expected dense dim 1024, got {dense_param.size}"

    for doc_id in doc_ids:
        records, _ = qc.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id)),
                    qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True)),
                ]
            ),
            limit=5,
            with_vectors=True,
        )
        print(f"\nDocument {doc_id}: Found {len(records)} sample active points.")
        assert len(records) > 0, f"No active points found for document {doc_id}"
        sample = records[0]
        payload = sample.payload
        print("Sample Payload Keys:", list(payload.keys()))
        assert payload["is_active"] is True
        assert "content" in payload
        assert "token_count" in payload
        assert "chunk_index" in payload
        assert "version" in payload
        assert payload["version"] >= 1

        # Check vectors
        dense_vec = sample.vector.get("dense") if isinstance(sample.vector, dict) else None
        sparse_vec = sample.vector.get("sparse") if isinstance(sample.vector, dict) else None
        print(f"Dense vector length: {len(dense_vec) if dense_vec else 'None'}")
        print(f"Sparse vector indices: {len(sparse_vec.indices) if sparse_vec else 'None'}")
        assert len(dense_vec) == 1024
        assert len(sparse_vec.indices) > 0

    print("\n=== ALL INGESTION CHECKS PASSED SUCCESSFULLY! ===")


if __name__ == "__main__":
    main()
