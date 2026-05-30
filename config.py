"""
voiz/config.py  —  shared config imported by ALL 4 assignments.

Groq SDK usage:
  from config import chat, client, MODEL
  reply = chat(system="...", messages=[...])
"""

import os
import logging
import pathlib
from groq import Groq
from dotenv import load_dotenv

load_dotenv()  # reads .env from project root

# ── API setup ──────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
if not GROQ_API_KEY:
    raise EnvironmentError("GROQ_API_KEY not set. Add it to your .env file.")

# Best free Groq model for reasoning tasks — fast + capable
MODEL = "llama-3.3-70b-versatile"

# Single shared client — import this in every module
client = Groq(api_key=GROQ_API_KEY)


# ── Shared chat wrapper ────────────────────────────────────────────────
def chat(
    system: str,
    messages: list[dict],
    max_tokens: int = 512,
    temperature: float = 0.3,
    model: str = MODEL,
) -> str:
    """
    Thin wrapper around Groq chat completions.
    All 4 assignments call this — never call client.chat directly.

    Args:
        system:      System prompt string (state block + agent instructions).
        messages:    List of {"role": "user"/"assistant", "content": "..."}.
        max_tokens:  Cap on response length.
        temperature: Lower = more deterministic (good for classifiers).
        model:       Override per call if needed.

    Returns:
        Plain string response from the model.
    """
    response = client.chat.completions.create(
        model       = model,
        max_tokens  = max_tokens,
        temperature = temperature,
        messages    = [{"role": "system", "content": system}] + messages,
    )
    return response.choices[0].message.content.strip()


# ── Shared logger setup ────────────────────────────────────────────────
LOG_DIR = pathlib.Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def get_logger(name: str, log_file: str) -> logging.Logger:
    """
    Returns a logger that writes structured lines to both console and a .jsonl file.
    Idempotent — safe to call multiple times with the same name.

    Usage:  logger = get_logger("a1", "voiz_a1.jsonl")
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    # File handler — always UTF-8 so arrow chars etc. never crash on Windows
    fh = logging.FileHandler(LOG_DIR / log_file, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger