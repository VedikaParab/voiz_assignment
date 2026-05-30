"""
generator.py — VOIZ A3 RAG Pipeline
Generate 5 synthetic knowledge-base docs using Groq via config.chat().
Saves to a3_rag/docs/ — skip if files already exist.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import chat

DOCS_DIR = Path(__file__).parent / "docs"

DOCUMENTS = [
    {
        "filename": "01_collections_policy.txt",
        "prompt": """Write a realistic 600-word collections policy document for VOIZ KOLLECT,
a B2B debt collections platform serving Indian NBFCs and banks.
Include: DPD bucket definitions (0-30, 31-60, 61-90, 90+ DPD), settlement guidelines
with specific percentages per bucket, escalation rules, agent conduct rules
(RBI Fair Practice Code), and payment plan eligibility criteria.
Write in formal policy language with specific numbers.""",
    },
    {
        "filename": "02_product_faq.txt",
        "prompt": """Write a product FAQ with exactly 20 Q&A pairs for VOIZ, an AI voice agent platform.
Cover: what VOIZ does, supported languages (Hindi/English/regional), integrations
(API/Twilio/Exotel), pricing tiers (Starter ₹15,000/mo, Growth ₹35,000/mo, Enterprise custom),
SOC2/RBI compliance, onboarding timeline (2-4 weeks), KOLLECT/LEADX/AGENTX products.
Format as Q: ... / A: ... pairs.""",
    },
    {
        "filename": "03_complaince_sop.txt",
        "prompt": """Write a 600-word compliance SOP for VOIZ agents making outbound collection calls in India.
Include numbered steps for: pre-call checks (DNC registry, calling hours 8am-7pm),
borrower verification (name, DOB, last 4 account digits), mandatory disclosures
(agent name, company, recording notice), handling disputes (48-hour escalation),
prohibited phrases, and post-call documentation. Use clear numbered sub-steps.""",
    },
    {
        "filename": "04_pricing_sheet.txt",
        "prompt": """Write a pricing sheet for VOIZ platform (Predixion AI) with 3 tiers: Starter, Growth, Enterprise.
Include specific INR pricing, features per tier (agent minutes, concurrent calls, integrations),
add-on pricing (extra minutes, WhatsApp, custom voice), implementation fees, SLA terms,
volume discount table (>10k and >50k calls/month), and payment terms (monthly/annual, 15% annual discount).""",
    },
    {
        "filename": "05_communication_scripts.txt",
        "prompt": """Write borrower communication scripts for VOIZ KOLLECT for these 5 scenarios:
1. First contact call, 2. Negotiating a payment plan, 3. Handling "I already paid" dispute,
4. Handling hardship (medical/job loss), 5. Final notice before legal escalation.
Each script needs: Opening, objection handling, Close. Include sample borrower responses
and agent rebuttals. Write realistic dialogue.""",
    },
]


def generate_documents() -> None:
    """Generate all 5 synthetic docs and save to docs/ directory."""
    DOCS_DIR.mkdir(exist_ok=True)

    for doc in DOCUMENTS:
        out_path = DOCS_DIR / doc["filename"]
        if out_path.exists() and out_path.stat().st_size > 100:
            print(f"  ✓ {doc['filename']} already exists — skipping")
            continue

        print(f"  Generating {doc['filename']} ...", end="", flush=True)
        text = chat(
            system="You are a professional business document writer. Write exactly what is requested.",
            messages=[{"role": "user", "content": doc["prompt"]}],
            max_tokens=1500,
            temperature=0.4,
        )
        out_path.write_text(text, encoding="utf-8")
        print(f" ✓ ({len(text)} chars)")

    print(f"\nAll documents saved to {DOCS_DIR}/")


if __name__ == "__main__":
    print("=== VOIZ RAG — Generating Synthetic Documents ===")
    generate_documents()