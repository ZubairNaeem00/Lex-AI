"""Load the rebuilt faiss_index_law (raw FAISS + SQLite) as a LangChain store.

The law index now uses Qwen/Qwen3-Embedding-0.6B (1024-dim, unit vectors,
IndexFlatL2). To keep the existing hybrid retrieval, citation anchoring and
distance floors working unchanged, we expose it through the same LangChain FAISS
interface the rest of legal_agent.py expects:

- score stays the squared-L2 distance (cosine = 1 - d/2), exactly as before;
- each chunk becomes a Document carrying statute metadata (act, citation,
  section, source PDF, page) so labels, dedupe and section maps behave the same.
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

_HEADER_PREFIXES = ("Citation:", "Case name:", "Section:")


def _strip_header(text: str) -> str:
    """Remove the builder's 'Citation/Case name/Section' header lines."""
    body = text or ""
    for prefix in _HEADER_PREFIXES:
        if body.startswith(prefix):
            newline = body.find("\n")
            body = body[newline + 1:] if newline >= 0 else ""
    return body.strip()


def build_law_store(path: str) -> Any:
    """Build a LangChain FAISS store from the raw law index folder."""
    import faiss

    folder = Path(path)
    info = json.loads((folder / "run_info.json").read_text(encoding="utf-8"))
    index = faiss.read_index(str(folder / "index.faiss"))

    dimension = int(info.get("embedding_dimension") or index.d)
    if index.d != dimension:
        raise ValueError(
            f"Law index dimension mismatch: index={index.d}, run_info={dimension}."
        )

    device = os.getenv("LAW_EMBEDDING_DEVICE", "cpu")
    embeddings = Qwen3Embeddings(
        model_name=info["model_name"],
        query_prompt=info.get("query_prompt", ""),
        device=device,
        max_seq_length=int(info.get("max_seq_length", 2048)),
    )

    database = f"file:{folder / 'metadata.sqlite3'}?mode=ro"
    connection = sqlite3.connect(database, uri=True)
    try:
        statutes: Dict[int, Dict[str, Any]] = {}
        for row in connection.execute(
            "SELECT case_id, act_title, act_no, year, section_no, kind, status, "
            "source_pdf, page_start, page_end FROM statute_sections"
        ):
            statutes[int(row[0])] = {
                "act_title": row[1], "act_no": row[2], "year": row[3],
                "section_no": row[4], "kind": row[5], "status": row[6],
                "source_pdf": row[7], "page_start": row[8], "page_end": row[9],
            }

        docstore: Dict[str, Document] = {}
        index_to_docstore_id: Dict[int, str] = {}
        for vector_id, case_id, citation, case_name, source_field, page_content in connection.execute(
            "SELECT vector_id, case_id, citation, case_name, source_field, page_content FROM chunks"
        ):
            vector_id = int(vector_id)
            case_id = int(case_id)
            statute = statutes.get(case_id, {})
            section_no = str(statute.get("section_no") or "").strip()
            act_title = str(statute.get("act_title") or "").strip()
            page_start = statute.get("page_start")
            metadata = {
                "_retriever_kind": "law",
                "act_name": act_title or str(case_name or "").strip(),
                "citation": str(citation or "").strip(),
                "section_number": section_no,
                "section": section_no,
                "source": str(statute.get("source_pdf") or "").strip(),
                "page_label": str(page_start) if page_start is not None else "",
                "year": statute.get("year"),
                "statute_kind": statute.get("kind"),
                "status": statute.get("status"),
                "source_field": source_field,
                "case_id": case_id,
                "vector_id": vector_id,
            }
            doc_id = str(vector_id)
            docstore[doc_id] = Document(
                page_content=_strip_header(page_content), metadata=metadata
            )
            index_to_docstore_id[vector_id] = doc_id
    finally:
        connection.close()

    if len(index_to_docstore_id) != index.ntotal:
        raise ValueError(
            f"Law index/metadata mismatch: {index.ntotal} vectors vs "
            f"{len(index_to_docstore_id)} chunk rows."
        )

    return FAISS(
        embedding_function=embeddings,
        index=index,
        docstore=InMemoryDocstore(docstore),
        index_to_docstore_id=index_to_docstore_id,
    )
