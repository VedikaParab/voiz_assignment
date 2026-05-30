"""
retriever.py — VOIZ A3 RAG Pipeline
Retrieval engine: embed query, find top-k similar chunks, return with metadata & scores.
Uses shared config.py (Groq) for generation and hallucination judging.
"""

import sys
import os
from typing import List, Dict, Any
import chromadb

# Allow importing config.py from parent voiz/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import chat

from ingestor import embed


# ── Context formatter ──────────────────────────────────────────────────────────
def format_context(chunks: List[Dict[str, Any]]) -> str:
    lines = ["=== RETRIEVED CONTEXT ===\n"]
    for i, chunk in enumerate(chunks, 1):
        meta = chunk["metadata"]
        score = chunk.get("score", 0.0)
        lines.append(
            f"[{i}] Source: {meta['source_doc']} | "
            f"Chunk: {meta['chunk_id']} | "
            f"Page: {meta.get('page_number', '?')} | "
            f"Relevance: {score:.3f}\n"
            f"{chunk['text']}\n"
        )
    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)


# ── Retrieval engine ──────────────────────────────────────────────────────────
def retrieve(
    query: str,
    collection: chromadb.Collection,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Embed query, retrieve top_k similar chunks, return with scores."""
    query_embedding = embed(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        similarity = max(0.0, 1.0 - dist / 2.0)
        chunks.append({"text": doc, "metadata": meta, "score": round(similarity, 4)})

    chunks.sort(key=lambda x: x["score"], reverse=True)
    return chunks


# ── Generation layer (uses config.chat → Groq) ────────────────────────────────
def generate_grounded_response(
    query: str,
    chunks: List[Dict[str, Any]],
) -> str:
    """
    Inject retrieved chunks into system prompt.
    Instructs the model to answer ONLY from context and cite sources.
    Uses shared config.chat() — no API key argument needed.
    """
    if not chunks:
        return (
            "This information is not available in my knowledge base. "
            "Please contact support for assistance."
        )

    context_block = format_context(chunks)

    system_prompt = f"""You are VOIZ, a grounded enterprise voice agent assistant.

Answer the user's question using ONLY the context provided below.

RULES:
1. Answer ONLY from the retrieved context. Do NOT use knowledge from your training data.
2. Every factual claim MUST be attributable to a specific source chunk.
3. After your answer, include a CITATIONS block in this exact format:
   [Source: {{doc_name}}, chunk {{chunk_id}}, relevance: {{score:.3f}}]
4. If the context does not contain sufficient information, say exactly:
   "This information is not available in my knowledge base."
5. Do not speculate, infer, or extrapolate beyond what the documents state.

{context_block}"""

    return chat(
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
        max_tokens=800,
        temperature=0.1,
    )


# ── Citation parser ────────────────────────────────────────────────────────────
def parse_citations(response_text: str) -> List[Dict[str, str]]:
    import re
    citations = []
    pattern = r"\[Source:\s*(.+?),\s*chunk\s*(.+?),\s*relevance:\s*([\d.]+)\]"
    for match in re.finditer(pattern, response_text):
        citations.append({
            "source": match.group(1).strip(),
            "chunk_id": match.group(2).strip(),
            "relevance": match.group(3).strip(),
        })
    return citations