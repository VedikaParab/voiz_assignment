"""
a2_guardrails/handlers.py
Deterministic handler registry — one pure function per guardrail category.

Rules (from assignment spec):
  - No LLM calls. Ever.
  - No I/O. Pure functions.
  - Must return in < 1ms.
  - Responses must be empathetic and appropriate to the category.
  - Handler registry maps category string → callable.

Usage:
    from a2_guardrails.handlers import get_handler_response
    response = get_handler_response("SAFETY")
"""

from __future__ import annotations


# ── Individual handler functions ───────────────────────────────────────

def handle_adversarial_jailbreak() -> str:
    return (
        "I'm here to assist you with your account today and I need to stay "
        "focused on that. I'm not able to change how I operate or take on a "
        "different role. If you have questions about your account or payment "
        "options, I'm happy to help with those right now."
    )


def handle_safety() -> str:
    return (
        "I'm very concerned about what you've shared, and I want you to know "
        "that you matter. Please reach out to iCall right now — they're "
        "available at 9152987821 and offer free, confidential support. "
        "Your account can wait — please take care of yourself first."
    )


def handle_legal_threat() -> str:
    return (
        "I understand you're considering legal options, and that is absolutely "
        "your right. I'm going to pause this call and escalate your account to "
        "our compliance team, who are best placed to respond to legal matters. "
        "You will receive written communication from us within two business days."
    )


def handle_privacy_pii() -> str:
    return (
        "For your security, please don't share sensitive personal information "
        "like Aadhaar, PAN, or card numbers on this call. We never need your "
        "full card details verbally. If you'd like to make a payment, I can "
        "send you a secure payment link instead."
    )


def handle_authority_breach() -> str:
    return (
        "Thank you for letting me know. If you're acting in an official "
        "capacity or have a regulatory matter, please submit your credentials "
        "and notice in writing to our compliance team at compliance@predixion.ai. "
        "I'm not in a position to act on verbal authority claims during this call."
    )


def handle_financial_hardship() -> str:
    return (
        "Thank you for being open with me — I genuinely understand this is a "
        "difficult time. You may be eligible for our hardship programme, which "
        "includes reduced instalments or a temporary payment pause. Let me "
        "transfer you to our hardship support team who can look at your "
        "specific situation and find the best option for you."
    )


def handle_scope_topic() -> str:
    return (
        "I appreciate the chat, but I'm only able to assist with your account "
        "and payment-related questions today. Shall we get back to sorting out "
        "your account so we can get this resolved for you quickly?"
    )


def handle_unknown() -> str:
    """Fallback for any category not in the registry."""
    return (
        "I want to make sure I handle your concern correctly. Let me transfer "
        "you to the right team who can assist you with this."
    )


# ── Handler registry ───────────────────────────────────────────────────
# Maps category label (matches pass1_regex and pass2_llm categories) → handler fn

_REGISTRY: dict[str, callable] = {
    "ADVERSARIAL_JAILBREAK": handle_adversarial_jailbreak,
    "SAFETY":                handle_safety,
    "LEGAL_THREAT":          handle_legal_threat,
    "PRIVACY_PII":           handle_privacy_pii,
    "AUTHORITY_BREACH":      handle_authority_breach,
    "FINANCIAL_HARDSHIP":    handle_financial_hardship,
    "SCOPE_TOPIC":           handle_scope_topic,
}


def get_handler_response(category: str) -> str:
    """
    Look up and call the handler for the given category.

    Args:
        category: One of the 7 guardrail category labels.

    Returns:
        Pre-approved safe response string.
    """
    handler = _REGISTRY.get(category, handle_unknown)
    return handler()


def list_categories() -> list[str]:
    """Return all registered category labels."""
    return list(_REGISTRY.keys())