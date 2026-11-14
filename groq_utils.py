"""Shared Groq client creation, usage logging, and error classification."""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv(".env")

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low").strip().lower()
LLM_RETRY_WAIT_SECONDS = float(os.getenv("LLM_RETRY_WAIT_SECONDS", "8"))

_BRACKETED_HOST = re.compile(r"\[([^\[\]]+)\]")


def _normalize_no_proxy() -> None:
    """httpx, which the Groq SDK builds on, parses NO_PROXY entries as URLs, so a
    bracketed IPv6 literal such as "[::1]" aborts every client with InvalidURL."""
    for name in ("NO_PROXY", "no_proxy"):
        value = os.getenv(name)
        if value and "[" in value:
            os.environ[name] = _BRACKETED_HOST.sub(r"\1", value)


_normalize_no_proxy()

_clients: Dict[tuple, ChatGroq] = {}
_client_lock = threading.Lock()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def get_groq_llm(
    *,
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
) -> ChatGroq:
    """Return a cached ChatGroq client for the given options."""
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it to the .env file and restart the server."
        )
    resolved_model = model or GROQ_MODEL
    key = (resolved_model, round(float(temperature), 2), max_tokens)
    with _client_lock:
        if key in _clients:
            return _clients[key]
        kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "temperature": temperature,
            "max_retries": 1,
            "request_timeout": _env_float("GROQ_REQUEST_TIMEOUT", 120.0),
        }
        if max_tokens:
            kwargs["max_tokens"] = int(max_tokens)
        if GROQ_REASONING_EFFORT in {"low", "medium", "high"}:
            kwargs["reasoning_effort"] = GROQ_REASONING_EFFORT
        client = ChatGroq(**kwargs)
        _clients[key] = client
        return client


def log_usage(label: str, response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage_metadata", None) or {}
    usage = dict(usage) if isinstance(usage, dict) else {}
    details = usage.get("output_token_details") or {}
    reasoning = details.get("reasoning") if isinstance(details, dict) else None
    print(
        "[LLM] "
        f"{label}: input={usage.get('input_tokens', '?')} "
        f"output={usage.get('output_tokens', '?')} "
        f"reasoning={reasoning if reasoning is not None else '?'} "
        f"total={usage.get('total_tokens', '?')}",
        flush=True,
    )
    return usage


def _status_code(exc: BaseException) -> Optional[int]:
    code = getattr(exc, "status_code", None)
    if code is None:
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _message(exc: BaseException) -> str:
    return str(exc).lower()


def is_rate_limit_error(exc: BaseException) -> bool:
    status = _status_code(exc)
    message = _message(exc)
    return status == 429 or any(
        marker in message
        for marker in (
            "rate limit",
            "rate_limit",
            "tokens per minute",
            "token per minute",
            "tpm",
            "too many requests",
        )
    )


def is_token_limit_error(exc: BaseException) -> bool:
    status = _status_code(exc)
    message = _message(exc)
    if is_rate_limit_error(exc):
        return True
    token_markers = (
        "request too large",
        "reduce the length",
        "context length",
        "context_length_exceeded",
        "maximum context",
        "too many tokens",
        "token limit",
        "input too large",
        "requested too many",
        "tokens in the request",
        "payload too large",
    )
    if any(marker in message for marker in token_markers):
        return True
    return status == 413


def is_retryable_llm_error(exc: BaseException) -> bool:
    return is_rate_limit_error(exc) or is_token_limit_error(exc)


def retry_wait_seconds(exc: BaseException) -> float:
    if is_rate_limit_error(exc):
        return max(2.0, _env_float("LLM_RETRY_WAIT_SECONDS", LLM_RETRY_WAIT_SECONDS))
    return 0.0


def friendly_llm_error(exc: BaseException, *, context: str = "answer") -> str:
    if is_rate_limit_error(exc):
        return (
            "The language model is temporarily rate-limited (Groq's token-per-minute "
            "limit). Your case data is safe. Please wait a few seconds and retry."
        )
    if is_token_limit_error(exc):
        if context == "analysis":
            return (
                "This document is too large for a single analysis request. "
                "Try a shorter document."
            )
        return (
            "The language model rejected the request as too large. The app has "
            "trimmed the context; please retry. If it persists, ask a narrower question."
        )
    print(f"[LLM] {context} error: {type(exc).__name__}: {exc}", flush=True)
    return (
        "The language model request failed. Check the server terminal, your "
        "GROQ_API_KEY, and the configured GROQ_MODEL, then retry."
    )


def invoke_llm(
    llm: Any,
    payload: Any,
    *,
    label: str,
    retry_on_rate_limit: bool = True,
) -> Any:
    """Invoke a bounded prompt, retrying once after a 429/TPM error."""
    attempts = 2 if retry_on_rate_limit else 1
    for attempt in range(1, attempts + 1):
        try:
            response = llm.invoke(payload)
            log_usage(label, response)
            return response
        except Exception as exc:
            if attempt < attempts and is_rate_limit_error(exc):
                wait = retry_wait_seconds(exc)
                print(
                    f"[LLM] {label}: rate-limited, retrying in {wait:.1f}s",
                    flush=True,
                )
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("LLM invocation failed without an exception.")


def usage_summary(usage: Optional[Dict[str, Any]]) -> str:
    if not usage:
        return ""
    input_tokens = usage.get("input_tokens", "?")
    output_tokens = usage.get("output_tokens", "?")
    total = usage.get("total_tokens", "?")
    return f"input={input_tokens}, output={output_tokens}, total={total}"
