"""Load the prebuilt faiss_case_retrieval (raw FAISS + SQLite) as a LangChain store.

The case index uses Qwen/Qwen3-Embedding-0.6B (1024-dim, unit vectors, IndexFlatL2),
the same model as the law index, so the shared Qwen instance serves both. We expose
it through the LangChain FAISS interface legal_agent.py expects:

- score stays the squared-L2 distance (cosine = 1 - d/2), exactly as before;
- each chunk becomes a Document carrying case metadata (case_name, citation) so
  labels, dedupe and evidence selection behave unchanged;
- the chunk's original header (Citation / Case name / Section) is kept in page_content
  so BM25 can match citations and party names lexically, not just semantically.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict

from langchain_core.documents import Document
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS

from qwen_embeddings import Qwen3Embeddings


def build_case_store(path: str) -> Any:
    """Build a LangChain FAISS store from the raw case index folder."""
    import faiss

    folder = Path(path)
    info = json.loads((folder / "run_info.json").read_text(encoding="utf-8"))
    index = faiss.read_index(str(folder / "index.faiss"))

    dimension = int(info.get("embedding_dimension") or index.d)
    if index.d != dimension:
        raise ValueError(
            f"Case index dimension mismatch: index={index.d}, run_info={dimension}."
        )

    device = os.getenv("CASE_EMBEDDING_DEVICE", "cpu")
    embeddings = Qwen3Embeddings(
        model_name=info["model_name"],
        query_prompt=info.get("query_prompt", ""),
        device=device,
        max_seq_length=int(info.get("max_seq_length", 2048)),
    )

    database = f"file:{folder / 'metadata.sqlite3'}?mode=ro"
    connection = sqlite3.connect(database, uri=True)
    docstore: Dict[str, Document] = {}
    index_to_docstore_id: Dict[int, str] = {}
    try:
        for vector_id, case_id, citation, case_name, source_field, page_content in connection.execute(
            "SELECT vector_id, case_id, citation, case_name, source_field, page_content FROM chunks"
        ):
            vector_id = int(vector_id)
            doc_id = str(vector_id)
            metadata = {
                "_retriever_kind": "cases",
                "type": "case_law",
                "case_name": str(case_name or "").strip(),
                "citation": str(citation or "").strip(),
                "source_field": source_field,
                "case_id": int(case_id),
                "vector_id": vector_id,
            }
            docstore[doc_id] = Document(page_content=page_content or "", metadata=metadata)
            index_to_docstore_id[vector_id] = doc_id
    finally:
        connection.close()

    if len(index_to_docstore_id) != index.ntotal:
        raise ValueError(
            f"Case index/metadata mismatch: {index.ntotal} vectors vs "
            f"{len(index_to_docstore_id)} chunk rows."
        )

    return FAISS(
        embedding_function=embeddings,
        index=index,
        docstore=InMemoryDocstore(docstore),
        index_to_docstore_id=index_to_docstore_id,
    )