"""Legal RAG agent for Pakistani criminal law.

The full case history, documents, and reports live in the shared session.
Each model request (Ollama or Groq) receives only:
- a few recent, length-limited conversation turns,
- compact case facts/summaries plus lexically relevant excerpts,
- a deduplicated, length-limited set of retrieved authorities.

Prompts are trimmed to a token budget and retried with tighter budgets when
the model reports a context-size error. Retrieval, prompts, history and
citations are identical for both providers; only the chat call differs.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Transformers otherwise probes for an unused TensorFlow install, adding about a
# minute to the first embedding load.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

import torch
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from ollama import chat as ollama_chat

import hybrid_retrieval
import pakistancode_web
from case_context import build_case_context, build_precedent_context
from law_index_store import build_law_store
from context_budget import (
    CASE_CONTEXT_TOKEN_BUDGET,
    EARLY_MEMORY_TOKEN_BUDGET,
    HISTORY_TOKEN_BUDGET,
    MAX_EARLY_MEMORY_CHARS,
    MAX_HISTORY_MESSAGE_CHARS,
    MAX_HISTORY_TURNS,
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    MAX_PASSAGE_CHARS,
    MAX_QUESTION_CHARS,
    MAX_TOTAL_RETRIEVAL_CHARS,
    RESOLVE_INPUT_TOKEN_BUDGET,
    RESOLVE_OUTPUT_TOKENS,
    RETRIEVAL_TOKEN_BUDGET,
    build_bounded_history,
    build_early_memory,
    count_message_tokens,
    count_tokens,
    history_as_text,
    truncate_chars,
    truncate_to_tokens,
)
from groq_utils import (
    GROQ_MODEL,
    friendly_llm_error,
    get_groq_llm,
    invoke_llm,
    is_token_limit_error,
)
from session_manager import session_manager

load_dotenv(".env")

BASE_DIR = Path(__file__).resolve().parent
CASES_INDEX_PATH = os.getenv("CASES_INDEX_PATH", str(BASE_DIR / "faiss_index_cases"))
LAW_INDEX_PATH = os.getenv("LAW_INDEX_PATH", str(BASE_DIR / "faiss_index_law"))
JUDGMENTS_INDEX_PATH = os.getenv("JUDGMENTS_INDEX_PATH", str(BASE_DIR / "judgments_faiss_index"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")

PROVIDER_OLLAMA = "ollama"
PROVIDER_GROQ = "groq"
LEGAL_PROVIDERS = (PROVIDER_OLLAMA, PROVIDER_GROQ)


def normalize_provider(value: Optional[str] = None) -> str:
    """Resolve a requested provider, falling back to the configured default."""
    candidate = (value or "").strip().lower()
    if candidate in LEGAL_PROVIDERS:
        return candidate
    configured = os.getenv("LEGAL_LLM_PROVIDER", PROVIDER_OLLAMA).strip().lower()
    return configured if configured in LEGAL_PROVIDERS else PROVIDER_OLLAMA


DEFAULT_LLM_PROVIDER = normalize_provider()


def provider_model(provider: str) -> str:
    return GROQ_MODEL if provider == PROVIDER_GROQ else OLLAMA_MODEL


def provider_label(provider: str) -> str:
    return "Groq" if provider == PROVIDER_GROQ else "Ollama"

# The two retrievers share one embedding model; both indexes are 768-dim
# bge-base vectors, so scores stay comparable across sources.
KIND_LAW = "law"
KIND_CASES = "cases"
RETRIEVER_KINDS = (KIND_LAW, KIND_CASES)
INDEX_PATHS = {
    KIND_LAW: LAW_INDEX_PATH,
    KIND_CASES: CASES_INDEX_PATH,
}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


TOP_K = _env_int("TOP_K", 4)
# Judgment candidates are over-fetched because identical statutory pages and
# repeated headnotes are dropped before the passages reach the model.
TOP_K_CASES = _env_int("TOP_K_CASES", 8)
TOP_K_LAW = _env_int("TOP_K_LAW", 5)
MAX_EVIDENCE_CASES = _env_int("MAX_EVIDENCE_CASES", 6)
MAX_EVIDENCE_LAW = _env_int("MAX_EVIDENCE_LAW", TOP_K_LAW)
# Statute passages and judgment passages share the same overall retrieval
# budget, so adding a second index cannot grow the prompt past MAX_INPUT_TOKENS.
LAW_RETRIEVAL_SHARE = _env_float("LAW_RETRIEVAL_SHARE", 0.4, 0.2, 0.8)
MAX_CHARS_PER_DOCUMENT = _env_int("MAX_CHARS_PER_DOCUMENT", MAX_PASSAGE_CHARS)
MAX_RETRIEVAL_CHARS = _env_int("MAX_TOTAL_RETRIEVAL_CHARS", MAX_TOTAL_RETRIEVAL_CHARS)

# Multi-part questions: each part gets its own sub-query against both indexes.
MAX_FACETS = _env_int("MAX_FACETS", 3)
FACET_TOP_K_LAW = _env_int("FACET_TOP_K_LAW", 3)
FACET_TOP_K_CASES = _env_int("FACET_TOP_K_CASES", 2)
# A part counts as supported when a kept passage shares this many of its terms.
FACET_MIN_TERM_MATCHES = _env_int("FACET_MIN_TERM_MATCHES", 2)
DECOMPOSE_OUTPUT_TOKENS = _env_int("DECOMPOSE_OUTPUT_TOKENS", 260, 60)
# Rough allowance for each passage's [SOURCE-n ...] header inside the char budget.
LABEL_OVERHEAD_CHARS = 120


_embeddings = None
_init_lock = threading.Lock()

_stores: Dict[str, Any] = {KIND_LAW: None, KIND_CASES: None}
_load_attempted: Dict[str, bool] = {KIND_LAW: False, KIND_CASES: False}
_store_status: Dict[str, Dict[str, Any]] = {
    kind: {
        "state": "pending",
        "path": INDEX_PATHS[kind],
        "vectors": 0,
        "error": None,
        "last_query_error": None,
    }
    for kind in RETRIEVER_KINDS
}


def get_device() -> str:
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        device = get_device()
        print(f"Loading embedding model '{EMBEDDING_MODEL}' on '{device}'...", flush=True)
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True, "batch_size": 16},
        )
        print("Embedding model ready.", flush=True)
    return _embeddings


def _load_faiss(path: str):
    return FAISS.load_local(path, get_embeddings(), allow_dangerous_deserialization=True)


def _candidate_paths(kind: str) -> List[str]:
    if kind == KIND_CASES:
        return [CASES_INDEX_PATH, JUDGMENTS_INDEX_PATH]
    return [LAW_INDEX_PATH]


def get_store(kind: str) -> Optional[Any]:
    """Lazily load one FAISS index; never rebuilds or writes either index."""
    if kind not in _stores:
        return None
    if _stores[kind] is not None:
        return _stores[kind]

    status = _store_status[kind]
    with _init_lock:
        if _stores[kind] is not None:
            return _stores[kind]
        if _load_attempted[kind]:
            return None
        _load_attempted[kind] = True

        paths = _candidate_paths(kind)
        available = [p for p in paths if os.path.exists(p)]
        if not available:
            status.update(
                {"state": "missing", "path": paths[0], "vectors": 0, "error": None}
            )
            print(
                f"Notice: no {kind} FAISS index found at {', '.join(paths)}. "
                f"Answers will be produced without {kind} retrieved sources.",
                flush=True,
            )
            return None

        path = available[0]
        try:
            print(f"Loading {kind} FAISS index from '{path}'...", flush=True)
            store = build_law_store(path) if kind == KIND_LAW else _load_faiss(path)
            _stores[kind] = store
            status.update(
                {"state": "ready", "path": path, "vectors": int(store.index.ntotal), "error": None}
            )
            print(
                f"{kind.title()} FAISS index ready ({store.index.ntotal:,} vectors).",
                flush=True,
            )
            return store
        except Exception as exc:
            status.update(
                {
                    "state": "error",
                    "path": path,
                    "vectors": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"Notice: could not load {kind} FAISS index: {exc}", flush=True)
            return None


def get_vector_store() -> Optional[Any]:
    """Backward-compatible accessor for the case-law (judgments) index."""
    return get_store(KIND_CASES)


def retrieval_status() -> Dict[str, Any]:
    """Load state per retriever, so a dead index is reported instead of ignored."""
    return {
        kind: {
            "state": _store_status[kind]["state"],
            "path": _store_status[kind]["path"],
            "vectors": _store_status[kind]["vectors"],
            "error": _store_status[kind]["error"],
            "last_query_error": _store_status[kind]["last_query_error"],
        }
        for kind in RETRIEVER_KINDS
    }


def _ollama_messages(payload: Any) -> List[Dict[str, str]]:
    if isinstance(payload, str):
        return [{"role": "user", "content": payload}]

    role_names = {"system": "system", "human": "user", "ai": "assistant"}
    messages = []
    for message in payload:
        message_type = getattr(message, "type", None)
        role = role_names.get(message_type)
        if role is None:
            raise TypeError(f"Unsupported Ollama message type: {message_type!r}")
        messages.append({"role": role, "content": str(message.content)})
    return messages


def _ollama_content(response: Any) -> str:
    message = getattr(response, "message", None)
    return str(getattr(message, "content", "") or "")


def _ollama_usage(response: Any) -> Dict[str, int]:
    input_tokens = int(getattr(response, "prompt_eval_count", 0) or 0)
    output_tokens = int(getattr(response, "eval_count", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _log_ollama_usage(label: str, response: Any) -> Dict[str, int]:
    usage = _ollama_usage(response)
    print(
        f"[Ollama] {label}: input={usage['input_tokens']} "
        f"output={usage['output_tokens']} "
        f"total={usage['total_tokens']}",
        flush=True,
    )
    return usage


def _invoke_ollama(payload: Any, *, label: str, max_tokens: int) -> Any:
    response = ollama_chat(
        model=OLLAMA_MODEL,
        messages=_ollama_messages(payload),
        think=False,
        options={"temperature": 0, "num_predict": max_tokens},
    )
    _log_ollama_usage(label, response)
    return response


def _invoke_groq(payload: Any, *, label: str, max_tokens: int) -> Any:
    """Same prompts and budgets as Ollama, served by the shared Groq client."""
    llm = get_groq_llm(temperature=0.0, max_tokens=max_tokens)
    return invoke_llm(llm, payload, label=label)


def _invoke_model(payload: Any, *, label: str, max_tokens: int, provider: str) -> Any:
    if provider == PROVIDER_GROQ:
        return _invoke_groq(payload, label=label, max_tokens=max_tokens)
    return _invoke_ollama(payload, label=label, max_tokens=max_tokens)


def _model_content(response: Any, provider: str) -> str:
    if provider == PROVIDER_GROQ:
        return str(getattr(response, "content", "") or "")
    return _ollama_content(response)


def _model_usage(response: Any, provider: str) -> Dict[str, int]:
    if provider == PROVIDER_GROQ:
        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
        }
    return _ollama_usage(response)


def _law_document_title(meta: Dict[str, Any]) -> str:
    """Statute chunks carry only PDF-loader metadata; the Act name is in the filename."""
    title = str(meta.get("act_name") or "").strip()
    if title:
        return title

    raw = str(meta.get("source") or "").replace("\\", "/")
    name = raw.split("/")[-1].strip()
    name = re.sub(r"\.(pdf|docx?|txt|html?)$", "", name, flags=re.I)
    name = re.sub(r"^\d+\s*[-_. ]*", "", name)
    name = name.replace("_", " ").strip()
    if not name:
        meta_title = str(meta.get("title") or "").strip()
        if meta_title and "word" not in meta_title.lower():
            name = meta_title
    return name or "Pakistani Legal Provision"


def get_source_label(doc: Any, index: int, kind: Optional[str] = None) -> str:
    meta = getattr(doc, "metadata", {}) or {}
    kind = kind or meta.get("_retriever_kind") or KIND_CASES

    if kind == KIND_LAW:
        doc_name = _law_document_title(meta)
    else:
        doc_name = (
            meta.get("case_name")
            or meta.get("title")
            or meta.get("act_name")
            or meta.get("document")
            or meta.get("source")
            or "Pakistani Legal Authority"
        )

    citation = meta.get("citation", "")
    court = meta.get("court", "")
    date = meta.get("decision_date") or meta.get("date") or ""
    section = meta.get("section_number") or meta.get("section", "")
    page = meta.get("page_label") or meta.get("page_number") or meta.get("page") or ""

    kind_tag = "STATUTE" if kind == KIND_LAW else "CASE LAW"
    parts = [f"SOURCE-{index} [{kind_tag}]: {doc_name}"]
    if citation:
        parts.append(f"Citation: {citation}")
    if court:
        parts.append(f"Court: {court}")
    if section:
        parts.append(f"Section {section}")
    if date:
        parts.append(f"Date: {date}")
    if page:
        parts.append(f"Page {page}")
    if kind == KIND_LAW and meta.get("total_pages"):
        parts.append(f"Of {meta['total_pages']} pages")
    return " | ".join(str(part) for part in parts)


def unique_documents(documents: List[Any]) -> List[Any]:
    seen = set()
    unique = []
    for doc in documents:
        key = (doc.page_content or "", str(doc.metadata or {}))
        if key not in seen:
            seen.add(key)
            unique.append(doc)
    return unique


def _act_family(meta: Dict[str, Any]) -> str:
    """Normalize an Act title so duplicate file copies of one law collapse."""
    title = _law_document_title(meta)
    title = re.sub(r"\([^)]*\)", " ", title)
    title = re.sub(r"^the\s+", " ", title.strip(), flags=re.I)
    title = re.sub(r"^\d+\s*", " ", title.strip())
    return re.sub(r"[^a-z]", "", title.lower())[:20]


def _dedupe_hits(law_hits: List[Dict[str, Any]], cases_hits: List[Dict[str, Any]]) -> Tuple[List[Any], List[Any]]:
    law_unique: List[Any] = []
    cases_unique: List[Any] = []
    seen = set()
    seen_prefixes = set()
    seen_pages = set()
    seen_cases = set()
    for hit in list(law_hits) + list(cases_hits):
        doc = hit["doc"]
        key = (doc.page_content or "", str(doc.metadata or {}))
        if key in seen:
            continue
        # The same statutory page or headnote often appears in two files.
        prefix = re.sub(r"\W+", "", (doc.page_content or "").lower())[:240]
        if prefix and prefix in seen_prefixes:
            continue
        meta = doc.metadata or {}
        if hit["kind"] == KIND_LAW:
            page = str(meta.get("page_label") or meta.get("page_number") or meta.get("page") or "")
            family = _act_family(meta)
            if page and family and (family, page) in seen_pages:
                continue  # second copy of the same Act page under another filename
        else:
            case_key = re.sub(
                r"\W+",
                "",
                str(meta.get("citation") or meta.get("case_name") or meta.get("title") or ""),
            ).lower()
            if case_key and case_key in seen_cases:
                continue  # keep one excerpt per judgment, not three chunks
        seen.add(key)
        seen_prefixes.add(prefix)
        if hit["kind"] == KIND_LAW:
            page = str(meta.get("page_label") or meta.get("page_number") or meta.get("page") or "")
            if page:
                seen_pages.add((_act_family(meta), page))
        else:
            case_key = re.sub(
                r"\W+",
                "",
                str(meta.get("citation") or meta.get("case_name") or meta.get("title") or ""),
            ).lower()
            if case_key:
                seen_cases.add(case_key)
        (law_unique if hit["kind"] == KIND_LAW else cases_unique).append(hit)
    return law_unique, cases_unique


def _section_char_budget(kind: str) -> int:
    share = LAW_RETRIEVAL_SHARE if kind == KIND_LAW else (1.0 - LAW_RETRIEVAL_SHARE)
    return max(300, int(MAX_RETRIEVAL_CHARS * share))


def select_evidence(
    law_hits: List[Dict[str, Any]],
    cases_hits: List[Dict[str, Any]],
    max_law: Optional[int] = None,
    max_cases: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Choose passages per index and number them as one continuous SOURCE list."""
    law_hits, cases_hits = _dedupe_hits(law_hits, cases_hits)
    limits = {
        KIND_LAW: MAX_EVIDENCE_LAW if max_law is None else max_law,
        KIND_CASES: MAX_EVIDENCE_CASES if max_cases is None else max_cases,
    }
    evidence: List[Dict[str, Any]] = []
    for kind, hits in ((KIND_LAW, law_hits), (KIND_CASES, cases_hits)):
        chosen = hits[: max(0, limits[kind])]
        budget = _section_char_budget(kind)
        per_doc = MAX_CHARS_PER_DOCUMENT
        if chosen:
            # Reserve the label overhead per passage before splitting what is left.
            usable = max(300, budget - LABEL_OVERHEAD_CHARS * len(chosen))
            per_doc = max(300, min(MAX_CHARS_PER_DOCUMENT, usable // len(chosen)))
        used = 0
        for hit in chosen:
            content = (hit["doc"].page_content or "").strip()
            if not content or budget - used < 250:
                continue
            content = truncate_chars(content, min(per_doc, budget - used - LABEL_OVERHEAD_CHARS))
            evidence.append(
                {
                    "kind": kind,
                    "doc": hit["doc"],
                    "score": hit.get("score"),
                    "facet": hit.get("facet", -1),
                    "content": content,
                    "source_index": len(evidence) + 1,
                }
            )
            used += len(content) + LABEL_OVERHEAD_CHARS
    return evidence


def evidence_labels(evidence: List[Dict[str, Any]]) -> List[str]:
    return [
        get_source_label(item["doc"], item["source_index"], item["kind"])
        for item in evidence
    ]


LAW_SECTION_HEADING = (
    "STATUTORY / SUBORDINATE LAW PROVISIONS (text of Pakistani Acts and ordinances):"
)
CASE_SECTION_HEADING = (
    "CASE-LAW PRECEDENTS (reported Pakistani judgments showing how courts applied the law):"
)


def format_evidence(evidence: List[Dict[str, Any]]) -> str:
    """Render the selected passages as two clearly separated groups."""
    if not evidence:
        return "No specific statutory or case-law authorities are available for this question."

    blocks: Dict[str, List[str]] = {KIND_LAW: [], KIND_CASES: []}
    for item in evidence:
        label = get_source_label(item["doc"], item["source_index"], item["kind"])
        # Lead with the compact [SOURCE-n] bracket so the model copies only that
        # token inline; the descriptive remainder follows outside the brackets.
        short, _, rest = label.partition(" ")
        header = "[{0}] {1}".format(short, rest).rstrip()
        blocks[item["kind"]].append("{0}\nContent:\n{1}".format(header, item["content"]))

    sections = []
    for kind, heading in ((KIND_LAW, LAW_SECTION_HEADING), (KIND_CASES, CASE_SECTION_HEADING)):
        if blocks[kind]:
            sections.append(heading + "\n\n" + "\n\n".join(blocks[kind]))

    combined = "\n\n".join(sections)
    return truncate_to_tokens(
        combined,
        RETRIEVAL_TOKEN_BUDGET,
        suffix=" …[sources trimmed]",
    )


def format_documents(documents: List[Any]) -> str:
    """Legacy single-index formatter kept for callers of the original module."""
    return format_evidence(
        select_evidence(
            [],
            [{"kind": KIND_CASES, "doc": doc} for doc in documents],
        )
    )


def retrieval_unavailable_notice(status: Dict[str, Any]) -> str:
    """Tell the model which authority group is unavailable, in client-facing terms."""
    problems = []
    for kind, info in status.items():
        state = info.get("state")
        if state == "ready":
            continue
        group = "Statutory texts (Acts and ordinances)" if kind == KIND_LAW else "Reported court judgments"
        if state in ("missing", "error"):
            problems.append(
                f"- {group} are unavailable in this session, so the answer cannot rely on "
                f"{'statutory text' if kind == KIND_LAW else 'precedent'}."
            )
    for kind, info in status.items():
        if info.get("last_query_error"):
            group = "statutory texts" if kind == KIND_LAW else "reported judgments"
            problems.append(f"- The search of {group} did not complete for this question.")

    if not problems:
        return ""
    return (
        "SOURCE AVAILABILITY NOTE (internal; convey the substance briefly and professionally, "
        "without mentioning indexes, retrieval, or system errors; do not replace the missing "
        "authorities with knowledge from memory):\n" + "\n".join(problems)
    )


_SECTION_MENTION = re.compile(r"\bsection\s*(?:no\.?\s*)?(\d{1,4}[A-Z]?)\b", re.I)
_YEAR_TOKEN = re.compile(r"(18|19|20)\d{2}")
_SECTION_START = re.compile(r"(?m)^\s*(\d{1,4}[A-Z]?)\s*[.\u00b7]")
_NEXT_SECTION = re.compile(r"(?m)^\s*\d{1,4}[A-Z]?\s*[.\u00b7]")


def _section_numbers(query: str) -> List[str]:
    numbers = _SECTION_MENTION.findall(query or "")
    if not numbers:
        numbers = [
            token
            for token in re.findall(r"\b\d{2,4}[A-Z]?\b", query or "")
            if not _YEAR_TOKEN.fullmatch(token)
        ]
    return list(dict.fromkeys(numbers))[:2]


_section_maps: Dict[str, Tuple[int, Dict[str, List[str]]]] = {}


def _get_section_map(kind: str, store: Any) -> Dict[str, List[str]]:
    """section number -> chunk ids, built once per index size."""
    docstore = store.docstore._dict
    cached = _section_maps.get(kind)
    if cached and cached[0] == len(docstore):
        return cached[1]
    mapping: Dict[str, List[str]] = {}
    for doc_id, doc in docstore.items():
        for num in set(_SECTION_START.findall(doc.page_content or "")):
            mapping.setdefault(num, []).append(doc_id)
    _section_maps[kind] = (len(docstore), mapping)
    return mapping


def _anchor_query_words(query: str) -> set:
    expanded = (query or "").lower()
    for short, full in pakistancode_web._ALIASES.items():
        expanded = re.sub(r"\b" + short + r"\b", full, expanded)
    return {
        word
        for word in _query_words(expanded)
        if word not in _QUERY_STOPWORDS and not word.isdigit()
    }


def _citation_boost(
    kind: str, query: str, hits: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Guarantee the chunk where the asked section starts reaches retrieval.

    Embeddings rank citation queries poorly and BM25 prefers contents pages and
    other Acts' tables, so the provision itself can miss the fused top-k entirely.
    Anchoring on the literal "379." line keeps the text in the evidence pool with
    its true distance so every downstream threshold still applies.
    """
    numbers = _section_numbers(query)
    store = get_store(kind)
    if not numbers or store is None:
        return hits
    try:
        import numpy as np

        mapping = _get_section_map(kind, store)
        docstore = store.docstore._dict
        _, _, docid_to_row = hybrid_retrieval._get_entry(kind, store)
        embed = store.embedding_function
        embed_query = getattr(embed, "embed_query", None) or embed
        qvec = np.asarray(embed_query(query), dtype=np.float32)
    except Exception:
        return hits
    anchor_words = _anchor_query_words(query)
    have = {(h["doc"].page_content or "", str(h["doc"].metadata or {})) for h in hits}
    extra: List[Dict[str, Any]] = []
    for num in numbers:
        start = re.compile(r"(?mi)^\s*" + re.escape(num) + r"\s*[.\u00b7]\s*")
        for doc_id in mapping.get(num, []):
            doc = docstore[doc_id]
            meta = doc.metadata or {}
            text = doc.page_content or ""
            title_match = (
                len(anchor_words & set(_query_words(_law_document_title(meta)))) >= 2
            )
            text_match = not anchor_words or any(w in text.lower() for w in anchor_words)
            if not title_match and not text_match:
                continue
            m = start.search(text)
            if not m:
                continue
            key = (text, str(meta))
            if key in have:
                continue
            nxt = _NEXT_SECTION.search(text, m.end())
            if (nxt.start() if nxt else len(text)) - m.end() < 80:
                continue  # a contents-page listing, not the provision itself
            row = docid_to_row.get(doc_id)
            distance = (
                hybrid_retrieval._l2_distance(store, qvec, row)
                if row is not None
                else WEB_TRIGGER_DISTANCE
            )
            extra.append(
                {
                    "kind": kind,
                    "doc": doc,
                    "score": float(distance),
                    "facet": -1,
                    "query": query,
                    "_citation_title_match": title_match,
                }
            )
    if any(item["_citation_title_match"] for item in extra):
        # When the query names the Act, chunks from other Acts are noise.
        extra = [item for item in extra if item["_citation_title_match"]]
    extra.sort(key=lambda item: (not item["_citation_title_match"], item["score"]))
    boosted = extra[:3]
    for hit in boosted:
        hit.pop("_citation_title_match", None)
    return boosted + hits


def _local_statutes_on_topic(query: str, law_hits: List[Dict[str, Any]]) -> bool:
    """A weak distance can still point at the wrong Act; require the top statute
    hits to actually name the question's most distinctive terms — and, when the
    question cites a section number, to contain that number."""
    numbers = _section_numbers(query)
    terms = sorted(
        (
            word
            for word in _query_words(query)
            if word not in _QUERY_STOPWORDS and not word.isdigit()
        ),
        key=len,
        reverse=True,
    )[:2]
    for hit in law_hits[:3]:
        text = (hit["doc"].page_content or "").lower()
        terms_ok = all(term in text for term in terms) if terms else True
        number_ok = not numbers or any(
            re.search(r"(?<!\d)" + re.escape(num) + r"(?!\d)", text) for num in numbers
        )
        if terms_ok and number_ok:
            return True
    return False


def _repeated_question(session: Any, search_query: str) -> bool:
    """True when this resolved question was already answered in the session."""
    norm = re.sub(r"\W+", " ", (search_query or "").lower()).strip()
    if not norm:
        return False
    for event in getattr(session, "ui_events", []):
        if event.get("type") == "message" and event.get("role") == "assistant":
            prior = re.sub(
                r"\W+", " ", str(event.get("search_query") or "").lower()
            ).strip()
            if prior == norm:
                return True
    return False


def _prewarm() -> None:
    """Build the lazily-created retrieval structures while the server idles."""
    for kind in (KIND_LAW, KIND_CASES):
        store = get_store(kind)
        if store is None:
            continue
        try:
            hybrid_retrieval._get_entry(kind, store)
        except Exception:
            pass
        if kind == KIND_LAW:
            try:
                _get_section_map(kind, store)
            except Exception:
                pass


threading.Thread(target=_prewarm, daemon=True, name="legal-prewarm").start()


def _search_store(
    kind: str,
    query: str,
    top_k: int,
    facet: int = -1,
) -> List[Dict[str, Any]]:
    store = get_store(kind)
    if store is None or not query.strip() or top_k <= 0:
        return []
    try:
        pairs = hybrid_retrieval.hybrid_search(kind, store, query, top_k)
        if pairs is None:
            pairs = store.similarity_search_with_score(query, k=top_k)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        _store_status[kind]["last_query_error"] = message
        print(f"FAISS {kind} search error: {message}", flush=True)
        return []
    _store_status[kind]["last_query_error"] = None
    return [
        {"kind": kind, "doc": doc, "score": float(score), "facet": facet, "query": query}
        for doc, score in pairs
    ]


def retrieve_dual_documents(
    query: str,
    top_k_law: int = TOP_K_LAW,
    top_k_cases: int = TOP_K_CASES,
) -> Dict[str, Any]:
    """Query both indexes for the same question and return them separately."""
    law_hits = _citation_boost(KIND_LAW, query, _search_store(KIND_LAW, query, top_k_law))
    cases_hits = _search_store(KIND_CASES, query, top_k_cases)
    return {
        "law": law_hits,
        "cases": cases_hits,
        "status": retrieval_status(),
    }


def retrieve_documents(query: str, top_k: int = TOP_K) -> Tuple[List[Any], List[float]]:
    """Compat accessor: passages from both indexes, judgments first."""
    result = retrieve_dual_documents(query, top_k_law=top_k, top_k_cases=top_k)
    hits = list(result["cases"]) + list(result["law"])
    return [hit["doc"] for hit in hits], [hit["score"] for hit in hits]


# ---------------------------------------------------------------------------
# Multi-part questions: split the ask, search both indexes per part, verify
# that every part has evidence before the model is allowed to answer.
# ---------------------------------------------------------------------------

MAX_EVIDENCE_LAW_MULTI = _env_int("MAX_EVIDENCE_LAW_MULTI", 5)
MAX_EVIDENCE_CASES_MULTI = _env_int("MAX_EVIDENCE_CASES_MULTI", 7)
LAW_RELATIVE_MARGIN = _env_float("LAW_RELATIVE_MARGIN", 0.25, 0.05, 1.0)
CASES_RELATIVE_MARGIN = _env_float("CASES_RELATIVE_MARGIN", 0.40, 0.05, 1.0)
RELEVANCE_SCORE_FLOOR = _env_float("RELEVANCE_SCORE_FLOOR", 0.60, 0.0, 1.5)
# Best statute distance above this means the local match is too weak to answer alone.
WEB_TRIGGER_DISTANCE = _env_float("WEB_TRIGGER_DISTANCE", 0.70, 0.3, 1.5)

_QUERY_STOPWORDS = frozenset(
    """
    a an the and or of to in on for with without is are was were be been being
    what which how why when who whom whose do does did done not no yes its it
    this that these those there their they them he she his her i we you your
    as at by from into about regarding explain give list tell can could may
    might must shall should will would also more most other such then than so
    if but while please me my question answer parts part asked provide tell
    legal law laws act acts statute statutes section sections crpc ppc
    pakistan pakistani court courts judge judges bench under pursuant
    get obtain apply made make taking take want needed relevant
    """.split()
)


# Only function words are dropped when building a search query: very short queries
# embed poorly, so terms like "conditions", "procedure" or "section" are kept.
_QUERY_FILLERS = frozenset(
    """
    a an the and or but of to in on at for with without as by from into about
    regarding is are was were be been being do does did done not no nor so than
    that this these those it its its own he him his she her they them their
    you your we our i me my mine who whom whose which what when where how why
    please tell say said give list explain describe define
    pakistan pakistani there here also more most other such then therefore
    can could may might must shall should will would want wish need needed
    """.split()
)


def _stem(term: str) -> str:
    """Crude prefix stem so 'means/meaning' and 'step/steps' compare as one idea."""
    return term[:4] if len(term) > 4 else term


def _keywords(text: str) -> List[str]:
    """Meaningful words of a phrase, in order, without stopwords."""
    return list(
        dict.fromkeys(
            term
            for term in re.findall(r"[a-z0-9']+", (text or "").lower())
            if term not in _QUERY_STOPWORDS and len(term) > 2
        )
    )


def _content_terms(text: str) -> List[str]:
    return [_stem(term) for term in _keywords(text)]


_FACET_SIGNAL_RE = re.compile(
    r"\b(defini\w*|mean\w*|condition\w*|requirement\w*| ground\w*|procedure|"
    r"process|steps?|step\w*|effect\w*|consequence\w*|right\w*|liabilit\w*|"
    r"obligation\w*|penalt\w*|punish\w*|validity|principle\w*|provision\w*|"
    r"api\w*|remedy|remedies|differen\w*|eligible|eligibility|how to|how does)\b",
    re.IGNORECASE,
)


def _is_citation_lookup(text: str) -> bool:
    """A lone "section 379 of PPC" request names one provision, not several
    facets; decomposing it only fragments retrieval below the boosted chunk."""
    if not _section_numbers(text):
        return False
    signals = {
        match.group(0).lower() for match in _FACET_SIGNAL_RE.finditer(text or "")
    }
    return len(signals) <= 1


def _is_multi_part(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    if len(cleaned.split()) < 6:
        return False
    signals = {match.group(0).lower() for match in _FACET_SIGNAL_RE.finditer(cleaned)}
    separators = cleaned.count(",") + len(re.findall(r"\band\b", cleaned))
    if len(signals) >= 2:
        return True
    return separators >= 2 and len(signals) >= 1


# Keys are the 4-character stems produced by _stem().
_TERM_EXPANSIONS = {
    "defi": ("meaning", "concept", "import"),
    "mean": ("definition", "signification"),
    "cond": ("requirements", "preconditions", "eligibility"),
    "requ": ("conditions", "essential"),
    "elgi": ("qualification", "conditions"),
    "step": ("procedure", "process", "filing"),
    "proc": ("steps", "process", "application"),
    "cons": ("consequences", "effect"),
    "effe": ("consequences", "outcome"),
    "grou": ("basis", "reasons"),
    "righ": ("entitlement", "option"),
    "puni": ("penalty", "sentence"),
    "pena": ("punishment", "fine"),
    "sect": ("provision", "article"),
    "prov": ("section", "enactment"),
    "prin": ("doctrine", "rules"),
    "remi": ("relief", "recourse"),
    "appe": ("revision", "challenge"),
}


def _expansion_for(words: List[str]) -> str:
    for word in words:
        synonyms = _TERM_EXPANSIONS.get(_stem(word))
        if synonyms:
            return synonyms[0]
    return ""


def _heuristic_facets(query: str) -> List[Dict[str, str]]:
    """Split on commas/conjunctions and re-attach the subject to every fragment."""
    fragments = [
        fragment.strip()
        for fragment in re.split(r"[,;]|\band\b|\bplus\b|\balso\b", query, flags=re.I)
        if len(fragment.strip()) > 4
    ]
    if len(fragments) < 2:
        return []
    subject_words = _keywords(fragments[0])[:1]
    subject = subject_words[0] if subject_words else ""
    facets: List[Dict[str, str]] = []
    for fragment in fragments[:MAX_FACETS]:
        all_words = _keywords(fragment)
        words = [word for word in all_words if word not in subject_words] or all_words
        search_terms = ([subject] if subject else []) + words[:4]
        search = " ".join(dict.fromkeys(search_terms))
        fallback = " ".join(
            dict.fromkeys(search_terms[:4] + [term for term in (_expansion_for(words), subject) if term])
        )
        facets.append(
            {
                "part": truncate_chars(words[0] if words else subject or "aspect", 40),
                "query": truncate_chars(search, 160),
                "fallback_query": truncate_chars(fallback or search, 160),
            }
        )
    return facets


def _query_words(text: str) -> List[str]:
    words: List[str] = []
    for word in re.findall(r"[a-z0-9']+", (text or "").lower()):
        if len(word) < 3 or word in _QUERY_FILLERS or word in words:
            continue
        words.append(word)
    return words


def _normalize_subquery(text: str, subject: str = "") -> str:
    """Reduce a sub-query to its informative words, with the subject stated once."""
    words = _query_words(text)
    if not words:
        return (subject or (text or "").strip().lower())
    if subject and subject not in words:
        words = [subject] + words
    return truncate_chars(" ".join(words[:8]), 160)


def _expansion_terms(words: List[str], limit: int = 3) -> List[str]:
    """Related search terms for the part's signal word (vocabulary only, never law)."""
    extras: List[str] = []
    for word in words:
        for synonym in _TERM_EXPANSIONS.get(_stem(word), ()):
            if synonym not in extras and _stem(synonym) != _stem(word):
                extras.append(synonym)
        if len(extras) >= limit:
            break
    return extras[:limit]


def _subject_of(question: str) -> str:
    words = _keywords(question)
    return words[0] if words else ""


def decompose_question(
    question: str,
    search_query: str,
    history: List[Any],
    document_context: str,
    provider: str = DEFAULT_LLM_PROVIDER,
) -> Tuple[List[Dict[str, str]], str]:
    """Break a multi-part ask into focused sub-queries (LLM, with a offline fallback)."""
    facets = _heuristic_facets(search_query) or _heuristic_facets(question)
    method = "heuristic" if facets else "single"

    history_text = history_as_text(
        history, max_tokens=180, max_turns=1, max_message_chars=200
    )
    context_text = truncate_to_tokens(document_context or "None", 120)
    prompt = f"""Split this Pakistani legal question into at most {MAX_FACETS} distinct parts
that each need their own evidence (for example: definition/meaning, eligibility or legal
conditions, procedure or steps, consequences or penalties, relevant sections).

For every part return a self-contained search query about Pakistani law that repeats the
subject term, plus one differently-worded fallback query. Use only words from the question
and the context; do not add legal rules, section numbers, or case names of your own.

Return JSON only, shaped as:
[{{"part": "short label", "query": "...", "fallback_query": "..."}}]

QUESTION:
{truncate_chars(question, 700)}

SEARCH QUERY:
{truncate_chars(search_query, 500)}

RECENT CONVERSATION:
{history_text or "None"}

CASE CONTEXT:
{context_text}
"""
    try:
        response = _invoke_model(
            prompt,
            label="question decomposition",
            max_tokens=DECOMPOSE_OUTPUT_TOKENS,
            provider=provider,
        )
        raw = _model_content(response, provider)
        parsed = _finalize_facets(
            _parse_facets(raw), _subject_of(search_query) or _subject_of(question)
        )
        if parsed:
            return parsed, provider
    except Exception as exc:
        print(
            f"[Legal] decomposition skipped, using heuristic split: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
    return facets, method


def _finalize_facets(facets: List[Dict[str, str]], subject: str) -> List[Dict[str, str]]:
    """Clean each model-written sub-query and drop duplicates.

    The primary query keeps only the asker's own words: adding synonyms such as
    "import" or "filing" pulled unrelated Acts (Animal Quarantine, Income Tax)
    into the statute results. Vocabulary widening is reserved for the fallback.
    """
    cleaned: List[Dict[str, str]] = []
    seen: set = set()
    for facet in facets:
        query = _normalize_subquery(facet["query"], subject)
        if not query or query.lower() in seen:
            continue
        seen.add(query.lower())
        fallback = _normalize_subquery(facet.get("fallback_query", ""), subject)
        if not fallback or fallback.lower() == query.lower():
            fallback = _normalize_subquery(
                f"{query} {' '.join(_expansion_terms(_query_words(query), 2))}", subject
            )
        if fallback.lower() == query.lower():
            fallback = ""
        cleaned.append(
            {
                "part": (facet.get("part") or subject or "part").strip(),
                "query": query,
                "fallback_query": fallback,
            }
        )
    return cleaned[:MAX_FACETS]


def _parse_facets(raw: str) -> List[Dict[str, str]]:
    start, end = raw.find("["), raw.rfind("]")
    candidate = raw[start : end + 1] if 0 <= start < end else raw
    try:
        data = json.loads(candidate)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    facets: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query") or "").strip()
        if not query or not _keywords(query):
            continue
        facets.append(
            {
                "part": truncate_chars(str(item.get("part") or query).strip(), 40),
                "query": truncate_chars(query, 160),
                "fallback_query": truncate_chars(
                    str(item.get("fallback_query") or "").strip() or query, 160
                ),
            }
        )
        if len(facets) >= MAX_FACETS:
            break
    return facets


def _order_by_facet(
    hits: List[Dict[str, Any]],
    facet_count: int,
) -> List[Dict[str, Any]]:
    """Round-robin the parts so one part cannot crowd the others out of the budget."""
    if facet_count <= 0:
        return list(hits)
    buckets: List[List[Dict[str, Any]]] = [[] for _ in range(facet_count + 1)]
    for hit in hits:
        index = hit.get("facet", -1)
        buckets[index if 0 <= index < facet_count else facet_count].append(hit)
    ordered: List[Dict[str, Any]] = []
    for rank in range(max(len(bucket) for bucket in buckets)):
        for bucket in buckets:
            if rank < len(bucket):
                ordered.append(bucket[rank])
    return ordered


def _facet_terms(facet: Dict[str, str]) -> set:
    """The part's own terms plus its synonym family, so 'steps' also matches 'procedure'."""
    words = _query_words(facet["query"]) + _query_words(facet.get("part", ""))
    terms = {_stem(word) for word in words if word not in _QUERY_STOPWORDS}
    for word in words:
        for synonym in _TERM_EXPANSIONS.get(_stem(word), ()):
            terms.add(_stem(synonym))
    return terms


def _subject_terms(*texts: str) -> List[str]:
    """The topic words a genuinely relevant passage is expected to name."""
    terms: List[str] = []
    for text in texts:
        word = _subject_of(text)
        if len(word) >= 4 and word not in terms:
            terms.append(word)
    return terms


_TITLE_NOISE = frozenset(
    """
    act acts ordinance ordinances the of and or for amendment amendments rules
    regulation regulations part chapter section schedule
    """.split()
)


def _title_terms(title: str) -> List[str]:
    return [
        word
        for word in _query_words(title)
        if word not in _TITLE_NOISE and not word.isdigit()
    ]


def _prune_off_topic(
    hits: List[Dict[str, Any]],
    facets: List[Dict[str, str]],
    subject_terms: List[str],
    margin: float,
) -> List[Dict[str, Any]]:
    """Reject passages that are neither about the subject nor near their own best match.

    Distances are only comparable inside one query: an unrelated Act can sit at
    0.65 while the right Family Courts page sits at 0.86. So a passage is kept
    when it names the subject (strongest signal) or when it tracks the closest
    hit for that same query and actually uses the part's vocabulary.
    """
    if not hits:
        return []
    best_by_query: Dict[Any, float] = {}
    for hit in hits:
        key = (hit.get("facet", -1), hit.get("query", ""))
        score = best_by_query.get(key)
        if score is None or hit["score"] < score:
            best_by_query[key] = hit["score"]

    facet_terms = [_facet_terms(facet) for facet in facets]
    kept: List[Dict[str, Any]] = []
    for hit in hits:
        text = hit["doc"].page_content or ""
        key = (hit.get("facet", -1), hit.get("query", ""))
        close = hit["score"] <= best_by_query[key] + margin
        index = hit.get("facet", -1)
        terms = facet_terms[index] if 0 <= index < len(facet_terms) else set()
        topical = len(terms & set(_content_terms(text))) >= FACET_MIN_TERM_MATCHES
        hit["names_subject"] = any(term in text.lower() for term in subject_terms)
        if hit["names_subject"] or (close and topical):
            kept.append(hit)
    # Passages that actually name the topic are the ones worth spending tokens on.
    kept.sort(key=lambda item: 0 if item["names_subject"] else 1)
    return kept


def _assemble_evidence(
    law_pool: List[Dict[str, Any]],
    cases_pool: List[Dict[str, Any]],
    facets: List[Dict[str, str]],
    subject_terms: List[str],
    score_floor: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    law_ordered = _order_by_facet(
        _prune_off_topic(law_pool, facets, subject_terms, LAW_RELATIVE_MARGIN), len(facets)
    )
    cases_ordered = _order_by_facet(
        _prune_off_topic(cases_pool, facets, subject_terms, CASES_RELATIVE_MARGIN), len(facets)
    )
    evidence = select_evidence(
        law_ordered,
        cases_ordered,
        max_law=MAX_EVIDENCE_LAW_MULTI,
        max_cases=MAX_EVIDENCE_CASES_MULTI,
    )
    return law_ordered, cases_ordered, evidence, _facet_coverage(
        facets, evidence, subject_terms, score_floor
    )


def _retry_queries(
    facet: Dict[str, str],
    law_candidates: List[Dict[str, Any]],
    subject_terms: List[str],
) -> List[str]:
    """Differently-worded searches for a part that came back without support."""
    queries: List[str] = []

    def add(candidate: str) -> None:
        cleaned = truncate_chars((candidate or "").strip(), 160)
        if cleaned and cleaned.lower() not in {q.lower() for q in queries}:
            queries.append(cleaned)

    add(facet.get("fallback_query", ""))
    if not queries:
        words = _keywords(facet["query"]) + [
            word
            for word in _keywords(facet.get("part", ""))
            if word not in _keywords(facet["query"])
        ]
        add(" ".join(dict.fromkeys(words + _expansion_terms(words))))

    # An Act already confirmed to discuss the topic is a legitimate search term,
    # and naming it is what pulls that Act's other pages into the next attempt.
    for hit in law_candidates:
        if not hit.get("names_subject"):
            continue
        title = _law_document_title(hit["doc"].metadata or {})
        terms = _title_terms(title)[:3]
        if terms:
            add(f"{facet['query']} {' '.join(terms)}")
        break
    return queries[:2]


def retrieve_multi_part(
    facets: List[Dict[str, str]],
    base_query: str,
) -> Dict[str, Any]:
    """Search both indexes for the whole question and for each part, then re-try gaps."""
    subject_terms = _subject_terms(base_query, *(facet["query"] for facet in facets))
    law_pool = _citation_boost(
        KIND_LAW, base_query, _search_store(KIND_LAW, base_query, TOP_K_LAW)
    )
    cases_pool = _search_store(KIND_CASES, base_query, MAX_EVIDENCE_CASES_MULTI)
    for index, facet in enumerate(facets):
        law_pool += _search_store(KIND_LAW, facet["query"], FACET_TOP_K_LAW, facet=index)
        cases_pool += _search_store(KIND_CASES, facet["query"], FACET_TOP_K_CASES, facet=index)

    ordered_law, ordered_cases, evidence, coverage = _assemble_evidence(
        law_pool, cases_pool, facets, subject_terms, RELEVANCE_SCORE_FLOOR
    )
    if coverage and not any(item["supported"] for item in coverage):
        # The distance floor was too strict for this topic, so judge support on
        # wording alone rather than reporting every part as unsupported.
        coverage = _facet_coverage(facets, evidence, subject_terms)

    retried: List[str] = []
    gaps = [i for i, item in enumerate(coverage) if not item["supported"]]
    for index in gaps:
        facet = facets[index]
        retried.append(facet["part"])
        for retry_query in _retry_queries(facet, ordered_law, subject_terms):
            law_pool += _search_store(KIND_LAW, retry_query, FACET_TOP_K_LAW + 1, facet=index)
            cases_pool += _search_store(
                KIND_CASES, retry_query, FACET_TOP_K_CASES + 1, facet=index
            )
    if gaps:
        ordered_law, ordered_cases, evidence, coverage = _assemble_evidence(
            law_pool, cases_pool, facets, subject_terms
        )

    return {
        "law": ordered_law,
        "cases": ordered_cases,
        "evidence": evidence,
        "coverage": coverage,
        "retried_parts": retried,
        "status": retrieval_status(),
    }


def _facet_coverage(
    facets: List[Dict[str, str]],
    evidence: List[Dict[str, Any]],
    subject_terms: Optional[List[str]] = None,
    score_floor: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Check, per part, whether the passages that actually reach the model support it.

    A passage only counts as support when it names the topic itself: an unrelated
    Criminal Procedure page that happens to contain the word "steps" must never be
    reported as authority for the khula procedure part. The score floor adds the
    same guard for parts whose wording appears in an off-topic document.
    """
    terms_required = max(1, FACET_MIN_TERM_MATCHES - 1)
    subject_terms = subject_terms or []
    coverage: List[Dict[str, Any]] = []
    for index, facet in enumerate(facets):
        facet_terms = _facet_terms(facet)
        supporting: List[int] = []
        other: List[int] = []
        for item in evidence:
            text = (item["content"] or "").lower()
            names_topic = any(term in text for term in subject_terms) or not subject_terms
            score = item.get("score")
            close_enough = score is None or score_floor is None or score <= score_floor
            overlap = len(facet_terms & set(_content_terms(text)))
            matched = names_topic and close_enough and overlap >= terms_required
            if item.get("facet") == index:
                (supporting if matched else other).append(item["source_index"])
            elif item.get("facet") == -1 and matched:
                # A whole-question passage may cover this part too.
                supporting.append(item["source_index"])
        source_indexes = sorted(set(supporting)) or sorted(set(other))
        coverage.append(
            {
                "part": facet["part"],
                "query": facet["query"],
                "supported": bool(supporting),
                "source_indexes": source_indexes,
                "weak_only": not supporting and bool(other),
            }
        )
    return coverage


def build_parts_checklist(facets: List[Dict[str, str]], coverage: List[Dict[str, Any]]) -> str:
    """Tell the model which parts have evidence, so one gap cannot end the answer."""
    if not facets:
        return ""
    lines = []
    for number, item in enumerate(coverage, start=1):
        labels = ", ".join(f"SOURCE-{index}" for index in item["source_indexes"]) or "none"
        if item["supported"]:
            lines.append(f"{number}. {item['part']} — supported by: {labels}")
        elif item.get("weak_only"):
            lines.append(
                f"{number}. {item['part']} — only loosely related excerpts ({labels}); "
                "they do not state this aspect, so do not present them as authority for it"
            )
        else:
            lines.append(
                f"{number}. {item['part']} — no supporting authority is available"
                f" (query: \"{truncate_chars(item['query'], 120)}\")"
            )
    unsupported = sum(1 for item in coverage if not item["supported"])
    return (
        "PARTS REQUESTED AND EVIDENCE COVERAGE:\n"
        + "\n".join(lines)
        + "\nAnswer every supported part with its listed [SOURCE-i] labels. State a "
        "limitation only for the part it applies to and still answer the rest; never "
        "let one unsupported part stop the answer, and never supply the missing part "
        "from memory."
    )


_FOLLOWUP_RE = re.compile(
    r"\b(it|its|this|that|these|those|they|them|their|he|him|his|she|her|"
    r"same|above|previous|former|latter|such|then|next|also|there|"
    r"accused|applicant|petitioner|respondent)\b",
    re.IGNORECASE,
)


def _needs_rewrite(question: str, history: List[Any], document_context: str) -> bool:
    if not history and not document_context.strip():
        return False
    text = (question or "").strip()
    if not text:
        return False
    if _FOLLOWUP_RE.search(text):
        return True
    if re.match(r"^\s*(and|also|what about|how about|then)\b", text, re.IGNORECASE):
        return True
    if len(text.split()) <= 5:
        return True
    return False


def resolve_question(
    question: str,
    history: List[Any],
    document_context: str,
    provider: str = DEFAULT_LLM_PROVIDER,
) -> str:
    """Resolve references to earlier turns/case facts, with a small prompt."""
    if not _needs_rewrite(question, history, document_context):
        return question

    history_text = history_as_text(
        history,
        max_tokens=260,
        max_turns=2,
        max_message_chars=280,
    ) or "No earlier conversation."
    context_text = truncate_to_tokens(
        document_context or "No document uploaded.",
        max(120, int(RESOLVE_INPUT_TOKEN_BUDGET * 0.28)),
    )
    question_text = truncate_chars(question, 500)

    prompt = f"""Rewrite the latest question as a standalone Pakistani legal search query.
Use the case context and earlier conversation only to resolve references such as
"he", "the accused", "this FIR", or "that section". Do not answer. Do not invent facts.
Return only the rewritten query.

CASE CONTEXT:
{context_text}

RECENT CONVERSATION:
{history_text}

LATEST QUESTION:
{question_text}
"""
    try:
        response = _invoke_model(
            prompt,
            label="follow-up resolution",
            max_tokens=RESOLVE_OUTPUT_TOKENS,
            provider=provider,
        )
        rewritten = _model_content(response, provider).strip()
        rewritten = re.sub(r"^(rewritten query|query)\s*:\s*", "", rewritten, flags=re.I)
        rewritten = rewritten.strip().strip('"').strip("'").split("\n")[0].strip()
        if not rewritten:
            return question
        return truncate_chars(rewritten, 400)
    except Exception as exc:
        print(
            f"[Legal] follow-up resolution skipped: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return question


SYSTEM_PROMPT = """You are LegalLens, a professional legal assistant specializing in Pakistani law.
You advise users by applying their case record and the legal authorities made available
to you in this session. You do not state legal rules, offence classifications, or
procedure from memory.

You are an educational assistant, not a substitute for an enrolled Pakistani advocate.
Do not guarantee outcomes.

PROFESSIONAL VOICE:
- Speak as a composed, client-facing legal professional: direct answers first, then
  reasoning and authority. Never narrate how you work.
- Never mention retrieval, searches, indexes, databases, embeddings, or any system
  mechanics, and never describe how authorities reached you. Do not say you "cannot
  retrieve" anything or that nothing "was found"; speak only of the law and the
  materials before you.
- When the authorities available to you do not settle a point, say so professionally.
  Good example: "Section 302 PPC is not reproduced in the materials before me; the
  judgments cited show how courts have sentenced under it. For the exact statutory
  penalty, the full text of the Pakistan Penal Code should be consulted."
  Never dress the gap up as a technical failure, and never fill it from memory.
- Refer to the material you rely on as "the authorities", "the statute", "the judgment",
  "the materials before me", or by name (Act, section, case title) — never as something
  handed to you by the system.

AUTHORITY PRIORITY:
1. Uploaded case material is labeled [DOC-n]. It is the case record, not legal authority.
2. Legal authorities are provided in two clearly separated groups under
   "LEGAL AUTHORITIES":
   a. STATUTORY / SUBORDINATE LAW PROVISIONS - the text of Pakistani Acts and
      ordinances (PPC, CrPC, and other statutes).
   b. CASE-LAW PRECEDENTS - reported Pakistani judgments.
   c. ONLINE FEDERAL LAW TEXTS - live copies from the official Pakistan Code
      website (pakistancode.gov.pk), identified by that citation. Treat them as
      statutory text; when you rely on one, note that the Pakistan Code website
      was consulted.
   Each excerpt carries its own [SOURCE-i] label and a [STATUTE] or [CASE LAW] tag.
   Cite them only with their exact [SOURCE-i] label when the content supports the
   statement.
3. General knowledge may explain a background concept only when it is explicitly
   labeled "General reference (not legal authority)". It must not supply
   statutory numbers, offence classifications, bail rules, or procedure.

HOW TO USE BOTH GROUPS TOGETHER:
- State the rule from a [STATUTE] excerpt (name the Act and the section number only
  when both appear in that excerpt's content or label), then show how a [CASE LAW]
  excerpt applies, interprets, or limits it, and then apply both to the user's facts.
- If only one group answers part of the question, say which part rests on the statute
  and which part lacks supporting precedent (or statutory text) instead
  of inventing the missing half.
- Never attribute wording of a judgment to a statute, or wording of a statute to a
  judgment. Keep the two kinds of authority distinct in the answer.

RULES:
- Never cite a [DOC-n] case excerpt as [SOURCE-i]. Mention case material only as
  "the case record (DOC-n)" or by document type.
- A judgment name (for example, "Inayat vs State") is a legal authority
  [SOURCE-i], never the case record. Refer to it as "[SOURCE-4] Inayat vs State".
- The user's question is not the case record. Never attribute a fact from the
  question to the case record. If no documents were uploaded, never refer to "the case
  record"; note the absence of case documents naturally, and only when it matters to
  the answer.
- A value marked [user-corrected], or listed under USER-CORRECTED VALUES
  (AUTHORITATIVE), replaces the original extraction in every summary and excerpt.
  Always use the corrected value; never revert to the original text.
- Use only [SOURCE-i] labels that appear under LEGAL AUTHORITIES.
- Never fabricate section numbers, case titles, citations, quotations, or holdings.
- Every statement about what a statutory provision requires, or whether an offence
  is bailable/non-bailable or cognizable/non-cognizable, must be supported by a
  cited [SOURCE-i] or stated in the case record. If the available authorities do not
  establish it, say so professionally instead of relying on memory.
- If an authority states a classification or rule, follow that authority exactly;
  never override it with general knowledge.
- Do not state what a statutory section says, what its legal test is, or how a
  procedure works unless that description appears in the cited authorities or case
  record. Never fill a gap with a general explanation of bail or criminal procedure.
- A numbered list of steps, requirements or documents may only repeat the items the
  cited excerpt itself lists. If an excerpt names an Act, section or right without
  enumerating steps, state exactly that and stop; do not expand the citation into a
  filing procedure from general knowledge.
- If the available authorities do not identify the offence section or its bail status,
  say that plainly. Do not offer possible section numbers as examples or guesses
  (not even in phrases like "e.g., section ...").
- When the question has several parts, treat each part separately. A gap in one part
  never excuses the others: answer every part the authorities support, and
  state the limitation only for the unsupported part.
- If the available authorities do not establish one requested rule, do not fill that gap
  and do not give practical next steps for it. For that part, return only: (1) one short
  professional statement that the point is not established by the authorities available
  in this session, and (2) the specific document or material that would be needed.
  Do not include examples, general law, or advice to look up particular section numbers.
- Never add a "practical next steps" section that supplies unsourced legal procedure.
- Do not introduce any statutory section number that is not present in the case
  record or cited authorities, even as an example. Do not describe a section by
  relying on memory.
- This assistant covers Pakistani law. Do not import Indian CrPC 1973 numbering or
  treat non-Pakistani authorities as binding.
- If an authority is from another jurisdiction, label it as non-Pakistani
  and do not present it as binding Pakistani law.
- Distinguish FIR allegations from facts established by a court.
- Apply the law to the known facts and explicitly state missing facts or limitations.
- If the available authorities do not address part of the question, say so for that part
  only and continue answering the parts they do address.
- Use clear, structured, professional English with short headings and bullet lists
  or compact tables. Be concise and do not repeat the case context.

Suggested structure when the authorities answer the question: direct answer, case facts
used, law supported by cited authorities, limitations. Give one heading per requested
part. When a part is not covered, use a short, professional limitation statement for
that part only. Omit any section or citation that would require unsourced legal rules or
procedure, but still answer the parts the authorities do support.
"""


def _build_messages(
    question: str,
    document_context: str,
    retrieved_context: str,
    history: List[Any],
    factor: float,
    retrieval_note: str = "",
    parts_checklist: str = "",
) -> Tuple[List[Any], Dict[str, int]]:
    input_budget = max(800, int(MAX_INPUT_TOKENS * factor))
    history_messages = build_bounded_history(
        history,
        max_tokens=int(HISTORY_TOKEN_BUDGET * factor),
        max_turns=MAX_HISTORY_TURNS,
        max_message_chars=MAX_HISTORY_MESSAGE_CHARS,
    )
    early_memory_text = build_early_memory(
        history,
        max_tokens=int(EARLY_MEMORY_TOKEN_BUDGET * factor),
        skip_recent=MAX_HISTORY_TURNS * 2,
        max_message_chars=MAX_EARLY_MEMORY_CHARS,
    )
    question_text = truncate_chars(question, MAX_QUESTION_CHARS)
    case_text = truncate_to_tokens(
        document_context or "No case documents have been uploaded in this session.",
        max(150, int(CASE_CONTEXT_TOKEN_BUDGET * factor)),
        suffix=" …[case context trimmed]",
    )
    sources_text = truncate_to_tokens(
        retrieved_context,
        max(120, int(RETRIEVAL_TOKEN_BUDGET * factor)),
        suffix=" …[sources trimmed]",
    )
    note_text = truncate_to_tokens(retrieval_note or "", 140)
    parts_text = truncate_to_tokens(parts_checklist or "", 260)

    def assemble() -> List[Any]:
        note_block = f"\n\n{note_text}" if note_text else ""
        parts_block = f"\n\n{parts_text}\n" if parts_text else ""
        memory_block = (
            f"\n\nEARLIER CONVERSATION MEMORY (older user statements; background only, "
            f"not a legal source, may be trimmed):\n{early_memory_text}"
            if early_memory_text
            else ""
        )
        user_prompt = f"""LATEST USER QUESTION:
{question_text}

COMPACT CASE CONTEXT (full documents are stored separately; excerpts only):
{case_text}{memory_block}

LEGAL AUTHORITIES:
{sources_text}{note_block}{parts_block}
INSTRUCTIONS:
- Answer the specific question using the case facts above, as a professional legal
  assistant. Never mention retrieval, indexes, or system mechanics.
- If a PARTS REQUESTED list is given, answer each listed part that has supporting
  authorities, under its own heading, and flag only the parts whose evidence is missing.
- Cite authorities with their exact [SOURCE-i] labels only where they support a claim.
- Use [STATUTE] excerpts for the wording of the law and [CASE LAW] excerpts for how the
  courts applied it; keep the two kinds of authority separate and never quote one as the other.
- Treat USER-CORRECTED VALUES as authoritative over any conflicting summary or excerpt.
- Refer to uploaded documents as DOC-n; never label a case excerpt as SOURCE-i.
- Sources citing pakistancode.gov.pk are live online copies of federal laws; treat
  them as statutory text and mention the Pakistan Code website when you rely on them.
- If a SOURCE AVAILABILITY NOTE is present, reflect its substance briefly and
  professionally; do not quote it or describe technical details.
- Do not repeat the case context verbatim. If the authorities do not answer a part of the
  question, say so professionally for that part only; do not suggest legal steps or
  section numbers.
"""
        return [SystemMessage(content=SYSTEM_PROMPT), *history_messages, HumanMessage(content=user_prompt)]

    messages = assemble()
    for _ in range(12):
        total = count_message_tokens(messages)
        if total <= input_budget:
            break
        # Drop the least critical content first: sources, case facts, early memory, then old turns.
        if count_tokens(sources_text) > 120:
            sources_text = truncate_to_tokens(
                sources_text,
                max(100, int(count_tokens(sources_text) * 0.7)),
                suffix=" …",
            )
        elif count_tokens(case_text) > 130:
            case_text = truncate_to_tokens(
                case_text,
                max(110, int(count_tokens(case_text) * 0.7)),
                suffix=" …",
            )
        elif count_tokens(early_memory_text) > 60:
            early_memory_text = truncate_to_tokens(
                early_memory_text,
                max(50, int(count_tokens(early_memory_text) * 0.7)),
                suffix=" …",
            )
        elif history_messages:
            history_messages = history_messages[1:]
        else:
            if count_tokens(question_text) > max(80, input_budget // 3):
                question_text = truncate_to_tokens(
                    question_text, max(60, input_budget // 3)
                )
            messages = assemble()
            break
        messages = assemble()

    stats = {
        "budget_factor": round(factor, 2),
        "input_budget": input_budget,
        "input_estimated": count_message_tokens(messages),
        "system_tokens": count_tokens(SYSTEM_PROMPT),
        "history_tokens": count_message_tokens(history_messages),
        "early_memory_tokens": count_tokens(early_memory_text),
        "case_context_tokens": count_tokens(case_text),
        "retrieval_tokens": count_tokens(sources_text),
        "output_limit": MAX_OUTPUT_TOKENS,
    }
    return messages, stats


def generate_legal_answer(
    question: str,
    document_context: str,
    retrieved_context: str,
    history: List[Any],
    stats: Optional[Dict[str, Any]] = None,
    retrieval_note: str = "",
    parts_checklist: str = "",
    provider: str = DEFAULT_LLM_PROVIDER,
) -> str:
    """Generate a grounded answer, retrying with tighter context on token errors."""
    last_error: Optional[BaseException] = None
    label = provider_label(provider)

    for attempt, factor in enumerate((1.0, 0.6, 0.4)):
        messages, context_stats = _build_messages(
            question,
            document_context,
            retrieved_context,
            history,
            factor,
            retrieval_note,
            parts_checklist,
        )
        if stats is not None:
            stats.clear()
            stats.update(context_stats)
        try:
            response = _invoke_model(
                messages,
                label="legal answer",
                max_tokens=MAX_OUTPUT_TOKENS,
                provider=provider,
            )
            usage = _model_usage(response, provider)
            content = _model_content(response, provider).strip()
            if not content:
                last_error = RuntimeError("The model returned an empty answer.")
                continue
            if stats is not None:
                stats["usage"] = usage
                stats["request_total_estimate"] = (
                    context_stats["input_estimated"] + int(usage.get("output_tokens") or 0)
                )
            return content
        except Exception as exc:
            last_error = exc
            if not is_token_limit_error(exc):
                break
            if attempt == 0:
                print(
                    f"[Legal] {label} rejected the context size; retrying with tighter context.",
                    flush=True,
                )
            else:
                print(f"[Legal] {label} rejected the reduced context; retrying with minimum context.", flush=True)

    if stats is not None:
        stats["error"] = type(last_error).__name__ if last_error else "unknown"
    if last_error:
        print(f"[{label}] legal answer failed: {type(last_error).__name__}: {last_error}", flush=True)
    if provider == PROVIDER_GROQ:
        return friendly_llm_error(last_error or RuntimeError("empty answer"), context="answer")
    if last_error and is_token_limit_error(last_error):
        return (
            "The Ollama model could not process the request size after the context was "
            "trimmed. Please retry with a narrower question."
        )
    return (
        f"The local Ollama request failed. Ensure Ollama is running and "
        f"'{OLLAMA_MODEL}' is available (run `ollama pull {OLLAMA_MODEL}` if needed)."
    )


def is_doc_generation_request(text: str) -> Tuple[bool, str]:
    """Compatibility helper retained for callers of the original module.

    The live chat route uses generation_workflow.detect_generation_request so
    clarification answers are never routed to the RAG agent.
    """
    cleaned = text.lower()
    gen_triggers = [
        "draft", "generate", "create", "write", "prepare", "make a petition",
        "make an application", "fill template", "generate document", "download",
    ]
    if not any(trigger in cleaned for trigger in gen_triggers):
        return False, "Bail Application.docx"
    if any(key in cleaned for key in ["bail", "497", "498", "custody", "release from jail"]):
        return True, "Bail Application.docx"
    if any(key in cleaned for key in ["notice", "legal notice"]):
        return True, "Legal Notice.docx"
    if any(key in cleaned for key in ["petition", "application", "document"]):
        return True, "Bail Application.docx"
    return False, "Bail Application.docx"


def ask_legal_agent(
    question: str,
    session_id: str = "default",
    force_generation: bool = False,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Run retrieval and grounded legal reasoning.

    `force_generation` is retained for signature compatibility; live document
    generation is handled by generation_workflow.py before this function.
    `provider` selects the chat model only — retrieval, prompts, history and
    citations are shared, and the document agents always stay on Groq.
    """
    provider = normalize_provider(provider)
    if not question or not question.strip():
        return {
            "answer": "Please enter a legal query or document drafting instruction.",
            "search_query": "",
            "sources": [],
            "scores": [],
            "tool_called": None,
            "is_document_generation": False,
            "generation_result": None,
        }

    session = session_manager.get_session(session_id)
    if session is None:
        return {"answer": "Case session not found.", "sources": [], "scores": []}

    with session.lock:
        history = list(session.history)

        case_context_text = build_case_context(
            session,
            question,
            max_tokens=CASE_CONTEXT_TOKEN_BUDGET,
            include_excerpts=True,
        )
        precedent_context = build_precedent_context(session, question, max_tokens=360)
        if precedent_context:
            case_context_text = (case_context_text + "\n\n" + precedent_context).strip()
        resolve_context = build_case_context(
            session,
            question,
            max_tokens=320,
            include_excerpts=False,
        )
        search_query = resolve_question(question, history, resolve_context, provider=provider)

        facets: List[Dict[str, str]] = []
        decompose_method = "single"
        coverage: List[Dict[str, Any]] = []
        retried_parts: List[str] = []
        parts_checklist = ""

        if (
            _is_multi_part(search_query) or _is_multi_part(question)
        ) and not _is_citation_lookup(search_query) and not _is_citation_lookup(question):
            facets, decompose_method = decompose_question(
                question, search_query, history, resolve_context, provider=provider
            )

        if facets:
            retrieval = retrieve_multi_part(facets, search_query)
            evidence = retrieval["evidence"]
            coverage = retrieval["coverage"]
            retried_parts = retrieval["retried_parts"]
            parts_checklist = build_parts_checklist(facets, coverage)
        else:
            retrieval = retrieve_dual_documents(search_query)
            evidence = select_evidence(retrieval["law"], retrieval["cases"])

        # Web fallback: only when the local indexes leave the question (or a part
        # of it) without authority. Web passages join the same evidence list, so
        # labeling, dedupe and the token budget apply unchanged.
        law_scores = [h["score"] for h in retrieval["law"] if h.get("score") is not None]
        weak_local = (
            not evidence
            or (coverage and any(not item["supported"] for item in coverage))
            or (
                not facets
                and (
                    not law_scores
                    or min(law_scores) > WEB_TRIGGER_DISTANCE
                    or not _local_statutes_on_topic(search_query, retrieval["law"])
                )
            )
        )
        if not weak_local and _repeated_question(session, search_query):
            # The user came back to a question already answered from these
            # authorities: treat it as unsatisfactory and widen the net.
            weak_local = True
        if pakistancode_web.WEB_FALLBACK_ENABLED and weak_local:
            web_queries = [search_query] + [
                facets[i]["query"]
                for i, item in enumerate(coverage)
                if not item["supported"]
            ]
            web_hits = pakistancode_web.search_web_laws(web_queries)
            if web_hits:
                evidence = select_evidence(
                    web_hits + retrieval["law"],
                    retrieval["cases"],
                    max_law=MAX_EVIDENCE_LAW_MULTI if facets else None,
                    max_cases=MAX_EVIDENCE_CASES_MULTI if facets else None,
                )
                if facets:
                    subject_terms = _subject_terms(
                        search_query, *(facet["query"] for facet in facets)
                    )
                    coverage = _facet_coverage(facets, evidence, subject_terms)
                    parts_checklist = build_parts_checklist(facets, coverage)

        retrieved_context = format_evidence(evidence)
        retriever_status = retrieval["status"]
        retrieval_note = retrieval_unavailable_notice(retriever_status)

        stats: Dict[str, Any] = {}
        answer = generate_legal_answer(
            question=question,
            document_context=case_context_text,
            retrieved_context=retrieved_context,
            history=history,
            stats=stats,
            retrieval_note=retrieval_note,
            parts_checklist=parts_checklist,
            provider=provider,
        )

        sources = evidence_labels(evidence)
        session.add_message("user", question)
        session.add_message(
            "assistant",
            answer,
            sources=sources,
            extra={
                "search_query": search_query,
                "context_stats": stats,
                "parts": [item["part"] for item in coverage],
                "llm_provider": provider,
            },
        )

        law_count = sum(1 for item in evidence if item["kind"] == KIND_LAW)
        case_count = len(evidence) - law_count
        stats.update(
            {
                "document_count": len(session.documents),
                "retrieved_count": len(evidence),
                "web_passages": sum(
                    1 for item in evidence if (item["doc"].metadata or {}).get("_web_source")
                ),
                "retrieved_law_count": law_count,
                "retrieved_case_count": case_count,
                "law_candidates": len(retrieval["law"]),
                "case_candidates": len(retrieval["cases"]),
                "retrieval_status": retriever_status,
                "question_parts": [item["part"] for item in coverage],
                "sub_queries": [facet["query"] for facet in facets],
                "parts_coverage": coverage,
                "parts_retried_twice": retried_parts,
                "decompose_method": decompose_method,
                "history_stored_messages": len(session.history),
                "llm_provider": provider,
                "llm_model": provider_model(provider),
            }
        )
        return {
            "answer": answer,
            "search_query": search_query,
            "sources": sources,
            "scores": [round(float(item.get("score") or 0.0), 4) for item in evidence],
            "tool_called": None,
            "is_document_generation": False,
            "generation_result": None,
            "llm_provider": provider,
            "llm_model": provider_model(provider),
            "retrieval_status": retriever_status,
            "question_parts": [item["part"] for item in coverage],
            "parts_coverage": coverage,
            "context_stats": stats,
        }
