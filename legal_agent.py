"""Legal RAG agent for Pakistani criminal law.

The full case history, documents, and reports live in the shared session.
Each Groq request receives only:
- a few recent, length-limited conversation turns,
- compact case facts/summaries plus lexically relevant excerpts,
- a deduplicated, length-limited set of retrieved authorities.

Prompts are trimmed to a token budget and retried with tighter budgets when
Groq reports a TPM/token-limit error.
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
from langchain_core.tools import tool

from case_context import build_case_context
from context_budget import (
    CASE_CONTEXT_TOKEN_BUDGET,
    HISTORY_TOKEN_BUDGET,
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
    count_message_tokens,
    count_tokens,
    history_as_text,
    truncate_chars,
    truncate_to_tokens,
)
from groq_utils import (
    friendly_llm_error,
    get_groq_llm,
    invoke_llm,
    is_retryable_llm_error,
    log_usage,
)
from session_manager import session_manager

load_dotenv(".env")

BASE_DIR = Path(__file__).resolve().parent
CASES_INDEX_PATH = os.getenv("CASES_INDEX_PATH", str(BASE_DIR / "faiss_index_cases"))
LAW_INDEX_PATH = os.getenv("LAW_INDEX_PATH", str(BASE_DIR / "faiss_index_law"))
JUDGMENTS_INDEX_PATH = os.getenv("JUDGMENTS_INDEX_PATH", str(BASE_DIR / "judgments_faiss_index"))

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

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
TOP_K_LAW = _env_int("TOP_K_LAW", TOP_K)
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


@tool
def greet(query: str = "") -> str:
    """
    Call this function whenever the user greets, says hello, hi, hey,
    or asks the agent to greet or say hello.
    """
    for _ in range(10):
        print("hello world")
    return "Tool 'greet' executed: Printed 'hello world' 10 times to stdout."


agent_tools = [greet]
tools_by_name = {"greet": greet}

_embeddings = None
_llm = None
_llm_with_tools = None
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
            store = _load_faiss(path)
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


def get_llm():
    global _llm
    if _llm is None:
        _llm = get_groq_llm(max_tokens=MAX_OUTPUT_TOKENS, temperature=0)
    return _llm


def get_llm_with_tools():
    global _llm_with_tools
    if _llm_with_tools is None:
        base = get_llm()
        try:
            _llm_with_tools = base.bind_tools(agent_tools)
        except Exception:
            _llm_with_tools = base
    return _llm_with_tools


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


def _dedupe_hits(law_hits: List[Dict[str, Any]], cases_hits: List[Dict[str, Any]]) -> Tuple[List[Any], List[Any]]:
    law_unique: List[Any] = []
    cases_unique: List[Any] = []
    seen = set()
    seen_prefixes = set()
    for hit in list(law_hits) + list(cases_hits):
        doc = hit["doc"]
        key = (doc.page_content or "", str(doc.metadata or {}))
        if key in seen:
            continue
        # The same statutory page or headnote often appears in two files.
        prefix = re.sub(r"\W+", "", (doc.page_content or "").lower())[:240]
        if prefix and prefix in seen_prefixes:
            continue
        seen.add(key)
        seen_prefixes.add(prefix)
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
    "STATUTORY / SUBORDINATE LAW PASSAGES (retrieved from the Pakistani Acts index "
    "`faiss_index_law`; these give the text of the law):"
)
CASE_SECTION_HEADING = (
    "CASE-LAW PRECEDENTS (retrieved from the Pakistani judgments index "
    "`faiss_index_cases`; these give how courts applied the law):"
)


def format_evidence(evidence: List[Dict[str, Any]]) -> str:
    """Render the selected passages as two clearly separated groups."""
    if not evidence:
        return "No specific authorities were retrieved from either local legal index."

    blocks: Dict[str, List[str]] = {KIND_LAW: [], KIND_CASES: []}
    for item in evidence:
        blocks[item["kind"]].append(
            "[{0}]\nContent:\n{1}".format(
                get_source_label(item["doc"], item["source_index"], item["kind"]),
                item["content"],
            )
        )

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
    """Tell the model which retriever failed, instead of leaving it unsaid."""
    problems = []
    for kind, info in status.items():
        state = info.get("state")
        if state == "ready":
            continue
        label = "statutes/Acts index" if kind == KIND_LAW else "court judgments index"
        if state == "missing":
            problems.append(
                f"- The {label} (`{info.get('path')}`) is not present, so no "
                f"{'statutory' if kind == KIND_LAW else 'precedent'} passages could be retrieved."
            )
        elif state == "error":
            problems.append(
                f"- The {label} failed to load ({info.get('error')}), so no "
                f"{'statutory' if kind == KIND_LAW else 'precedent'} passages could be retrieved."
            )
    for kind, info in status.items():
        if info.get("last_query_error"):
            label = "statutes/Acts index" if kind == KIND_LAW else "court judgments index"
            problems.append(f"- A search against the {label} failed: {info['last_query_error']}")

    if not problems:
        return ""
    return (
        "RETRIEVER LIMITATIONS (state these plainly in the answer; do not replace the "
        "missing evidence with knowledge from memory):\n" + "\n".join(problems)
    )


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
    law_hits = _search_store(KIND_LAW, query, top_k_law)
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
    r"obligation\w*|penal\w*|punish\w*|validity|principle\w*|provision\w*|"
    r"api\w*|remedy|remedies|differen\w*|eligible|eligibility|how to|how does)\b",
    re.IGNORECASE,
)


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
        llm = get_groq_llm(max_tokens=DECOMPOSE_OUTPUT_TOKENS, temperature=0)
        response = invoke_llm(llm, prompt, label="question decomposition")
        raw = str(getattr(response, "content", "") or "")
        parsed = _finalize_facets(_parse_facets(raw), _subject_of(search_query) or _subject_of(question))
        if parsed:
            return parsed, "groq"
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
    law_pool = _search_store(KIND_LAW, base_query, TOP_K_LAW)
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
                f"{number}. {item['part']} — only loosely related passages ({labels}); "
                "they do not state this aspect, so do not present them as authority for it"
            )
        else:
            lines.append(
                f"{number}. {item['part']} — NO supporting passage was retrieved"
                f" (searched: \"{truncate_chars(item['query'], 120)}\")"
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
        llm = get_groq_llm(max_tokens=RESOLVE_OUTPUT_TOKENS, temperature=0)
        response = invoke_llm(llm, prompt, label="follow-up resolution")
        rewritten = str(getattr(response, "content", "") or "").strip()
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


SYSTEM_PROMPT = """You are a source-grounded legal information assistant for Pakistani criminal law.
You explain the supplied case record and the retrieved Pakistani authorities. You do not
state legal rules, offence classifications, or procedure from memory.

