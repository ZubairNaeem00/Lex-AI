"""Similar-case search over the prebuilt faiss_case_retrieval index.

Retrieval is LLM-free: the query is embedded with the same model that built the
index, FAISS returns the nearest chunks, and the original case records are read
back from metadata.sqlite3. Nothing is summarised or rewritten.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

INDEX_DIR = Path(os.getenv("CASE_RETRIEVAL_INDEX_DIR", str(Path(__file__).parent / "faiss_case_retrieval")))
DEFAULT_K = 5
MAX_K = 20
CANDIDATES_PER_CASE = 10

_state: Dict[str, Any] = {}
_lock = threading.Lock()


class CaseRetrievalError(RuntimeError):
    """The index or the embedding model could not be used."""


def _resources() -> Dict[str, Any]:
    """Load the index, metadata store and embedding model once, on first use."""
    with _lock:
        if _state:
            return _state
        try:
            import faiss
            from qwen_embeddings import get_qwen_model

            info = json.loads((INDEX_DIR / "run_info.json").read_text(encoding="utf-8"))
            index = faiss.read_index(str(INDEX_DIR / "index.faiss"))
            model = get_qwen_model(
                info["model_name"], device="cpu",
                max_seq_length=int(info.get("max_seq_length", 2048)),
            )
        except Exception as exc:
            raise CaseRetrievalError(
                f"Case index unavailable ({type(exc).__name__}: {exc}). "
                f"Expected a complete index in {INDEX_DIR}."
            ) from exc
        _state.update(
            index=index,
            model=model,
            info=info,
            database=str(INDEX_DIR / "metadata.sqlite3"),
        )
        print(
            f"[Cases] index ready: {info['total_cases']:,} cases / {index.ntotal:,} vectors "
            f"({info['model_name']})",
            flush=True,
        )
        return _state


def _connect(database: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{database}?mode=ro", uri=True)


def _stitch(rows: List[Tuple[int, int, str]]) -> str:
    """Rebuild one section from its overlapping chunks.

    Every chunk body is an exact substring of the source section at a known
    character offset, so placing the bodies by offset restores the original text
    without repeating the overlap.
    """
    pieces: List[str] = []
    covered = 0
    for start, end, content in rows:
        if end <= start:
            continue
        body = content[len(content) - (end - start):]
        if start >= covered:
            pieces.append(body)
        elif end > covered:
            pieces.append(body[covered - start:])
        covered = max(covered, end)
    return "".join(pieces)


def _case_record(connection: sqlite3.Connection, case_id: int, score: float, section: str) -> Dict[str, Any]:
    citation, case_name, chunk_count = connection.execute(
        "SELECT citation, case_name, chunk_count FROM cases WHERE case_id = ?", (case_id,)
    ).fetchone()
    rows = connection.execute(
        "SELECT source_field, chunk_char_start, chunk_char_end, page_content "
        "FROM chunks WHERE case_id = ? ORDER BY chunk_char_start",
        (case_id,),
    ).fetchall()
    sections = {
        field: _stitch([(start, end, content) for name, start, end, content in rows if name == field])
        for field in ("summary", "case_description")
    }
    return {
        "case_id": int(case_id),
        "citation": citation or "",
        "case_name": case_name or "",
        "summary": sections["summary"],
        "description": sections["case_description"],
        "matched_section": section,
        "chunk_count": int(chunk_count),
        "score": round(score, 4),
    }


def retrieve_similar_cases(query: str, k: int = DEFAULT_K) -> Dict[str, Any]:
    """Return the k most similar Pakistani court cases, as original full records."""
    text = " ".join(str(query or "").split())
    if not text:
        raise CaseRetrievalError("A search query is required.")
    k = max(1, min(int(k or DEFAULT_K), MAX_K))

    resources = _resources()
    index, info = resources["index"], resources["info"]
    vector = resources["model"].encode(
        [str(info.get("query_prompt", "")) + text],
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    pool = min(index.ntotal, max(k * CANDIDATES_PER_CASE, 40))
    distances, vector_ids = index.search(vector, pool)
    candidates = [int(item) for item in vector_ids[0] if item >= 0]
    if not candidates:
        return {"query": text, "k": k, "count": 0, "cases": []}

    with _connect(resources["database"]) as connection:
        marks = ",".join("?" * len(candidates))
        owner = {
            int(vector_id): (int(case_id), str(field))
            for vector_id, case_id, field in connection.execute(
                f"SELECT vector_id, case_id, source_field FROM chunks WHERE vector_id IN ({marks})",
                candidates,
            )
        }
        picked: List[Tuple[int, float, str]] = []
        seen = set()
        for distance, vector_id in zip(distances[0], vector_ids[0]):
            match = owner.get(int(vector_id))
            if match is None or match[0] in seen:
                continue
            seen.add(match[0])
            # IndexFlatL2 on unit vectors: cosine similarity = 1 - distance / 2.
            picked.append((match[0], 1.0 - float(distance) / 2.0, match[1]))
            if len(picked) >= k:
                break
        cases = [_case_record(connection, case_id, score, section) for case_id, score, section in picked]

    return {
        "query": text,
        "k": k,
        "count": len(cases),
        "cases": cases,
        "index": {
            "total_cases": info.get("total_cases"),
            "total_vectors": info.get("total_vectors"),
            "model": info.get("model_name"),
        },
    }