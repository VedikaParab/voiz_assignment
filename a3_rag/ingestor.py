"""
ingestor.py — VOIZ A3 RAG Pipeline
Loads documents, chunks at 300 tokens / 50 overlap, embeds with
sentence-transformers (local, free), stores in ChromaDB.
No API key needed — embeddings are fully local.
"""

import os
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any

from sentence_transformers import SentenceTransformer
import chromadb

# ── Local embedding model (free, no API key) ───────────────────────────────────
_model: SentenceTransformer | None = None

def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print("  Loading sentence-transformers model (first run only)...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


# ── Session-level embedding cache ─────────────────────────────────────────────
_embed_cache: Dict[str, List[float]] = {}

def embed(text: str) -> List[float]:
    key = hashlib.md5(text.encode()).hexdigest()
    if key not in _embed_cache:
        _embed_cache[key] = _get_model().encode(text).tolist()
    return _embed_cache[key]


# ── Token approximation ────────────────────────────────────────────────────────
def _approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.33))


# ── Chunker (paragraph-aware) ──────────────────────────────────────────────────
def chunk_text(
    text: str,
    source: str,
    chunk_size: int = 300,
    overlap: int = 50,
) -> List[Dict[str, Any]]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: List[Dict[str, Any]] = []
    current_words: List[str] = []
    chunk_idx = 0

    def flush(words: List[str]) -> None:
        nonlocal chunk_idx
        if not words:
            return
        chunk_str = " ".join(words)
        chunks.append({
            "text":        chunk_str,
            "source":      source,
            "chunk_id":    f"{Path(source).stem}_chunk_{chunk_idx:04d}",
            "page_number": max(1, (chunk_idx * chunk_size) // 400 + 1),
        })
        chunk_idx += 1

    for para in paragraphs:
        for word in para.split():
            current_words.append(word)
            if _approx_tokens(" ".join(current_words)) >= chunk_size:
                flush(current_words)
                overlap_words = int(overlap / 1.33)
                current_words = current_words[-overlap_words:] if overlap_words else []

    if current_words:
        flush(current_words)

    return chunks


# ── Document loader ────────────────────────────────────────────────────────────
def load_document(path: str) -> List[Dict[str, Any]]:
    ext = Path(path).suffix.lower()
    if ext == ".txt":
        text = Path(path).read_text(encoding="utf-8")
    elif ext == ".pdf":
        try:
            import fitz
            text = "\n\n".join(p.get_text() for p in fitz.open(path))
        except ImportError:
            raise ImportError("pip install pymupdf")
    elif ext == ".docx":
        try:
            from docx import Document
            text = "\n\n".join(p.text for p in Document(path).paragraphs if p.text.strip())
        except ImportError:
            raise ImportError("pip install python-docx")
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    return chunk_text(text, source=Path(path).name)


# ── Ingest to ChromaDB ────────────────────────────────────────────────────────
def ingest_documents(doc_paths: List[str], collection) -> int:
    total = 0
    for path in doc_paths:
        print(f"  Ingesting: {Path(path).name} ...", end="", flush=True)
        chunks = load_document(path)

        ids        = [c["chunk_id"]   for c in chunks]
        texts      = [c["text"]       for c in chunks]
        embeddings = [embed(t)        for t in texts]
        metadatas  = [{"source_doc": c["source"], "chunk_id": c["chunk_id"],
                        "page_number": c["page_number"]} for c in chunks]

        for i in range(0, len(ids), 50):
            collection.add(
                ids=ids[i:i+50], embeddings=embeddings[i:i+50],
                documents=texts[i:i+50], metadatas=metadatas[i:i+50],
            )

        print(f" {len(chunks)} chunks")
        total += len(chunks)
    return total


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from vector_store import get_collection

    docs_dir  = Path(__file__).parent / "docs"
    doc_paths = sorted(docs_dir.glob("*.txt"))

    if not doc_paths:
        print("No .txt files found in docs/ — run generator.py first")
        exit(1)

    print("=== VOIZ RAG — Document Ingestion ===")
    col = get_collection("client_A")
    n   = ingest_documents([str(p) for p in doc_paths], col)
    print(f"\nTotal chunks ingested into client_A: {n}")

    # Also seed client_B with a subset (for multi-tenant demo)
    print("\nSeeding client_B with docs 1-2 only (multi-tenant demo)...")
    col_b = get_collection("client_B")
    ingest_documents([str(doc_paths[0]), str(doc_paths[1])], col_b)