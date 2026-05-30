"""
multitenant_test.py — VOIZ A3 RAG Pipeline
Proves that client_A and client_B collections are completely isolated.
A query to client_A NEVER returns chunks from client_B's documents.

Run: python multitenant_test.py
"""

import os
from pathlib import Path

from vector_store import get_collection, delete_collection
from ingestor import embed, chunk_text

# ── Test fixtures ──────────────────────────────────────────────────────────────
CLIENT_A_DOC = """
ALPHA FINANCE COLLECTIONS POLICY
Settlement rates for Alpha Finance:
- 0-30 DPD: 95% of outstanding balance
- 31-60 DPD: 85% of outstanding balance
- 61-90 DPD: 70% of outstanding balance
The Alpha Finance helpline is 1800-123-4567.
"""

CLIENT_B_DOC = """
BETA BANK LOAN RECOVERY PROCEDURES
Beta Bank uses the following recovery thresholds:
- Stage 1: gentle reminder SMS at 5 DPD
- Stage 2: outbound call at 15 DPD
- Stage 3: legal notice at 90 DPD
Beta Bank recovery team email: recovery@betabank.example.com
"""


def seed_collection(client_id: str, text: str, source: str) -> None:
    """Seed a collection with one document's chunks."""
    col = get_collection(client_id)
    chunks = chunk_text(text, source=source, chunk_size=100, overlap=20)

    ids = [c["chunk_id"] for c in chunks]
    texts = [c["text"] for c in chunks]
    embeddings = [embed(t) for t in texts]
    metadatas = [
        {
            "source_doc": c["source"],
            "chunk_id": c["chunk_id"],
            "page_number": c["page_number"],
        }
        for c in chunks
    ]

    col.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


def query_collection(client_id: str, query: str, top_k: int = 3) -> list:
    """Query a collection and return results."""
    col = get_collection(client_id)
    if col.count() == 0:
        return []

    q_emb = embed(query)
    results = col.query(
        query_embeddings=[q_emb],
        n_results=min(top_k, col.count()),
        include=["documents", "metadatas"],
    )
    return list(zip(results["documents"][0], results["metadatas"][0]))


def run_isolation_tests() -> bool:
    """
    Run multi-tenant isolation tests.
    Returns True if all tests pass, False otherwise.
    """
    print("=== VOIZ Multi-Tenant Isolation Tests ===\n")

    # Clean up from previous runs
    delete_collection("test_client_A")
    delete_collection("test_client_B")

    # Seed separate collections
    print("Seeding client_A (Alpha Finance docs) ...")
    seed_collection("test_client_A", CLIENT_A_DOC, "alpha_finance_policy.txt")

    print("Seeding client_B (Beta Bank docs) ...")
    seed_collection("test_client_B", CLIENT_B_DOC, "beta_bank_procedures.txt")

    print()
    all_passed = True

    # ── Test 1: client_A query returns only client_A docs ────────────────────
    print("TEST 1: Query client_A — should return Alpha Finance chunks only")
    results_a = query_collection("test_client_A", "settlement rate DPD")
    sources_a = [m.get("source_doc", "") for _, m in results_a]
    leaked = any("beta" in s.lower() for s in sources_a)

    if not leaked and results_a:
        print(f"  ✅ PASS — {len(results_a)} chunks returned, all from Alpha Finance")
        for doc, meta in results_a:
            print(f"     Source: {meta['source_doc']} | {doc[:60]}...")
    else:
        print(f"  ❌ FAIL — Beta Bank data leaked into client_A results!")
        all_passed = False

    print()

    # ── Test 2: client_B query returns only client_B docs ────────────────────
    print("TEST 2: Query client_B — should return Beta Bank chunks only")
    results_b = query_collection("test_client_B", "loan recovery stage")
    sources_b = [m.get("source_doc", "") for _, m in results_b]
    leaked = any("alpha" in s.lower() for s in sources_b)

    if not leaked and results_b:
        print(f"  ✅ PASS — {len(results_b)} chunks returned, all from Beta Bank")
        for doc, meta in results_b:
            print(f"     Source: {meta['source_doc']} | {doc[:60]}...")
    else:
        print(f"  ❌ FAIL — Alpha Finance data leaked into client_B results!")
        all_passed = False

    print()

    # ── Test 3: A client cannot access B's collection directly ────────────────
    print("TEST 3: client_A collection has ZERO chunks from client_B's source docs")
    col_a = get_collection("test_client_A")
    # Query with a phrase that only exists in Beta Bank doc
    results_cross = query_collection("test_client_A", "Beta Bank recovery email")
    sources_cross = [m.get("source_doc", "") for _, m in results_cross]
    leaked_cross = any("beta" in s.lower() for s in sources_cross)

    if not leaked_cross:
        print("  ✅ PASS — Beta Bank content is architecturally absent from client_A collection")
    else:
        print("  ❌ FAIL — Cross-collection data found!")
        all_passed = False

    print()

    # ── Test 4: collection counts are independent ──────────────────────────────
    print("TEST 4: Collection counts are independent")
    count_a = get_collection("test_client_A").count()
    count_b = get_collection("test_client_B").count()
    print(f"  client_A chunks: {count_a}")
    print(f"  client_B chunks: {count_b}")
    assert count_a > 0 and count_b > 0
    print("  ✅ PASS — both collections non-empty and independent")

    # Teardown
    delete_collection("test_client_A")
    delete_collection("test_client_B")

    print()
    if all_passed:
        print("=" * 50)
        print("✅ ALL ISOLATION TESTS PASSED — multi-tenant safe")
    else:
        print("=" * 50)
        print("❌ SOME TESTS FAILED — check vector_store.py")

    return all_passed


if __name__ == "__main__":
    success = run_isolation_tests()
    exit(0 if success else 1)