"""Token counting and context-budget helpers.

Groq's gpt-oss models are limited to a small per-minute token budget. Every
LLM prompt in this project is assembled from explicitly bounded pieces so that
retrieved passages, case context, and chat history cannot grow without limit.
Full documents and the complete conversation remain stored in the case
session; only compact, relevant extracts are sent to the model.
"""

from __future__ import annotations

import math
import os
import re
from typing import Any, Iterable, List, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

try:
    import tiktoken

    _ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - tiktoken is optional at runtime
    _ENCODER = None


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


CHARS_PER_TOKEN = _env_float("CHARS_PER_TOKEN_ESTIMATE", 4.0, 2.0)

# Conservative defaults: ~3.6k input + ~1.2k completion = 4.8k tokens per
# legal-chat request, well below Groq's 8k TPM ceiling. Override in .env.
MAX_INPUT_TOKENS = _env_int("MAX_INPUT_TOKENS", 3600, 800)
MAX_OUTPUT_TOKENS = _env_int("MAX_OUTPUT_TOKENS", 1200, 200)
HISTORY_TOKEN_BUDGET = _env_int("HISTORY_TOKEN_BUDGET", 650, 100)
CASE_CONTEXT_TOKEN_BUDGET = _env_int("CASE_CONTEXT_TOKEN_BUDGET", 900, 120)
RETRIEVAL_TOKEN_BUDGET = _env_int("RETRIEVAL_TOKEN_BUDGET", 1500, 150)
RESOLVE_INPUT_TOKEN_BUDGET = _env_int("RESOLVE_INPUT_TOKEN_BUDGET", 1100, 300)
RESOLVE_OUTPUT_TOKENS = _env_int("RESOLVE_OUTPUT_TOKENS", 100, 30)
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
GENERATION_CONTEXT_TOKEN_BUDGET = _env_int("GENERATION_CONTEXT_TOKEN_BUDGET", 500, 150)
GENERATION_KNOWN_FACTS_TOKEN_BUDGET = _env_int("GENERATION_KNOWN_FACTS_TOKEN_BUDGET", 450, 100)
GENERATION_EXTRACTION_OUTPUT_TOKENS = _env_int("GENERATION_EXTRACTION_OUTPUT_TOKENS", 700, 200)
MAX_PASSAGE_CHARS = _env_int("MAX_CHARS_PER_PASSAGE", 1200, 200)
MAX_TOTAL_RETRIEVAL_CHARS = _env_int("MAX_TOTAL_RETRIEVAL_CHARS", 6000, 500)
MAX_HISTORY_TURNS = _env_int("MAX_HISTORY_TURNS", 3, 1)
MAX_HISTORY_MESSAGE_CHARS = _env_int("MAX_HISTORY_MESSAGE_CHARS", 600, 100)
MAX_QUESTION_CHARS = _env_int("MAX_QUESTION_CHARS", 1800, 200)
MAX_GENERATION_ANSWER_CHARS = _env_int("MAX_GENERATION_ANSWER_CHARS", 500, 60)


def count_tokens(text: Any) -> int:
    """Return a token count for text (tiktoken when available, else estimate)."""
    value = "" if text is None else str(text)
    if not value:
        return 0
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(value, disallowed_special=()))
        except Exception:
            pass
    return max(1, int(math.ceil(len(value) / CHARS_PER_TOKEN)))


def count_message_tokens(messages: Sequence[BaseMessage]) -> int:
    """Approximate token count of a chat message list, including small overheads."""
    total = 0
    for message in messages:
        total += count_tokens(getattr(message, "content", "")) + 4
    return total


def _sentence_boundary(text: str) -> int:
    candidates = [
        text.rfind(". "),
        text.rfind(".\n"),
        text.rfind("? "),
        text.rfind("! "),
        text.rfind("\n\n"),
        text.rfind("\n"),
    ]
    return max(candidates)


def truncate_chars(text: Any, max_chars: int, suffix: str = "…") -> str:
    """Trim text near a sentence boundary without exceeding max_chars."""
    value = "" if text is None else str(text).strip()
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value

    room = max(0, max_chars - len(suffix))
    cut = value[:room]
    boundary = _sentence_boundary(cut)
    if boundary >= int(room * 0.6):
        cut = cut[: boundary + 1]
    return cut.rstrip() + suffix


