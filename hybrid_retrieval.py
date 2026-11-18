"""Hybrid retrieval: BM25 keyword search fused with the existing FAISS indexes.

The FAISS indexes are reused as-is. BM25 is built once from the same docstore
chunks and cached on disk, so startup stays fast. Rankings from both retrievers
are merged with weighted Reciprocal Rank Fusion (RRF), which needs no score
normalization. Every returned hit keeps its true FAISS L2 distance as `score`,
so downstream distance floors and margins behave exactly as before.
"""

import os
import pickle
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = Path(os.getenv("BM25_CACHE_DIR", str(BASE_DIR / "bm25_cache")))

HYBRID_ENABLED = os.getenv("HYBRID_ENABLED", "1").strip().lower() not in ("0", "false", "no")
SEMANTIC_WEIGHT = float(os.getenv("HYBRID_SEMANTIC_WEIGHT", "0.6"))
KEYWORD_WEIGHT = float(os.getenv("HYBRID_KEYWORD_WEIGHT", "0.4"))
RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
CANDIDATE_MULTIPLIER = int(os.getenv("HYBRID_CANDIDATE_MULTIPLIER", "4"))
MIN_CANDIDATES = 30

_entries: Dict[str, Any] = {}
_lock = threading.Lock()


def _doc_key(doc: Any) -> Tuple[str, str]:
    return doc.page_content or "", str(doc.metadata or {})


def _tokenize(texts):
    import bm25s

    return bm25s.tokenize(texts, stopwords="en", stemmer=None, show_progress=False)


def _build_entry(kind: str, store: Any):
    import bm25s

    docstore = store.docstore._dict
    ids = list(docstore.keys())
    texts = [docstore[doc_id].page_content or "" for doc_id in ids]
    print(f"Building BM25 {kind} index over {len(ids):,} chunks...", flush=True)
    tokens = _tokenize(texts)
    bm25 = bm25s.BM25()
    bm25.index(tokens, show_progress=False)
    del tokens, texts

    cache_dir = CACHE_DIR / kind
    cache_dir.mkdir(parents=True, exist_ok=True)
    bm25.save(str(cache_dir), show_progress=False)
    with open(cache_dir / "corpus.pkl", "wb") as handle:
        pickle.dump({"ntotal": store.index.ntotal, "ids": ids}, handle)
    print(f"BM25 {kind} index ready and cached at '{cache_dir}'.", flush=True)
    return bm25, ids


def _get_entry(kind: str, store: Any):
    if kind in _entries:
        return _entries[kind]
    with _lock:
        if kind in _entries:
            return _entries[kind]
        import bm25s

        cache_dir = CACHE_DIR / kind
        meta_path = cache_dir / "corpus.pkl"
        bm25 = ids = None
        if meta_path.exists():
            try:
                with open(meta_path, "rb") as handle:
                    meta = pickle.load(handle)
                if meta.get("ntotal") == store.index.ntotal:
                    bm25 = bm25s.BM25.load(str(cache_dir))
                    ids = meta["ids"]
                    print(f"BM25 {kind} index loaded from cache ({len(ids):,} chunks).", flush=True)
            except Exception as exc:
                print(f"BM25 {kind} cache unreadable ({exc}); rebuilding.", flush=True)
        if bm25 is None:
            bm25, ids = _build_entry(kind, store)
        docid_to_row = {doc_id: row for row, doc_id in store.index_to_docstore_id.items()}
        _entries[kind] = (bm25, ids, docid_to_row)
        return _entries[kind]


def _l2_distance(store: Any, query_vec: np.ndarray, row: int) -> float:
    vec = store.index.reconstruct(row)
    return float(np.sum((query_vec - vec) ** 2))


def hybrid_search(
    kind: str, store: Any, query: str, top_k: int
) -> Optional[List[Tuple[Any, float]]]:
    """Fuse FAISS and BM25 rankings; returns (doc, faiss_l2_distance) pairs.

    Returns None when hybrid search cannot run, so the caller can fall back to
    plain FAISS without interrupting the pipeline.
    """
    if not HYBRID_ENABLED or store is None or top_k <= 0:
        return None
    try:
        bm25, ids, docid_to_row = _get_entry(kind, store)
        n_candidates = max(MIN_CANDIDATES, top_k * CANDIDATE_MULTIPLIER)

        sem_pairs = store.similarity_search_with_score(query, k=n_candidates)
        query_tokens = _tokenize([query])
        bm25_rows, bm25_scores = bm25.retrieve(query_tokens, k=n_candidates, show_progress=False)

        fused: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for rank, (doc, distance) in enumerate(sem_pairs, start=1):
            fused[_doc_key(doc)] = {
                "doc": doc,
                "distance": float(distance),
                "rrf": SEMANTIC_WEIGHT / (RRF_K + rank),
            }

        embed = store.embedding_function
        embed_query = embed.embed_query if hasattr(embed, "embed_query") else embed
        query_vec = np.asarray(embed_query(query), dtype=np.float32)
        docstore = store.docstore._dict
        for rank, (row_idx, score) in enumerate(
            zip(bm25_rows[0], bm25_scores[0]), start=1
        ):
            if score <= 0:
                continue
            doc_id = ids[int(row_idx)]
            doc = docstore[doc_id]
            key = _doc_key(doc)
            weight = KEYWORD_WEIGHT / (RRF_K + rank)
            if key in fused:
                fused[key]["rrf"] += weight
            else:
                fused[key] = {
                    "doc": doc,
                    "distance": _l2_distance(store, query_vec, docid_to_row[doc_id]),
                    "rrf": weight,
                }

        ordered = sorted(fused.values(), key=lambda item: item["rrf"], reverse=True)
        return [(item["doc"], item["distance"]) for item in ordered[:top_k]]
    except Exception as exc:
        print(f"Hybrid {kind} search failed ({type(exc).__name__}: {exc}); using FAISS only.", flush=True)
        return None