You are an educational assistant, not a substitute for an enrolled Pakistani advocate.
Do not guarantee outcomes.

SOURCE PRIORITY:
1. Uploaded case material is labeled [DOC-n]. It is the case record, not legal authority.
2. Retrieved authorities arrive in two clearly separated groups under
   "RETRIEVED LEGAL SOURCES":
   a. STATUTORY / SUBORDINATE LAW PASSAGES - the text of Pakistani Acts and
      ordinances (PPC, CrPC, and other statutes), from the statutes index.
   b. CASE-LAW PRECEDENTS - reported Pakistani judgments, from the judgments index.
   Each passage carries its own [SOURCE-i] label and a [STATUTE] or [CASE LAW] tag.
   Cite them only with their exact [SOURCE-i] label when the supplied content
   supports the statement.
3. General knowledge may explain a background concept only when it is explicitly
   labeled "General reference (not from the supplied sources)". It must not supply
   statutory numbers, offence classifications, bail rules, or procedure.

HOW TO USE BOTH GROUPS TOGETHER:
- State the rule from a [STATUTE] passage (name the Act and the section number only
  when both appear in that passage's content or label), then show how a [CASE LAW]
  passage applies, interprets, or limits it, and then apply both to the user's facts.
- If only one group answers part of the question, say which part rests on the statute
  and which part has no retrieved precedent (or no retrieved statutory text) instead
  of inventing the missing half.
- Never attribute wording of a judgment to a statute, or wording of a statute to a
  judgment. Keep the two kinds of authority distinct in the answer.

RULES:
- Never cite a [DOC-n] case excerpt as [SOURCE-i]. Mention case material only as
  "the case record (DOC-n)" or by document type.
- A retrieved judgment name (for example, "Inayat vs State") is a legal authority
  [SOURCE-i], never the case record. Refer to it as "[SOURCE-4] Inayat vs State".
- The user's question is not the case record. Never attribute a fact from the
  question to the case record. If no documents were uploaded, begin by saying
  "No case documents are uploaded" and do not use "the case record" for anything
  else.
- A value marked [user-corrected], or listed under USER-CORRECTED VALUES
  (AUTHORITATIVE), replaces the original extraction in every summary and excerpt.
  Always use the corrected value; never revert to the original text.
- Use only [SOURCE-i] labels that appear in RETRIEVED LEGAL SOURCES.
- Never fabricate section numbers, case titles, citations, quotations, or holdings.
- Every statement about what a statutory provision requires, or whether an offence
  is bailable/non-bailable or cognizable/non-cognizable, must be supported by a
  supplied [SOURCE-i] or stated in the case record. If no supplied material
  establishes it, say so instead of relying on memory.
- If a supplied source states a classification or rule, follow that source exactly;
  never override it with general knowledge.
- Do not state what a statutory section says, what its legal test is, or how a
  procedure works unless that description appears in the supplied sources or case
  record. Never fill a gap with a general explanation of bail or criminal procedure.
- A numbered list of steps, requirements or documents may only repeat the items the
  cited passage itself lists. If a passage names an Act, section or right without
  enumerating steps, state exactly that and stop; do not expand the citation into a
  filing procedure from general knowledge.
- If the supplied sources do not identify the offence section or its bail status,
  say that plainly. Do not offer possible section numbers as examples or guesses
  (not even in phrases like "e.g., section ...").
- When the question has several parts, treat each part separately. A gap in one part
  never excuses the others: answer every part that the supplied sources support, and
  state the limitation only for the unsupported part.
- If the supplied sources do not establish one requested rule, do not fill that gap and
  do not give practical next steps for it. For that part, return only: (1) one short
  statement that the supplied material does not establish it, and (2) the specific
  document or material that would be needed. Do not include examples, general law, or
  advice to look up particular section numbers.
- Never add a "practical next steps" section that supplies unsourced legal procedure.
- Do not introduce any statutory section number that is not present in the case
  record or supplied sources, even as an example. Do not describe a section by
  relying on memory.
- This assistant covers Pakistani law. Do not import Indian CrPC 1973 numbering or
  treat non-Pakistani authorities as binding.
- If a retrieved authority is from another jurisdiction, label it as non-Pakistani
  and do not present it as binding Pakistani law.
- Distinguish FIR allegations from facts established by a court.
- Apply the law to the known facts and explicitly state missing facts or limitations.
- If retrieved material does not address part of the question, say so for that part
  only and continue answering the parts it does address.
- Use clear, structured, professional English with short headings and bullet lists
  or compact tables. Be concise and do not repeat the case context.

Suggested structure when the sources answer the question: direct answer, case facts
used, law supported by supplied sources, limitations. Give one heading per requested
part. When the sources do not answer a part, use a short source-limitation statement for
that part only. Omit any section or citation that would require unsourced legal rules or
procedure, but still answer the parts the sources do support.
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
        user_prompt = f"""LATEST USER QUESTION:
{question_text}

COMPACT CASE CONTEXT (full documents are stored separately; excerpts only):
{case_text}

RETRIEVED LEGAL SOURCES:
{sources_text}{note_block}{parts_block}
INSTRUCTIONS:
- Answer the specific question using the case facts above.
- If a PARTS REQUESTED list is given, answer each listed part that has supporting
  sources, under its own heading, and flag only the parts whose evidence is missing.
- Cite retrieved authorities with their exact [SOURCE-i] labels only where they support a claim.
- Use [STATUTE] passages for the wording of the law and [CASE LAW] passages for how the
  courts applied it; keep the two kinds of authority separate and never quote one as the other.
- Treat USER-CORRECTED VALUES as authoritative over any conflicting summary or excerpt.
- Refer to uploaded documents as DOC-n; never label a case excerpt as SOURCE-i.
- If the RETRIEVER LIMITATIONS block says a group of sources was unavailable, say so.
- Do not repeat the case context verbatim. If the sources do not answer a part of the
  question, say so for that part only; do not suggest legal steps or section numbers.
"""
        return [SystemMessage(content=SYSTEM_PROMPT), *history_messages, HumanMessage(content=user_prompt)]

    messages = assemble()
    for _ in range(12):
        total = count_message_tokens(messages)
        if total <= input_budget:
            break
        # Drop the least critical content first: sources, then case facts, then old turns.
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
) -> str:
    """Generate a grounded answer, retrying with tighter context on token errors."""
    llm = get_llm()
    last_error: Optional[BaseException] = None

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
            response = llm.invoke(messages)
            usage = log_usage("legal answer", response)
            content = str(getattr(response, "content", "") or "").strip()
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
            if not is_retryable_llm_error(exc):
                break
            if attempt == 0:
                wait = 6.0 if "rate" in str(exc).lower() else 0.0
                if wait:
                    print(
                        f"[Legal] Groq token/rate limit reached; retrying with 60% context "
                        f"in {wait:.0f}s.",
                        flush=True,
                    )
                    import time

                    time.sleep(wait)
                else:
                    print(
                        "[Legal] Groq rejected the context size; retrying with tighter context.",
                        flush=True,
                    )
            else:
                print("[Legal] Token/rate limit again; retrying with minimum context.", flush=True)

    if stats is not None:
        stats["error"] = type(last_error).__name__ if last_error else "unknown"
    return friendly_llm_error(last_error or RuntimeError("unknown"), context="legal answer")