def truncate_to_tokens(text: Any, max_tokens: int, suffix: str = " …[trimmed]") -> str:
    """Trim text to a token budget, preferring a sentence/line boundary."""
    value = "" if text is None else str(text).strip()
    if max_tokens <= 0:
        return ""
    if count_tokens(value) <= max_tokens:
        return value

    suffix_tokens = count_tokens(suffix)
    target = max(1, max_tokens - suffix_tokens)

    if _ENCODER is not None:
        try:
            tokens = _ENCODER.encode(value, disallowed_special=())
            cut = _ENCODER.decode(tokens[:target])
        except Exception:
            cut = value[: int(target * CHARS_PER_TOKEN)]
    else:
        cut = value[: int(target * CHARS_PER_TOKEN)]

    # Guard against tokenizer/char estimate drift.
    while cut and count_tokens(cut + suffix) > max_tokens:
        cut = cut[: max(0, int(len(cut) * 0.9))]

    boundary = _sentence_boundary(cut)
    if boundary >= int(len(cut) * 0.55):
        cut = cut[: boundary + 1]
    return cut.rstrip() + suffix


def bounded_text(text: Any, max_tokens: int, max_chars: Optional[int] = None) -> str:
    """Apply a character cap and then a token cap."""
    result = "" if text is None else str(text).strip()
    if max_chars:
        result = truncate_chars(result, max_chars)
    return truncate_to_tokens(result, max_tokens)


def build_bounded_history(
    history: Sequence[BaseMessage],
    max_tokens: int = HISTORY_TOKEN_BUDGET,
    max_turns: int = MAX_HISTORY_TURNS,
    max_message_chars: int = MAX_HISTORY_MESSAGE_CHARS,
) -> List[BaseMessage]:
    """Select the newest few history messages, trimming long messages.

    The full history is never modified. Old/long turns stop consuming the
    prompt budget, but remain available in the case session.
    """
    candidates = [
        message
        for message in list(history)[-max_turns * 2 :]
        if isinstance(message, (HumanMessage, AIMessage))
    ]
    chosen: List[BaseMessage] = []
    remaining = max_tokens

    for message in reversed(candidates):
        if remaining < 40:
            break
        content = truncate_chars(str(message.content or ""), max_message_chars)
        message_tokens = count_tokens(content) + 4
        if message_tokens > remaining:
            content = truncate_to_tokens(content, max(30, remaining - 4))
            message_tokens = count_tokens(content) + 4
            if message_tokens > remaining:
                break
        clone = (
            HumanMessage(content=content)
            if isinstance(message, HumanMessage)
            else AIMessage(content=content)
        )
        chosen.append(clone)
        remaining -= message_tokens

    chosen.reverse()
    return chosen


def history_as_text(
    history: Sequence[BaseMessage],
    max_tokens: int = 350,
    max_turns: int = 2,
    max_message_chars: int = 280,
) -> str:
    selected = build_bounded_history(
        history,
        max_tokens=max_tokens,
        max_turns=max_turns,
        max_message_chars=max_message_chars,
    )
    lines = []
    for message in selected:
        role = "User" if isinstance(message, HumanMessage) else "Assistant"
        lines.append(f"{role}: {message.content}")
    return "\n".join(lines)


def fit_sections(sections: Sequence[tuple[str, str]], max_tokens: int) -> str:
    """Join text sections while limiting the total token count.

    Each section is trimmed so that later (higher-priority) sections still
    fit. Pass the most important section first.
    """
    if not sections or max_tokens <= 0:
        return ""
    remaining = max_tokens
    output: List[str] = []
    for heading, body in sections:
        if remaining <= 10:
            break
        content = truncate_to_tokens(body, remaining)
        block = f"{heading}\n{content}" if heading else content
        block_tokens = count_tokens(block) + 2
        if block_tokens > remaining:
            block = truncate_to_tokens(block, remaining)
            block_tokens = count_tokens(block)
        if block_tokens <= 0:
            continue
        output.append(block)
        remaining -= block_tokens
    return "\n\n".join(output)


def compact_lines(pairs: Iterable[tuple[str, Any]], max_chars_per_value: int = 220) -> str:
    lines = []
    for label, value in pairs:
        if value is None or not str(value).strip():
            continue
        lines.append(f"- {label}: {truncate_chars(value, max_chars_per_value)}")
    return "\n".join(lines)


def budget_report(**parts: Any) -> dict:
    return {key: int(value) for key, value in parts.items()}
