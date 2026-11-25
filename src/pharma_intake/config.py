"""Single source of configuration constants."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
SOP_DIR = DATA_DIR / "sops"
# PHARMA_DB_PATH lets tests/demos point at a throwaway database.
DB_PATH = Path(os.environ.get("PHARMA_DB_PATH", DATA_DIR / "intake.db"))

# Domain formats
LOT_PATTERN = r"^LOT-[0-9]{5}$"  # ASCII digits only
REF_PREFIX = "REF"

def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides real env vars."""
    path = path or ROOT_DIR / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"


def openrouter_settings() -> tuple[str, str]:
    """(api_key, model), read at call time so tests can override the environment."""
    return (
        os.environ.get("OPENROUTER_API_KEY", "").strip(),
        os.environ.get("OPENROUTER_MODEL", "").strip() or OPENROUTER_DEFAULT_MODEL,
    )


# Workflow
STATUSES = ("New", "In Review", "Closed")
REPORT_TYPES = ("Suspected Adverse Event", "Product Quality Complaint")

# Hybrid RAG parameters
BM25_K1 = 1.3
BM25_B = 0.75
CHUNK_TOKENS = 512
CHUNK_OVERLAP = 64
RETRIEVER_TOP_N = 50
RRF_K = 60
RERANK_THRESHOLD = 0.40
CONTEXT_MIN_CHUNKS = 3
CONTEXT_MAX_CHUNKS = 5

# Agent control plane
CIRCUIT_BREAKER_MAX_INVALID = 2  # halt when consecutive invalid calls exceed this

SYNTHETIC_BANNER = (
    "Training prototype: synthetic, fictional data only. Do not enter real patient "
    "or personal information. This tool does not assess causality, advise on "
    "treatment, or determine regulatory reportability."
)