def is_greeting(text: str) -> bool:
    patterns = [
        r"\b(hello|hi|hey|heyy|heya)\b",
        r"\b(greet|greetings|say hello|say hi|say hey)\b",
        r"\b(good morning|good afternoon|good evening)\b",
        r"\b(salam|assalam|aoa)\b",
    ]
    return any(re.search(pattern, text.lower()) for pattern in patterns)


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


GREETING_ANSWER = (
    "Hello! I am your Pakistani Legal AI Assistant specializing in criminal law, "
    "Pakistani court judgments, and legal document drafting.\n\n"
    "I can help you:\n"
    "• Analyze FIRs, judgments, and legal notices\n"
    "• Research applicable PPC/CrPC provisions and court precedents\n"
    "• Draft and download ready-to-file documents such as bail applications\n\n"
    "How can I assist you with your case today?"
)


def ask_legal_agent(
    question: str,
    session_id: str = "default",
    force_generation: bool = False,
) -> Dict[str, Any]:
    """Run greeting routing, retrieval, and grounded legal reasoning.

    `force_generation` is retained for signature compatibility; live document
    generation is handled by generation_workflow.py before this function.
    """
    if not question or not question.strip():
        return {
            "answer": "Please enter a legal query, greeting, or document drafting instruction.",
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
        tool_called = None
        is_greet = is_greeting(question)

        if is_greet:
            greet.invoke({})
            tool_called = "greet"

        clean = re.sub(r"[^\w\s]", "", question.lower()).strip()
        legal_keywords = [
            "law", "section", "bail", "case", "court", "fir", "theft", "murder",
            "offence", "offense", "punishment", "act", "ppc", "crpc", "judge",
            "crime", "police", "arrest", "rights", "statute", "appeal", "petition",
            "draft", "generate", "quashment", "remand", "notice", "evidence",
            "witness", "trial", "bailable", "cognizable", "sentence", "acquittal",
        ]
        has_substantive = any(keyword in clean for keyword in legal_keywords)

        if is_greet and not has_substantive:
            session.add_message("user", question)
            session.add_message("assistant", GREETING_ANSWER, tool_called=tool_called)
            return {
                "answer": GREETING_ANSWER,
                "search_query": "",
                "sources": [],
                "scores": [],
                "tool_called": tool_called,
                "is_document_generation": False,
                "generation_result": None,
                "context_stats": {"input_estimated": 0},
            }

        case_context_text = build_case_context(
            session,
            question,
            max_tokens=CASE_CONTEXT_TOKEN_BUDGET,
            include_excerpts=True,
        )
        resolve_context = build_case_context(
            session,
            question,
            max_tokens=320,
            include_excerpts=False,
        )
        search_query = resolve_question(question, history, resolve_context)

        facets: List[Dict[str, str]] = []
        decompose_method = "single"
        coverage: List[Dict[str, Any]] = []
        retried_parts: List[str] = []
        parts_checklist = ""

        if _is_multi_part(search_query) or _is_multi_part(question):
            facets, decompose_method = decompose_question(
                question, search_query, history, resolve_context
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
        )

        sources = evidence_labels(evidence)
        session.add_message("user", question)
        session.add_message(
            "assistant",
            answer,
            sources=sources,
            tool_called=tool_called,
            extra={
                "search_query": search_query,
                "context_stats": stats,
                "parts": [item["part"] for item in coverage],
            },
        )

        law_count = sum(1 for item in evidence if item["kind"] == KIND_LAW)
        case_count = len(evidence) - law_count
        stats.update(
            {
                "document_count": len(session.documents),
                "retrieved_count": len(evidence),
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
            }
        )
        return {
            "answer": answer,
            "search_query": search_query,
            "sources": sources,
            "scores": [round(float(item.get("score") or 0.0), 4) for item in evidence],
            "tool_called": tool_called,
            "is_document_generation": False,
            "generation_result": None,
            "retrieval_status": retriever_status,
            "question_parts": [item["part"] for item in coverage],
            "parts_coverage": coverage,
            "context_stats": stats,
        }
