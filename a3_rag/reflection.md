# A3 — RAG Pipeline: Reflection

**Predixion AI · VOIZ Platform · Intern Assignment 03**
**Author:** Vedika Parab · Date: May 2026

---

## Evaluation Results Summary

The pipeline was evaluated against 20 test questions: 17 grounded questions across 5 knowledge-base documents and 3 out-of-domain questions that should be declined.

| Metric | Result | Target |
|---|---|---|
| Precision | 100% | ≥85% |
| Recall | 100% | ≥85% |
| Out-of-domain decline accuracy | 100% | ≥80% |
| Hallucination rate | 0.0% | <2% |
| Avg faithfulness score | 1.00 / 1.00 | >0.80 |

All 17 grounded questions were answered correctly from retrieved context. All 3 out-of-domain questions (biryani recipe, 2024 IPL winner, Python sorting function) were correctly declined with the phrase "This information is not available in my knowledge base." Zero hallucinated claims were flagged across all 20 responses.

---

## What Chunking Strategy Gave the Best Retrieval Quality

The pipeline uses **paragraph-aware chunking** with a target of 300 tokens per chunk and a 50-token overlap between consecutive chunks. This was not the first approach tried.

The initial implementation used fixed-size character-count chunking at 1,200 characters. This worked poorly for the collections policy document (`01_collections_policy.txt`) because DPD bucket definitions — which appear as a table-like structure in the source — were split mid-row. A query about "Bucket 2 settlement discount" would retrieve a chunk containing the tail of Bucket 1 and the head of Bucket 2, with neither definition complete. Retrieval scores were artificially high (the right words were present) but the generated response was either incomplete or blended two bucket definitions.

Switching to paragraph-aware chunking (splitting on `\n\n` boundaries first, then accumulating words until the token budget is reached) solved this. Policy documents, FAQs, and SOPs are all naturally paragraph-structured. Each paragraph expresses one complete idea. Chunks aligned to paragraph boundaries gave the retrieval engine coherent units to score, and the generator a complete context to reason from.

The 50-token overlap was added to handle queries whose answer spans a paragraph boundary — for example, "What must an agent do if a borrower mentions legal action?" where the trigger condition is at the end of one paragraph and the required actions are at the start of the next. Without overlap, the retrieval would often return only the condition or only the response, not both. With overlap, one of the top-3 chunks always contained the full sequence.

The chunker also handles multi-format inputs: `.txt` via direct read, `.pdf` via PyMuPDF page extraction, and `.docx` via python-docx paragraph iteration. All three produce the same chunk format `{text, source, chunk_id, page_number}` that the retrieval engine and UI consume identically.

---

## What Types of Questions Caused the Most Hallucinations

In this run, zero hallucinations were detected. However, during development, two categories of questions were observed to produce hallucinated claims before the generation prompt was tightened:

**Aggregation questions.** Questions like "What are all the settlement discount percentages across all DPD buckets?" require the generator to synthesise information from multiple chunks. When the top-3 retrieved chunks did not cover all four bucket levels, the model would fill in missing percentages from training data rather than declining. The fix was strengthening the system prompt instruction: *"If the context does not contain sufficient information, say exactly: 'This information is not available in my knowledge base.' Do not speculate, infer, or extrapolate beyond what the documents state."*

**Numeric precision questions.** Questions asking for exact rupee figures or percentages were prone to off-by-one or rounded hallucinations when the model paraphrased instead of quoting. For example, a NACH bounce penalty of "₹500 + 18% GST" was occasionally rendered as "approximately ₹600." The hallucination judge was calibrated to flag these via the instruction that arithmetic derivable from stated numbers is not a hallucination, but invented numbers that do not appear in the context are. This kept the judge from over-flagging valid range-classification responses while still catching genuine fabrications.

---

## What Would I Do Differently at 10x Scale (50 Documents, 200 Questions)

**Chunking strategy.** At 50 documents, manual paragraph-aware chunking becomes unreliable because document structure varies widely — a pricing sheet formatted as a Markdown table needs different chunking than a narrative SOP. I would add a structure-detection layer: detect headers, tables, and bullet lists, and chunk at structural boundaries rather than just `\n\n`. For tables, each row would become its own chunk with the header row prepended as metadata, so retrieval can match individual cells rather than entire tables.

**Retrieval.** The current pipeline uses cosine similarity on `all-MiniLM-L6-v2` embeddings. At 10x scale, two limitations appear. First, MiniLM's 384-dimension embeddings compress semantic content aggressively — longer, denser policy paragraphs lose nuance. A larger model (e.g. `all-mpnet-base-v2` at 768 dimensions, or Anthropic's text-embedding-3 model) would improve retrieval precision on dense regulatory text. Second, pure semantic search misses exact keyword matches: a query for "NACH dishonour penalty" should always retrieve the chunk containing exactly those words, even if the embedding distance is not the smallest. Hybrid retrieval (BM25 + semantic, re-ranked by reciprocal rank fusion) would address this.

**Hallucination detection.** The current judge makes one LLM call per response. At 200 questions that is 200 sequential judge calls, taking 30–40 minutes. At scale, the judge would run asynchronously in a separate worker — the pipeline returns the response to the user immediately and the hallucination score is written to the audit log within a few seconds. If the judge flags a claim, a human review ticket is raised automatically rather than blocking the user.

**Multi-tenant isolation.** The current ChromaDB implementation uses one collection per client with a `voiz_{client_id}` namespace prefix. At 10x scale (say 20 enterprise clients), this works but ChromaDB's in-process architecture becomes a bottleneck under concurrent load. The production architecture would move to a hosted vector DB (Supabase pgvector or Pinecone) with row-level tenant isolation enforced by a policy layer, not just naming convention. Each query would carry a JWT-encoded client ID verified before the retrieval call — making cross-tenant access architecturally impossible rather than just organisationally prevented.