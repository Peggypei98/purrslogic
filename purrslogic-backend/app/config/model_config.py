"""
Centralized Gemini / ADK tuning for triage latency and decision quality.
Override via environment variables where noted.
"""

import os

from google.genai import types

TRIAGE_MODEL = os.getenv("PURRSLOGIC_TRIAGE_MODEL", "gemini-2.5-flash")

# Lower temperature → more deterministic tool picks and guardrail compliance.
TEMPERATURE = float(os.getenv("PURRSLOGIC_TEMPERATURE", "0.1"))
TOP_P = float(os.getenv("PURRSLOGIC_TOP_P", "0.9"))

# Disable internal thinking on balanced days (faster); allow budget on overload triage.
THINKING_BUDGET_BALANCED = int(os.getenv("PURRSLOGIC_THINKING_BUDGET_BALANCED", "0"))
THINKING_BUDGET_OVERLOAD = int(os.getenv("PURRSLOGIC_THINKING_BUDGET_OVERLOAD", "1024"))

MAX_OUTPUT_TOKENS_BALANCED = int(os.getenv("PURRSLOGIC_MAX_OUTPUT_BALANCED", "1024"))
MAX_OUTPUT_TOKENS_OVERLOAD = int(os.getenv("PURRSLOGIC_MAX_OUTPUT_OVERLOAD", "2048"))

PHOENIX_PREFETCH_LIMIT = int(os.getenv("PURRSLOGIC_PHOENIX_LIMIT", "3"))
RAG_PREFETCH_LIMIT = int(os.getenv("PURRSLOGIC_RAG_LIMIT", "2"))
VECTOR_NUM_CANDIDATES_MULTIPLIER = int(os.getenv("PURRSLOGIC_VECTOR_CANDIDATES_MULT", "3"))


def build_generate_content_config(is_overloaded: bool) -> types.GenerateContentConfig:
    """Build Gemini generation config tuned for speed vs overload triage depth."""
    return types.GenerateContentConfig(
        temperature=TEMPERATURE,
        top_p=TOP_P,
        max_output_tokens=(
            MAX_OUTPUT_TOKENS_OVERLOAD if is_overloaded else MAX_OUTPUT_TOKENS_BALANCED
        ),
        thinking_config=types.ThinkingConfig(
            thinking_budget=(
                THINKING_BUDGET_OVERLOAD if is_overloaded else THINKING_BUDGET_BALANCED
            ),
        ),
    )


def performance_profile() -> dict:
    """Expose active tuning knobs for /api/v1/adk/status and debugging."""
    return {
        "model": TRIAGE_MODEL,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "thinking_budget_balanced": THINKING_BUDGET_BALANCED,
        "thinking_budget_overload": THINKING_BUDGET_OVERLOAD,
        "max_output_tokens_balanced": MAX_OUTPUT_TOKENS_BALANCED,
        "max_output_tokens_overload": MAX_OUTPUT_TOKENS_OVERLOAD,
        "phoenix_prefetch_limit": PHOENIX_PREFETCH_LIMIT,
        "rag_prefetch_limit": RAG_PREFETCH_LIMIT,
        "vector_num_candidates_multiplier": VECTOR_NUM_CANDIDATES_MULTIPLIER,
    }
