"""
app.py — VOIZ A3 RAG Pipeline
Streamlit chat UI: left = chat, right = citations + hallucination flags.
Uses config.chat() (Groq) — reads GROQ_API_KEY from .env automatically.
Run: streamlit run app.py
"""

import sys
import os
import time
import streamlit as st

# Allow config.py import from parent voiz/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vector_store import get_collection
from retriever import retrieve, generate_grounded_response
from hallucination_judge import judge

st.set_page_config(
    page_title="VOIZ Knowledge Base",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.hallucination-flag {
    background:#ff4444;color:white;padding:8px 12px;
    border-radius:6px;font-weight:bold;margin-bottom:8px;
}
.citation-card {
    background:#f0f4ff;border-left:4px solid #4a7aff;
    padding:10px;margin-bottom:10px;border-radius:4px;
}
.grounded-badge {
    background:#22c55e;color:white;padding:3px 10px;
    border-radius:12px;font-size:12px;
}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🎙️ VOIZ RAG")
    st.caption("Knowledge Base Assistant · Groq + ChromaDB")

    client_id = st.selectbox("Client / Tenant", ["client_A", "client_B"])
    top_k = st.slider("Chunks to retrieve (top-k)", 1, 5, 3)
    enable_judge = st.toggle("Hallucination Judge", value=True)

    st.divider()
    try:
        col = get_collection(client_id)
        count = col.count()
        if count > 0:
            st.success(f"✅ {count} chunks loaded")
        else:
            st.warning("⚠️ Empty — run: python ingestor.py")
    except Exception as e:
        st.error(f"DB error: {e}")

    st.divider()
    st.caption("A3 · Predixion AI · Groq llama-3.3-70b")

# ── Session state ──────────────────────────────────────────────────────────────
if "messages"     not in st.session_state: st.session_state.messages     = []
if "last_context" not in st.session_state: st.session_state.last_context = []
if "last_judge"   not in st.session_state: st.session_state.last_judge   = None

# ── Layout ────────────────────────────────────────────────────────────────────
col_chat, col_citations = st.columns([3, 2])

with col_chat:
    st.subheader("🎙️ Chat")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask something about the knowledge base..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Retrieving and generating..."):
                t0 = time.time()
                try:
                    collection = get_collection(client_id)
                    if collection.count() == 0:
                        response = "⚠️ Knowledge base is empty. Run `python ingestor.py` first."
                        chunks, judge_result = [], None
                    else:
                        chunks = retrieve(prompt, collection, top_k=top_k)
                        response = generate_grounded_response(prompt, chunks)
                        judge_result = judge(response, chunks) if enable_judge and chunks else None
                except Exception as e:
                    response = f"❌ Error: {e}"
                    chunks, judge_result = [], None

                latency = round(time.time() - t0, 2)

            st.markdown(response)
            if judge_result and judge_result.get("hallucinated"):
                st.markdown(
                    '<div class="hallucination-flag">🔴 HALLUCINATION DETECTED — see Citations panel</div>',
                    unsafe_allow_html=True,
                )
            st.caption(f"⏱ {latency}s · {len(chunks)} chunks · {client_id} · Groq")

        st.session_state.messages.append({"role": "assistant", "content": response})
        st.session_state.last_context = chunks
        st.session_state.last_judge   = judge_result

# ── Citations panel ────────────────────────────────────────────────────────────
with col_citations:
    st.subheader("📎 Citations & Sources")
    chunks      = st.session_state.last_context
    judge_result = st.session_state.last_judge

    if not chunks:
        st.info("Citations will appear here after your first query.")
    else:
        if judge_result:
            if judge_result.get("hallucinated"):
                st.markdown('<div class="hallucination-flag">🔴 HALLUCINATION DETECTED</div>',
                            unsafe_allow_html=True)
                st.write(f"**Faithfulness:** {judge_result.get('faithfulness_score', 0):.2f} / 1.00")
                for claim in judge_result.get("flagged_claims", []):
                    st.markdown(f"- ⚠️ {claim}")
                with st.expander("Judge reasoning"):
                    st.write(judge_result.get("reasoning", ""))
            else:
                st.markdown('<span class="grounded-badge">✅ Fully Grounded</span>',
                            unsafe_allow_html=True)
                st.write(f"**Faithfulness:** {judge_result.get('faithfulness_score', 1):.2f} / 1.00")
            st.divider()

        st.write(f"**{len(chunks)} source chunk(s):**")
        for i, chunk in enumerate(chunks, 1):
            meta  = chunk["metadata"]
            score = chunk.get("score", 0.0)
            icon  = "🟢" if score > 0.7 else ("🟡" if score > 0.4 else "🔴")
            with st.expander(f"{icon} [{i}] {meta.get('source_doc','?')} — {score:.3f}"):
                st.markdown(
                    f'<div class="citation-card">'
                    f'<b>Doc:</b> {meta.get("source_doc","?")}<br>'
                    f'<b>Chunk:</b> {meta.get("chunk_id","?")}<br>'
                    f'<b>Page:</b> {meta.get("page_number","?")}<br>'
                    f'Relevance: {score:.4f}</div>',
                    unsafe_allow_html=True,
                )
                st.text(chunk["text"][:400] + ("..." if len(chunk["text"]) > 400 else ""))

    st.divider()
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages     = []
        st.session_state.last_context = []
        st.session_state.last_judge   = None
        st.rerun()