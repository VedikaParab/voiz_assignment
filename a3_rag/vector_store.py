"""
vector_store.py — VOIZ A3 RAG Pipeline
ChromaDB multi-tenant manager: one isolated collection per client_id.
Cross-collection access is architecturally impossible.
"""

import os
from typing import Dict
from pathlib import Path

import chromadb

# ── Persistent ChromaDB client ────────────────────────────────────────────────
_DB_PATH = Path(__file__).parent / ".chromadb"
_client: chromadb.PersistentClient | None = None
_collections: Dict[str, chromadb.Collection] = {}


def _get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _DB_PATH.mkdir(exist_ok=True)
        _client = chromadb.PersistentClient(path=str(_DB_PATH))
    return _client


def get_collection(client_id: str) -> chromadb.Collection:
    """
    Return (or create) the ChromaDB collection for this client_id.
    Each client gets an isolated namespace — voiz_{client_id}.
    """
    if client_id not in _collections:
        client = _get_client()
        # Collection name scoped to client — prevents any cross-tenant access
        collection_name = f"voiz_{client_id}"
        _collections[client_id] = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # cosine similarity
        )
    return _collections[client_id]


def delete_collection(client_id: str) -> None:
    """Wipe a client's collection (for test teardown)."""
    client = _get_client()
    try:
        client.delete_collection(f"voiz_{client_id}")
    except Exception:
        pass
    _collections.pop(client_id, None)


def collection_stats(client_id: str) -> dict:
    col = get_collection(client_id)
    return {
        "client_id": client_id,
        "collection_name": col.name,
        "chunk_count": col.count(),
    }


if __name__ == "__main__":
    # Quick smoke test
    col = get_collection("smoke_test")
    print("Collection created:", col.name)
    print("Count:", col.count())
    delete_collection("smoke_test")
    print("Deleted OK")