"""Build a resumable, chunk-based FAISS index for Pakistani legal cases  (v2.1).

This is a patched version of legal_case_index_builder_v2/build_index.py.
Every changed region is tagged  [v2.1 FIX n]  -- search for "v2.1 FIX" to see them all.
The change list with the reason for each fix is in README.md.

Default input:  cases_cleaned.json
Default output: faiss_index_cases_cleaned

Typical order of use (see README.md for the full Windows runbook):
  1. python build_index.py --dry-run                      # CPU only: exact chunk counts, no GPU, no index written
  2. python build_index.py --max-cases 100 --index-folder ..._test --checkpoint-folder ..._test
  3. python build_index.py                                # full build; re-run the SAME command after any interruption
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
from tqdm import tqdm

from legal_index_common import (
    EXPECTED_EMBEDDING_DIM,
    INDEX_FORMAT_VERSION,
    MODEL_NAME,
    QUERY_PROMPT,
    atomic_write_json,
    fsync_file,
    library_versions,
    normalize_citation,
    sha256_file,
    unit_normalize,
)

# ---------------------------- CONFIGURATION ----------------------------
DEVICE = "cuda"                 # This project was benchmarked on an RTX A2000 (4 GB).
DEFAULT_CUDA_DTYPE = "float16"  # [v2.1 FIX 4] now selectable with --dtype; see compare_dtypes.py
BATCH_SIZE = 1                  # Best measured throughput on the user's 4 GB GPU (v1 benchmarks).
MAX_SEQ_LENGTH = 2048           # Model input limit used for this run.
CHUNK_TOKENS = 1500             # Body tokens per chunk; leaves room for case/citation headers.
CHUNK_OVERLAP = 150             # Repeats nearby context across chunk boundaries.
CHECKPOINT_CASES = 100          # Persist progress after every 100 source cases.
ENCODE_SLICE = 32               # [v2.1 FIX 3] texts per encode() call: progress heartbeat + OOM isolation
JSON_READ_CHARS = 1024 * 1024
HEADER_CITATION_TOKENS = 40     # [v2.1 FIX 2] each header field is capped on its own ...
HEADER_NAME_TOKENS = 96         # ... so a long case name can never push the citation out.
MANIFEST_VERSION = 3
DOCUMENT_FORMAT_VERSION = 4     # [v2.1 FIX 2/5] text construction changed -> old checkpoints are refused
                                # [v2.1.1] 4: all source text is NFC-normalised (see json_value_to_text)

CHUNK_COLUMNS = (
    "vector_id", "case_id", "citation", "case_name", "source_field", "chunk_id", "chunk_count",
    "section_chunk_id", "section_chunk_count", "chunk_token_start", "chunk_token_end",
    "page_content", "chunk_char_start", "chunk_char_end", "chunk_input_tokens",
)


class EmbeddingOOMError(RuntimeError):
    """Raised when the GPU cannot embed a chunk even after retries. Checkpoints stay valid."""


# ---------------------------- JSON / FILE HELPERS ----------------------------
def iter_json_array(path: Path, read_chars: int = JSON_READ_CHARS) -> Iterator[Any]:
    """Stream one object at a time from a top-level JSON array.

    Unchanged from v2 (stress-tested in the v2.1 audit against json.load at buffer sizes
    256 chars .. 1 MiB, with BOM, unicode, brackets/quotes inside strings, and five kinds of
    malformed input -- all handled correctly).
    """
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8-sig") as handle:
        buffer = handle.read(read_chars)
        position = 0
        eof = False

        def fill_buffer() -> None:
            nonlocal buffer, eof
            piece = handle.read(read_chars)
            if piece:
                buffer += piece
            else:
                eof = True

        while True:
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position < len(buffer):
                break
            if eof:
                raise ValueError("The JSON file is empty or incomplete; expected a top-level array.")
            buffer = buffer[position:]
            position = 0
            fill_buffer()

        if buffer[position] != "[":
            raise ValueError("Expected cases_cleaned.json to contain a top-level JSON array ([...]).")
        position += 1
        first_item = True

        while True:
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer):
                    break
                if eof:
                    raise ValueError("Unexpected end of file before the closing ] of the JSON array.")
                buffer = buffer[position:]
                position = 0
                fill_buffer()

            if first_item:
                if buffer[position] == "]":
                    position += 1
                    break
            else:
                if buffer[position] == "]":
                    position += 1
                    break
                if buffer[position] != ",":
                    raise ValueError(
                        f"Invalid JSON array: expected ',' or ']' near character {position}."
                    )
                position += 1
                while True:
                    while position < len(buffer) and buffer[position].isspace():
                        position += 1
                    if position < len(buffer):
                        break
                    if eof:
                        raise ValueError("Unexpected end of file after a comma in the JSON array.")
                    buffer = buffer[position:]
                    position = 0
                    fill_buffer()
                if buffer[position] == "]":
                    raise ValueError("Invalid JSON array: trailing comma before ']' is not allowed.")

            while True:
                try:
                    item, end_position = decoder.raw_decode(buffer, position)
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise ValueError(
                            f"Invalid or incomplete JSON record near character {position}: {exc}"
                        ) from exc
                    if position > 0:
                        buffer = buffer[position:]
                        position = 0
                    fill_buffer()

            yield item
            position = end_position
            first_item = False

            if position >= read_chars:
                buffer = buffer[position:]
                position = 0

        trailing = buffer[position:]
        if trailing.strip():
            raise ValueError("Unexpected content after the top-level JSON array.")
        while not eof:
            piece = handle.read(read_chars)
            if not piece:
                eof = True
            elif piece.strip():
                raise ValueError("Unexpected content after the top-level JSON array.")


def count_cases(path: Path) -> int:
    count = 0
    for row_number, case in enumerate(iter_json_array(path), start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Record {row_number} is not a JSON object.")
        count += 1
    return count


def json_value_to_text(value: Any) -> str:
    """Source field -> text.  [v2.1.1] The result is Unicode NFC-normalised.

    Qwen's tokenizer normalises text to NFC internally (e.g. ARABIC ALEF + MADDAH ABOVE becomes the single
    letter ALEF WITH MADDAH ABOVE). Without this, the character-offset coverage check reported the combining
    mark as 'not covered' and the strict build refused to continue, although nothing is lost to the model.
    Normalising first makes offsets and text agree and is exactly what the model would see anyway. Stored
    chunk text and chunk_char_start/end therefore refer to the NFC-normalised text.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value).strip()
    return unicodedata.normalize("NFC", text)


def grouped_cases(path: Path, group_size: int, selected_cases: int) -> Iterator[Tuple[int, List[Dict[str, Any]]]]:
    """Yield (starting case_id, cases) groups without loading the full dataset."""
    iterator = iter_json_array(path)
    case_id = 0
    while case_id < selected_cases:
        batch = list(islice(iterator, min(group_size, selected_cases - case_id)))
        if not batch:
            break
        for offset, case in enumerate(batch):
            if not isinstance(case, dict):
                raise ValueError(f"Record {case_id + offset + 1} is not a JSON object.")
        yield case_id, batch
        case_id += len(batch)


def remove_tree(path: Path, attempts: int = 5) -> None:
    """[v2.1 FIX 9] rmtree with retries: Windows antivirus/indexers can briefly lock new files."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(1 + attempt)


# ---------------------------- MODEL / TOKENIZER ----------------------------
def resolve_dtype_name(device: str, requested: Optional[str]) -> str:
    if device != "cuda":
        if requested not in (None, "float32"):
            print(f"Note: --dtype {requested} ignored on CPU; using float32.")
        return "float32"
    return requested or DEFAULT_CUDA_DTYPE


def load_model(device: str, dtype_name: str, revision: Optional[str] = None):
    import torch
    from sentence_transformers import SentenceTransformer

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "DEVICE is set to CUDA, but PyTorch cannot see a CUDA GPU. "
            "Run python check_gpu.py and check your CUDA-enabled PyTorch installation."
        )
    dtype = getattr(torch, dtype_name)
    print(f"Loading {MODEL_NAME} on {device} as {dtype_name}...")
    kwargs: Dict[str, Any] = {"device": device, "model_kwargs": {"torch_dtype": dtype}}
    if revision:
        kwargs["revision"] = revision
    model = SentenceTransformer(MODEL_NAME, **kwargs)
    model.max_seq_length = MAX_SEQ_LENGTH

    if not hasattr(model, "tokenizer") or model.tokenizer is None:
        raise RuntimeError("Could not access the SentenceTransformer tokenizer for safe chunking.")
    require_fast_tokenizer(model.tokenizer)

    # [v2.1 FIX 4] v2 never confirmed the requested dtype was actually applied.
    try:
        actual = str(next(model.parameters()).dtype).replace("torch.", "")
    except Exception:
        actual = None
    if actual is not None and actual != dtype_name:
        raise RuntimeError(f"Requested {dtype_name} weights but the model loaded as {actual}.")
    if device == "cuda":
        print(f"Model weights resident on GPU: {torch.cuda.memory_allocated() / 1024 ** 3:.2f} GiB ({actual})")
    return model


def load_tokenizer(revision: Optional[str] = None):
    """Tokenizer only (no weights, no GPU) -- used by --dry-run."""
    from transformers import AutoTokenizer

    kwargs: Dict[str, Any] = {}
    if revision:
        kwargs["revision"] = revision
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, **kwargs)
    require_fast_tokenizer(tokenizer)
    return tokenizer


def require_fast_tokenizer(tokenizer: Any) -> None:
    # [v2.1 FIX 5] character offsets (needed for lossless chunk slicing) exist only on fast tokenizers.
    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError(
            "A fast (Rust) tokenizer is required for exact chunk boundaries. "
            "Update `transformers`/`tokenizers`, or report this if it persists."
        )


# ---------------------------- CHUNKING ----------------------------
def encode_with_offsets(tokenizer: Any, text: str) -> Tuple[List[int], List[Tuple[int, int]]]:
    encoded = tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
    return list(encoded["input_ids"]), [(int(a), int(b)) for a, b in encoded["offset_mapping"]]


def count_tokens(tokenizer: Any, text: str, special_tokens: bool) -> int:
    return len(tokenizer(text, add_special_tokens=special_tokens, truncation=False)["input_ids"])


def clip_to_tokens(tokenizer: Any, text: str, max_tokens: int) -> Tuple[str, bool]:
    """Clip on a token boundary using character offsets (never splits a multibyte character)."""
    ids, offsets = encode_with_offsets(tokenizer, text)
    if len(ids) <= max_tokens:
        return text, False
    return text[: offsets[max_tokens - 1][1]].rstrip() + " ...", True


def build_header(tokenizer: Any, citation: str, case_name: str) -> Tuple[str, bool]:
    """[v2.1 FIX 2] Citation FIRST, and each field capped independently.

    v2 put the case name first and cut the whole header at 128 tokens, so a very long
    multi-party case name silently removed the citation line from the embedded text.
    """
    citation_text, clipped_c = clip_to_tokens(tokenizer, " ".join(citation.split()) or "Not provided", HEADER_CITATION_TOKENS)
    name_text, clipped_n = clip_to_tokens(tokenizer, " ".join(case_name.split()) or "Not provided", HEADER_NAME_TOKENS)
    return f"Citation: {citation_text}\nCase name: {name_text}\n", (clipped_c or clipped_n)


def uncovered_characters(text: str, offsets: Sequence[Tuple[int, int]]) -> int:
    """Count non-whitespace characters of `text` that no token offset covers (would be silently lost)."""
    if not offsets:
        return len(text.strip())
    lost = 0
    cursor = 0
    for start, end in offsets:
        if start > cursor:
            lost += len(text[cursor:start].strip())
        cursor = max(cursor, end)
    lost += len(text[cursor:].strip())
    return lost


def make_case_chunks(
    case: Dict[str, Any],
    case_id: int,
    tokenizer: Any,
    strict: bool = True,
) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, Any]]:
    """Build token-bounded, overlapping documents for a single case.

    Returns (texts, metadata_rows, info). `info` carries diagnostics used by --dry-run.

    [v2.1 FIX 5] Chunk bodies are sliced from the ORIGINAL string using token character
    offsets, instead of decoding a token slice back to text. v2's decode-slicing could cut a
    multibyte character in half (byte-level BPE) and emit U+FFFD at chunk edges; this cannot.
    Every chunk body is an exact substring of the source section, and a coverage check
    refuses to continue if any non-whitespace source character would not appear in a chunk.
    """
    case_name = json_value_to_text(case.get("case_name"))
    citation = json_value_to_text(case.get("citation"))
    summary = json_value_to_text(case.get("summary"))
    description = json_value_to_text(case.get("case_description"))

    header, header_clipped = build_header(tokenizer, citation, case_name)
    info: Dict[str, Any] = {"header_clipped": header_clipped, "uncovered_chars": 0}

    sections = [("summary", summary), ("case_description", description)]
    documents: List[str] = []
    metadata_rows: List[Dict[str, Any]] = []

    for section_name, section_text in sections:
        if not section_text:
            continue

        prefix = header + f"Section: {section_name}\n"
        prefix_token_count = count_tokens(tokenizer, prefix, special_tokens=False)
        token_budget = min(CHUNK_TOKENS, MAX_SEQ_LENGTH - prefix_token_count - 32)
        if token_budget <= CHUNK_OVERLAP:
            raise ValueError(f"Case {case_id}: case name/citation header leaves too little room for text chunks.")

        body_ids, offsets = encode_with_offsets(tokenizer, section_text)
        if not body_ids:
            continue

        lost = uncovered_characters(section_text, offsets)
        if lost:
            info["uncovered_chars"] += lost
            if strict:
                raise RuntimeError(
                    f"Case {case_id}, section {section_name}: {lost} source characters are not covered by any "
                    "token offset and would be silently lost. Run --dry-run to survey the dataset for this."
                )

        start = 0
        section_chunks: List[Tuple[str, int, int, int, int, int]] = []
        while start < len(body_ids):
            end = min(start + token_budget, len(body_ids))

            while end > start:
                char_start, char_end = offsets[start][0], offsets[end - 1][1]
                chunk_text = prefix + section_text[char_start:char_end]
                final_token_count = count_tokens(tokenizer, chunk_text, special_tokens=True)
                if final_token_count <= MAX_SEQ_LENGTH:
                    break
                end -= max(1, final_token_count - MAX_SEQ_LENGTH)

            if end <= start:
                raise RuntimeError(f"Could not fit a text chunk for case {case_id}, section {section_name}.")

            section_chunks.append((chunk_text, start, end, char_start, char_end, final_token_count))
            if end >= len(body_ids):
                break
            start = max(start + 1, end - CHUNK_OVERLAP)

        # Coverage self-check: chunks must chain together and span the whole section.
        if section_chunks[0][3] > offsets[0][0] or section_chunks[-1][4] < offsets[-1][1]:
            raise RuntimeError(f"Case {case_id}, section {section_name}: chunks do not span the full section.")
        for previous, current in zip(section_chunks, section_chunks[1:]):
            if current[3] > previous[4]:
                raise RuntimeError(f"Case {case_id}, section {section_name}: gap between consecutive chunks.")

        total_section_chunks = len(section_chunks)
        for number, (chunk_text, token_start, token_end, char_start, char_end, input_tokens) in enumerate(section_chunks):
            documents.append(chunk_text)
            metadata_rows.append(
                {
                    "case_id": int(case_id),
                    "citation": citation,
                    "case_name": case_name,
                    "source_field": section_name,
                    "section_chunk_id": int(number),
                    "section_chunk_count": int(total_section_chunks),
                    "chunk_token_start": int(token_start),
                    "chunk_token_end": int(token_end),
                    "chunk_char_start": int(char_start),
                    "chunk_char_end": int(char_end),
                    "chunk_input_tokens": int(input_tokens),
                }
            )

    # Keep even a sparse record searchable, rather than silently dropping it.
    if not documents:
        fallback = header + "No summary or case description was provided in the source record."
        documents.append(fallback)
        metadata_rows.append(
            {
                "case_id": int(case_id),
                "citation": citation,
                "case_name": case_name,
                "source_field": "empty_record",
                "section_chunk_id": 0,
                "section_chunk_count": 1,
                "chunk_token_start": 0,
                "chunk_token_end": 0,
                "chunk_char_start": 0,
                "chunk_char_end": 0,
                "chunk_input_tokens": count_tokens(tokenizer, fallback, special_tokens=True),
            }
        )

    total_case_chunks = len(metadata_rows)
    for chunk_id, metadata in enumerate(metadata_rows):
        metadata["chunk_id"] = int(chunk_id)
        metadata["chunk_count"] = int(total_case_chunks)

    return documents, metadata_rows, info


def metadata_problem(metadata_rows: Sequence[Dict[str, Any]], first_case_id: int, last_case_id_exclusive: int) -> Optional[str]:
    """[v2.1 FIX 6] Every case in the group must be present, with chunk ids 0..n-1 and consistent counts."""
    per_case: Dict[int, List[Dict[str, Any]]] = {}
    for row in metadata_rows:
        per_case.setdefault(int(row["case_id"]), []).append(row)
    expected = set(range(first_case_id, last_case_id_exclusive))
    if set(per_case) != expected:
        missing = sorted(expected - set(per_case))[:5]
        extra = sorted(set(per_case) - expected)[:5]
        return f"case ids do not match the group (missing {missing}, unexpected {extra})"
    for case_id, rows in per_case.items():
        ids = [int(r["chunk_id"]) for r in rows]
        if ids != list(range(len(rows))) or any(int(r["chunk_count"]) != len(rows) for r in rows):
            return f"case {case_id}: chunk ids/counts are inconsistent"
    return None


# ---------------------------- CHECKPOINTS ----------------------------
def checkpoint_paths(checkpoint_dir: Path, checkpoint_number: int) -> Tuple[Path, Path, Path]:
    stem = f"group_{checkpoint_number:05d}"
    return (
        checkpoint_dir / f"{stem}_vectors.npy",
        checkpoint_dir / f"{stem}_docs.jsonl",
        checkpoint_dir / f"{stem}.done.json",
    )


def read_checkpoint_documents(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    texts: List[str] = []
    metadata_rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            texts.append(row["text"])
            metadata_rows.append(row["metadata"])
    return texts, metadata_rows


def checkpoint_problem(
    checkpoint_dir: Path,
    checkpoint_number: int,
    manifest_fingerprint: str,
    deep: bool = False,
) -> Optional[str]:
    """Return None if the checkpoint is usable, else a human-readable reason.

    [v2.1 FIX 6] v2 returned a bare True/False and recomputed silently. This version
    (a) says why, (b) checks file sizes recorded at write time, and (c) with deep=True also
    verifies SHA-256 of both data files, the finite/unit-norm property of every vector, and
    that every case in the group is present with consistent chunk numbering.
    """
    vector_path, docs_path, done_path = checkpoint_paths(checkpoint_dir, checkpoint_number)
    if not done_path.exists():
        return "no completion marker"
    if not vector_path.exists() or not docs_path.exists():
        return "data file missing"
    try:
        with done_path.open("r", encoding="utf-8") as handle:
            marker = json.load(handle)
        if marker.get("manifest_fingerprint") != manifest_fingerprint:
            return "belongs to a different dataset/configuration"
        if int(marker.get("checkpoint_number", -1)) != checkpoint_number:
            return "checkpoint number mismatch"
        if vector_path.stat().st_size != int(marker.get("vectors_file_bytes", -1)):
            return "vectors file size differs from the recorded size (truncated or modified)"
        if docs_path.stat().st_size != int(marker.get("docs_file_bytes", -1)):
            return "documents file size differs from the recorded size (truncated or modified)"
        vectors = np.load(vector_path, mmap_mode=None if deep else "r")
        if vectors.ndim != 2 or vectors.shape[1] != EXPECTED_EMBEDDING_DIM:
            return f"unexpected vector shape {vectors.shape}"
        if vectors.shape[0] != int(marker.get("total_vectors", -1)):
            return "vector count differs from the marker"
        if not deep:
            return None
        if sha256_file(vector_path) != marker.get("vectors_sha256"):
            return "vectors file SHA-256 mismatch"
        if sha256_file(docs_path) != marker.get("docs_sha256"):
            return "documents file SHA-256 mismatch"
        texts, metadata_rows = read_checkpoint_documents(docs_path)
        if len(texts) != vectors.shape[0]:
            return "document count differs from vector count"
        if not np.isfinite(vectors).all():
            return "non-finite values in vectors"
        norms = np.linalg.norm(vectors.astype(np.float32), axis=1)
        if (np.abs(norms - 1.0) > 1e-3).any():
            return "vectors are not unit length"
        return metadata_problem(
            metadata_rows, int(marker["first_case_id"]), int(marker["last_case_id_exclusive"])
        )
    except Exception as exc:  # unreadable/corrupt file of any kind
        return f"unreadable ({type(exc).__name__}: {exc})"


def save_checkpoint(
    checkpoint_dir: Path,
    checkpoint_number: int,
    vectors: np.ndarray,
    documents: Sequence[str],
    metadata_rows: Sequence[Dict[str, Any]],
    manifest_fingerprint: str,
    first_case_id: int,
    last_case_id_exclusive: int,
    oom_recoveries: int = 0,
) -> None:
    problem = metadata_problem(metadata_rows, first_case_id, last_case_id_exclusive)
    if problem:
        raise RuntimeError(f"Refusing to save checkpoint {checkpoint_number}: {problem}")
    if len(documents) != vectors.shape[0] or len(metadata_rows) != vectors.shape[0]:
        raise RuntimeError(f"Refusing to save checkpoint {checkpoint_number}: vector/document count mismatch.")

    vector_path, docs_path, done_path = checkpoint_paths(checkpoint_dir, checkpoint_number)
    temp_vector_path = vector_path.with_name(vector_path.stem + ".tmp.npy")
    temp_docs_path = docs_path.with_name(docs_path.stem + ".tmp.jsonl")

    # The marker is written last, and removed first: a checkpoint exists only if its marker does.
    if done_path.exists():
        done_path.unlink()

    with temp_vector_path.open("wb") as handle:
        np.save(handle, np.asarray(vectors, dtype=np.float32))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_vector_path, vector_path)

    with temp_docs_path.open("w", encoding="utf-8") as handle:
        for text, metadata in zip(documents, metadata_rows):
            handle.write(json.dumps({"text": text, "metadata": metadata}, ensure_ascii=False))
            handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_docs_path, docs_path)

    atomic_write_json(
        done_path,
        {
            "checkpoint_number": checkpoint_number,
            "first_case_id": first_case_id,
            "last_case_id_exclusive": last_case_id_exclusive,
            "total_cases": last_case_id_exclusive - first_case_id,
            "total_vectors": int(vectors.shape[0]),
            "embedding_dimension": int(vectors.shape[1]),
            "manifest_fingerprint": manifest_fingerprint,
            "vectors_file_bytes": vector_path.stat().st_size,   # [v2.1 FIX 6]
            "docs_file_bytes": docs_path.stat().st_size,        # [v2.1 FIX 6]
            "vectors_sha256": sha256_file(vector_path),         # [v2.1 FIX 6]
            "docs_sha256": sha256_file(docs_path),              # [v2.1 FIX 6]
            "oom_recoveries": int(oom_recoveries),
            "completed_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def clean_stale_temp_files(checkpoint_dir: Path) -> None:
    """[v2.1 FIX 9] Remove half-written *.tmp* files left by a hard kill (they are never read, just clutter)."""
    for stale in checkpoint_dir.glob("*.tmp*"):
        try:
            stale.unlink()
        except OSError:
            pass


def prepare_manifest(
    checkpoint_dir: Path,
    source_path: Path,
    source_hash: str,
    selected_cases: int,
    batch_size: int,
    device: str,
    dtype_name: str,
    model_revision: Optional[str],
) -> str:
    """Create/validate manifest.json and return the configuration fingerprint.

    [v2.1 FIX 7] The fingerprint now covers only fields that change the stored vectors/text
    (model revision and dtype added; query prompt removed because it never affects documents).
    Library versions are recorded as informational data and produce a warning, not a refusal.
    """
    fields = {
        "manifest_version": MANIFEST_VERSION,
        "source_file": source_path.name,
        "source_sha256": source_hash,
        "selected_cases": int(selected_cases),
        "model_name": MODEL_NAME,
        "model_revision": model_revision,
        "device": device,
        "inference_dtype": dtype_name,
        "batch_size": int(batch_size),
        "max_seq_length": MAX_SEQ_LENGTH,
        "chunk_tokens": CHUNK_TOKENS,
        "chunk_overlap": CHUNK_OVERLAP,
        "checkpoint_cases": CHECKPOINT_CASES,
        "header_citation_tokens": HEADER_CITATION_TOKENS,
        "header_name_tokens": HEADER_NAME_TOKENS,
        "normalize_embeddings": True,
        "renormalized_in_float32": True,
        "document_format_version": DOCUMENT_FORMAT_VERSION,
        "expected_embedding_dimension": EXPECTED_EMBEDDING_DIM,
    }

    def fingerprint_of(payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    fingerprint = fingerprint_of(fields)
    informational = {
        "library_versions": library_versions(),
        "python": sys.version.split()[0],
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = checkpoint_dir / "manifest.json"
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)
        if "fields" not in existing:
            raise RuntimeError(
                f"Checkpoint folder '{checkpoint_dir}' was created by an older builder version (v2). "
                "Its text format differs; use a new --checkpoint-folder."
            )
        if fingerprint_of(existing["fields"]) != existing.get("fingerprint") or existing["fingerprint"] != fingerprint:
            changed = sorted(
                key for key in set(fields) | set(existing["fields"]) if fields.get(key) != existing["fields"].get(key)
            )
            raise RuntimeError(
                f"Checkpoint folder '{checkpoint_dir}' belongs to a different dataset or configuration "
                f"(differing settings: {', '.join(changed) or 'manifest was edited'}).\n"
                "Do not mix checkpoints. Restore the exact original settings to resume, "
                "or use a new --checkpoint-folder (which recomputes everything)."
            )
        old_versions = existing.get("informational", {}).get("library_versions", {})
        for name in ("transformers", "tokenizers", "sentence-transformers", "torch"):
            if old_versions.get(name) and old_versions.get(name) != informational["library_versions"].get(name):
                print(
                    f"WARNING: {name} was {old_versions[name]} when these checkpoints were created and is "
                    f"{informational['library_versions'].get(name)} now. Tokenization/numerics may differ slightly."
                )
        clean_stale_temp_files(checkpoint_dir)
    else:
        existing_files = [p.name for p in checkpoint_dir.iterdir() if p.name != "manifest.json"]
        if existing_files:
            raise RuntimeError(
                f"Checkpoint folder '{checkpoint_dir}' already contains files but has no manifest.\n"
                "To avoid reusing unknown/stale embeddings, choose a new --checkpoint-folder."
            )
        atomic_write_json(
            manifest_path, {"fingerprint": fingerprint, "fields": fields, "informational": informational}
        )
    return fingerprint


# ---------------------------- EMBEDDING ----------------------------
def is_oom(exc: BaseException) -> bool:
    return type(exc).__name__ == "OutOfMemoryError" or "out of memory" in str(exc).lower()


def encode_texts(
    model: Any,
    texts: Sequence[str],
    device: str,
    oom_retries: int,
    on_progress=None,
) -> Tuple[np.ndarray, int]:
    """Embed `texts`. Returns (vectors, number_of_oom_recoveries).

    [v2.1 FIX 3] v2 aborted the whole run on the first CUDA OOM and told you to switch to a NEW
    checkpoint folder -- which, because chunk settings are part of the fingerprint, throws away
    every completed checkpoint. Here an OOM only triggers: empty the CUDA cache, retry that
    one text with exponential back-off, and abort (with accurate instructions) only if it keeps failing.
    """
    rows: List[np.ndarray] = []
    recoveries = 0
    for slice_start in range(0, len(texts), ENCODE_SLICE):
        piece = list(texts[slice_start : slice_start + ENCODE_SLICE])
        try:
            vectors = model.encode(
                piece, batch_size=BATCH_SIZE, normalize_embeddings=True,
                show_progress_bar=False, convert_to_numpy=True,
            )
            rows.extend(np.asarray(vectors, dtype=np.float32))
        except Exception as exc:
            if not is_oom(exc):
                raise
            recoveries += 1
            for offset, text in enumerate(piece):
                for attempt in range(oom_retries + 1):
                    try:
                        _release_gpu_memory(device)
                        vector = model.encode(
                            [text], batch_size=1, normalize_embeddings=True,
                            show_progress_bar=False, convert_to_numpy=True,
                        )
                        rows.append(np.asarray(vector, dtype=np.float32)[0])
                        break
                    except Exception as inner:
                        if not is_oom(inner):
                            raise
                        if attempt == oom_retries:
                            raise EmbeddingOOMError(
                                f"CUDA ran out of memory on chunk {slice_start + offset} of this checkpoint group "
                                f"(~{len(text):,} characters) even after {oom_retries} retries.\n"
                                "All completed checkpoints are SAFE and will be reused.\n"
                                "Close other programs that use the GPU (browsers with hardware acceleration, "
                                "games, other Python sessions), check `nvidia-smi`, then re-run the SAME command.\n"
                                "Do NOT change CHUNK_TOKENS or the checkpoint folder unless you accept "
                                "recomputing everything: both are part of the checkpoint fingerprint."
                            ) from inner
                        time.sleep(min(2 ** attempt, 30))
        if on_progress:
            on_progress(min(slice_start + ENCODE_SLICE, len(texts)), len(texts))
    return np.vstack(rows) if rows else np.zeros((0, EXPECTED_EMBEDDING_DIM), dtype=np.float32), recoveries


def _release_gpu_memory(device: str) -> None:
    gc.collect()
    if device == "cuda":
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass


def finalize_vectors(vectors: np.ndarray, expected_rows: int, label: str) -> np.ndarray:
    """Shape/finite/norm checks, then exact float32 unit-normalisation. [v2.1 FIX 4]"""
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != expected_rows:
        raise RuntimeError(f"{label}: model returned shape {vectors.shape}; expected {expected_rows} rows.")
    if vectors.shape[1] != EXPECTED_EMBEDDING_DIM:
        raise RuntimeError(f"{label}: model returned {vectors.shape[1]} dimensions; expected {EXPECTED_EMBEDDING_DIM}.")
    if not np.isfinite(vectors).all():
        raise RuntimeError(
            f"{label}: non-finite embedding values (NaN/inf). With --dtype float16 this can be a numeric overflow; "
            "try --dtype bfloat16 with a NEW checkpoint folder (dtype is part of the fingerprint)."
        )
    norms = np.linalg.norm(vectors, axis=1)
    if (norms < 0.95).any() or (norms > 1.05).any():
        raise RuntimeError(f"{label}: embeddings are not approximately unit length (norm range {norms.min():.3f}-{norms.max():.3f}).")
    return unit_normalize(vectors)


# ---------------------------- INDEX ASSEMBLY ----------------------------
def assemble_faiss_index(
    checkpoint_dir: Path,
    selected_cases: int,
    checkpoint_count: int,
    manifest_fingerprint: str,
    index_folder: Path,
    source_path: Path,
    source_hash: str,
    source_total_records: int,
    device: str,
    dtype_name: str,
    model_revision: Optional[str],
) -> Tuple[int, int]:
    """Assemble vectors into native FAISS and keep text/metadata in SQLite."""
    import faiss

    print("\nAll embedding checkpoints are complete. Building the final FAISS index...")
    building_folder = index_folder.with_name(index_folder.name + "_building")
    if building_folder.exists():
        remove_tree(building_folder)
    building_folder.mkdir(parents=True, exist_ok=True)

    vector_index = faiss.IndexFlatL2(EXPECTED_EMBEDDING_DIM)
    database_path = building_folder / "metadata.sqlite3"
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(str(database_path))
        # Safe: this file lives in a disposable *_building folder that is deleted and rebuilt from the
        # checkpoints on any failure, so crash-consistency of the half-built database does not matter.
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            """
            CREATE TABLE chunks (
                vector_id INTEGER PRIMARY KEY,
                case_id INTEGER NOT NULL,
                citation TEXT,
                case_name TEXT,
                source_field TEXT,
                chunk_id INTEGER,
                chunk_count INTEGER,
                section_chunk_id INTEGER,
                section_chunk_count INTEGER,
                chunk_token_start INTEGER,
                chunk_token_end INTEGER,
                page_content TEXT NOT NULL,
                chunk_char_start INTEGER,
                chunk_char_end INTEGER,
                chunk_input_tokens INTEGER
            )
            """
        )
        connection.execute("CREATE INDEX idx_chunks_case_id ON chunks(case_id)")
        connection.execute(
            "CREATE TABLE cases (case_id INTEGER PRIMARY KEY, citation TEXT, citation_norm TEXT, "
            "case_name TEXT, chunk_count INTEGER NOT NULL)"
        )

        insert_sql = f"INSERT INTO chunks ({', '.join(CHUNK_COLUMNS)}) VALUES ({', '.join('?' * len(CHUNK_COLUMNS))})"
        total_document_rows = 0
        for checkpoint_number in tqdm(range(checkpoint_count), desc="Assembling FAISS index", unit="checkpoint"):
            problem = checkpoint_problem(checkpoint_dir, checkpoint_number, manifest_fingerprint, deep=True)
            if problem:
                # Mark incomplete so the next run recomputes exactly this group instead of looping on it.
                _, _, done_path = checkpoint_paths(checkpoint_dir, checkpoint_number)
                if done_path.exists():
                    done_path.unlink()
                raise RuntimeError(
                    f"Checkpoint {checkpoint_number} failed its integrity check ({problem}). "
                    "It has been marked incomplete; re-run the SAME command to recompute just that group."
                )

            vector_path, docs_path, _ = checkpoint_paths(checkpoint_dir, checkpoint_number)
            vectors = np.load(vector_path).astype(np.float32, copy=False)
            texts, metadata_rows = read_checkpoint_documents(docs_path)

            first_vector_id = int(vector_index.ntotal)
            rows: List[Tuple[Any, ...]] = []
            for offset, (text, metadata) in enumerate(zip(texts, metadata_rows)):
                rows.append(
                    (
                        first_vector_id + offset,
                        int(metadata["case_id"]),
                        metadata.get("citation", ""),
                        metadata.get("case_name", ""),
                        metadata.get("source_field", ""),
                        int(metadata.get("chunk_id", 0)),
                        int(metadata.get("chunk_count", 1)),
                        int(metadata.get("section_chunk_id", 0)),
                        int(metadata.get("section_chunk_count", 1)),
                        int(metadata.get("chunk_token_start", 0)),
                        int(metadata.get("chunk_token_end", 0)),
                        text,
                        int(metadata.get("chunk_char_start", 0)),
                        int(metadata.get("chunk_char_end", 0)),
                        int(metadata.get("chunk_input_tokens", 0)),
                    )
                )
                if len(rows) >= 1000:
                    connection.executemany(insert_sql, rows)
                    rows.clear()
            if rows:
                connection.executemany(insert_sql, rows)

            vector_index.add(np.ascontiguousarray(vectors))
            connection.commit()
            total_document_rows += len(texts)
            del vectors, rows, texts, metadata_rows

        if vector_index.ntotal != total_document_rows:
            raise RuntimeError(
                f"FAISS contains {vector_index.ntotal} vectors but SQLite contains {total_document_rows} rows."
            )

        # [v2.1 FIX 8] one row per case with a normalised citation key -> exact citation lookup.
        connection.create_function("normalize_citation", 1, normalize_citation)
        connection.execute(
            "INSERT INTO cases (case_id, citation, citation_norm, case_name, chunk_count) "
            "SELECT case_id, citation, normalize_citation(citation), case_name, chunk_count "
            "FROM chunks WHERE chunk_id = 0"
        )
        connection.execute("CREATE INDEX idx_cases_citation_norm ON cases(citation_norm)")
        connection.commit()

        case_rows, min_case, max_case = connection.execute(
            "SELECT COUNT(*), MIN(case_id), MAX(case_id) FROM cases"
        ).fetchone()
        if case_rows != selected_cases or min_case != 0 or max_case != selected_cases - 1:
            raise RuntimeError(
                f"Case table is inconsistent: {case_rows} rows, ids {min_case}..{max_case}, expected 0..{selected_cases - 1}."
            )
        connection.execute("PRAGMA optimize")
        connection.commit()
        connection.close()
        connection = None

        # [v2.1 FIX 9] Flush finished files to disk BEFORE the folder is renamed into place, so a power
        # cut right after "success" cannot leave a complete-looking folder with a truncated index.
        fsync_file(database_path)
        faiss_path = building_folder / "index.faiss"
        faiss.write_index(vector_index, str(faiss_path))
        fsync_file(faiss_path)

        run_info = {
            "index_format_version": INDEX_FORMAT_VERSION,
            "builder_version": "2.1",
            "source_file": source_path.name,
            "source_sha256": source_hash,
            "total_cases": int(selected_cases),
            "source_total_records": int(source_total_records),  # == total_cases for a complete build
            "total_vectors": int(vector_index.ntotal),
            "embedding_dimension": int(vector_index.d),
            "model_name": MODEL_NAME,
            "model_revision": model_revision,
            "device": device,
            "inference_dtype": dtype_name,
            "batch_size": BATCH_SIZE,
            "max_seq_length": MAX_SEQ_LENGTH,
            "chunk_tokens": CHUNK_TOKENS,
            "chunk_overlap": CHUNK_OVERLAP,
            "header_citation_tokens": HEADER_CITATION_TOKENS,
            "header_name_tokens": HEADER_NAME_TOKENS,
            "index_type": "FAISS IndexFlatL2",
            "metric": "L2 on unit-length vectors (squared L2; cosine = 1 - d/2)",
            "metadata_store": "SQLite metadata.sqlite3 (tables: chunks, cases)",
            "estimated_raw_vector_index_gib": round((vector_index.ntotal * EXPECTED_EMBEDDING_DIM * 4) / (1024 ** 3), 3),
            "embeddings_normalized": True,
            "query_prompt": QUERY_PROMPT,
            "checkpoint_cases": CHECKPOINT_CASES,
            "library_versions": library_versions(),
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "manifest_fingerprint": manifest_fingerprint,
        }
        # run_info.json is written LAST: its presence is the "this folder is complete" marker.
        atomic_write_json(building_folder / "run_info.json", run_info)

        if index_folder.exists():
            raise FileExistsError(
                f"Output folder '{index_folder}' already exists. Nothing was overwritten. "
                "Rename or move it, or choose a different --index-folder."
            )
        os.replace(building_folder, index_folder)
        return int(selected_cases), int(vector_index.ntotal)
    except BaseException:
        # Includes Ctrl+C: never leave a half-built folder behind. Checkpoints are untouched.
        if connection is not None:
            connection.close()
        try:
            remove_tree(building_folder)
        except OSError:
            pass
        raise


# ---------------------------- DRY RUN (CPU ONLY) ----------------------------
def percentile(values: Sequence[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if len(values) else 0.0


def run_dry_run(args: argparse.Namespace) -> int:
    """[v2.1 FIX 1] Tokenize-only pass. No GPU, no model weights, writes NOTHING (unless --dry-run-report)."""
    source_path = Path(args.json).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Input JSON file not found: {source_path}")
    tokenizer = load_tokenizer(args.model_revision)
    limit = args.max_cases

    chunks_per_case: List[int] = []
    chunk_tokens: List[int] = []
    text_bytes = 0
    empty_records = no_summary = no_description = header_clipped = cases_with_uncovered = 0
    uncovered_total = source_fffd = chunk_fffd = 0
    citation_counts: Dict[str, int] = {}
    chunkiest: List[Tuple[int, int, str]] = []

    iterator = iter_json_array(source_path)
    total = 0
    for case_id, case in enumerate(tqdm(islice(iterator, limit) if limit else iterator, desc="Tokenizing", unit="case")):
        if not isinstance(case, dict):
            raise ValueError(f"Record {case_id + 1} is not a JSON object.")
        total += 1
        texts, rows, info = make_case_chunks(case, case_id, tokenizer, strict=False)
        chunks_per_case.append(len(texts))
        chunk_tokens.extend(int(r["chunk_input_tokens"]) for r in rows)
        text_bytes += sum(len(t.encode("utf-8")) for t in texts)
        empty_records += rows[0]["source_field"] == "empty_record"
        no_summary += not json_value_to_text(case.get("summary"))
        no_description += not json_value_to_text(case.get("case_description"))
        header_clipped += bool(info["header_clipped"])
        if info["uncovered_chars"]:
            cases_with_uncovered += 1
            uncovered_total += info["uncovered_chars"]
        for field in ("summary", "case_description", "case_name", "citation"):
            source_fffd += json_value_to_text(case.get(field)).count("\ufffd")
        chunk_fffd += sum(t.count("\ufffd") for t in texts)
        key = normalize_citation(json_value_to_text(case.get("citation")))
        if key:
            citation_counts[key] = citation_counts.get(key, 0) + 1
        chunkiest.append((len(texts), case_id, json_value_to_text(case.get("citation"))))
        chunkiest = sorted(chunkiest, reverse=True)[:5]

    if args.expect_cases is not None and not limit and total != args.expect_cases:
        raise ValueError(f"--expect-cases {args.expect_cases:,} but the file contains {total:,} records.")

    total_chunks = len(chunk_tokens)
    duplicates = {k: v for k, v in citation_counts.items() if v > 1}
    vector_gib = total_chunks * EXPECTED_EMBEDDING_DIM * 4 / 1024 ** 3
    text_gib = text_bytes / 1024 ** 3
    buckets = [("1", 1, 1), ("2", 2, 2), ("3-5", 3, 5), ("6-10", 6, 10), ("11-20", 11, 20), (">20", 21, 10 ** 9)]

    print("\n================ DRY-RUN REPORT (tokenizer only; nothing was embedded or written) ================")
    print(f"Cases tokenized:             {total:,}")
    print(f"Total chunks (= FAISS vectors): {total_chunks:,}")
    print(f"Chunks per case:             mean {total_chunks / max(total, 1):.2f}  median {percentile(chunks_per_case, 50):.0f}  "
          f"p90 {percentile(chunks_per_case, 90):.0f}  p99 {percentile(chunks_per_case, 99):.0f}  max {max(chunks_per_case, default=0)}")
    for label, low, high in buckets:
        count = sum(low <= c <= high for c in chunks_per_case)
        print(f"   cases with {label:>5} chunks:   {count:,} ({100 * count / max(total, 1):.1f}%)")
    print(f"Input tokens per chunk:      mean {np.mean(chunk_tokens) if chunk_tokens else 0:.0f}  p50 {percentile(chunk_tokens, 50):.0f}  "
          f"p90 {percentile(chunk_tokens, 90):.0f}  max {max(chunk_tokens, default=0)}   (limit {MAX_SEQ_LENGTH})")
    total_tokens = int(sum(chunk_tokens))
    print(f"Total tokens to embed:       {total_tokens:,}")
    print(f"Empty records (fallback chunk): {empty_records:,}   without summary: {no_summary:,}   without description: {no_description:,}")
    print(f"Header text clipped (very long case name/citation): {header_clipped:,} cases (full values stay in SQLite)")
    print(f"Cases with source characters NOT covered by any token offset: {cases_with_uncovered:,} ({uncovered_total:,} chars)"
          "   <-- must be 0 for a lossless build")
    print(f"U+FFFD characters:           source {source_fffd:,}   in chunk text {chunk_fffd:,}   <-- if the source count is 0 this MUST be 0 (overlap can repeat a source U+FFFD, so it may exceed it otherwise)")
    print(f"Duplicate non-empty citations: {len(duplicates):,} citation keys shared by multiple cases"
          + (f"  e.g. {list(duplicates.items())[:3]}" if duplicates else ""))
    print("Chunkiest cases (chunks, case_id, citation):", chunkiest)
    print(f"Estimated sizes:             FAISS vectors {vector_gib:.2f} GiB (also the RAM needed to hold the index)")
    print(f"                             chunk text ~{text_gib:.2f} GiB in SQLite + ~{text_gib:.2f} GiB again in the checkpoint .jsonl files")
    print(f"                             checkpoint vectors ~{vector_gib:.2f} GiB  ->  plan for roughly {2 * vector_gib + 2 * text_gib:.1f} GiB "
          "of disk, plus ~10% slack, while checkpoints and the final index coexist")
    if args.assumed_chunks_per_sec or args.assumed_tokens_per_sec:
        print("Time projection (ONLY as good as the rate you supplied; measure it with the 100-case run):")
        if args.assumed_chunks_per_sec:
            print(f"   at {args.assumed_chunks_per_sec} chunks/s: {total_chunks / args.assumed_chunks_per_sec / 3600:.1f} h")
        if args.assumed_tokens_per_sec:
            print(f"   at {args.assumed_tokens_per_sec} tokens/s: {total_tokens / args.assumed_tokens_per_sec / 3600:.1f} h")
    else:
        print("Time projection: not shown. Run the 100-case build, read the 'tokens/s' it prints, then re-run with "
              "--assumed-tokens-per-sec <that number> (and no --max-cases) for a projection grounded in your own measurement.")
    print("=" * 96)

    if args.dry_run_report:
        report = {
            "cases": total, "total_chunks": total_chunks, "total_tokens": total_tokens,
            "chunks_per_case": {"mean": total_chunks / max(total, 1), "p50": percentile(chunks_per_case, 50),
                                "p90": percentile(chunks_per_case, 90), "p99": percentile(chunks_per_case, 99),
                                "max": max(chunks_per_case, default=0)},
            "cases_with_uncovered_chars": cases_with_uncovered, "source_fffd": source_fffd, "chunk_fffd": chunk_fffd,
            "header_clipped_cases": header_clipped, "empty_records": empty_records,
            "duplicate_citation_keys": len(duplicates),
            "estimated_vector_gib": vector_gib, "estimated_text_gib": text_gib,
        }
        Path(args.dry_run_report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Report written to", args.dry_run_report)
    return 0 if cases_with_uncovered == 0 else 1


# ---------------------------- MAIN ----------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a chunked, resumable FAISS index for Pakistani court cases (v2.1).")
    parser.add_argument("--json", default="cases_cleaned.json", help="Input JSON array file.")
    parser.add_argument("--index-folder", default="faiss_index_cases_cleaned",
                        help="Final FAISS output folder (must not already exist).")
    parser.add_argument("--checkpoint-folder", default="embedding_checkpoints_cases_cleaned",
                        help="Folder for resumable vector/document checkpoint files.")
    parser.add_argument("--max-cases", type=int, default=None, help="Optional small-run limit for testing.")
    parser.add_argument("--device", choices=["cuda", "cpu"], default=DEVICE)
    parser.add_argument("--dtype", choices=["float16", "bfloat16", "float32"], default=None,
                        help=f"[v2.1] CUDA weight dtype (default {DEFAULT_CUDA_DTYPE}); CPU always uses float32.")
    parser.add_argument("--model-revision", default=None,
                        help="[v2.1] Optional Hugging Face commit hash to pin the model/tokenizer version.")
    parser.add_argument("--expect-cases", type=int, default=None,
                        help="[v2.1] Abort if the file does not contain exactly this many records (e.g. 70090).")
    parser.add_argument("--oom-retries", type=int, default=4, help="[v2.1] Retries per chunk after a CUDA OOM.")
    parser.add_argument("--dry-run", action="store_true",
                        help="[v2.1] Tokenizer-only survey: exact chunk counts and sizes. No GPU, writes nothing.")
    parser.add_argument("--dry-run-report", default=None, help="[v2.1] Optional JSON file for the dry-run numbers.")
    parser.add_argument("--assumed-chunks-per-sec", type=float, default=None, help="[v2.1] Dry-run time projection input.")
    parser.add_argument("--assumed-tokens-per-sec", type=float, default=None, help="[v2.1] Dry-run time projection input.")
    return parser.parse_args(argv)


def run_build(args: argparse.Namespace) -> int:
    source_path = Path(args.json).resolve()
    index_folder = Path(args.index_folder).resolve()
    checkpoint_dir = Path(args.checkpoint_folder).resolve()

    if not source_path.is_file():
        raise FileNotFoundError(f"Input JSON file not found: {source_path}")
    if args.max_cases is not None and args.max_cases < 1:
        raise ValueError("--max-cases must be a positive integer.")
    if index_folder.exists():
        raise FileExistsError(
            f"Output folder '{index_folder}' already exists. Rename/remove it or choose another --index-folder "
            "(nothing was overwritten)."
        )

    dtype_name = resolve_dtype_name(args.device, args.dtype)

    print(f"Input file: {source_path}")
    print("Calculating dataset SHA-256 (used to protect checkpoint/resume correctness)...")
    source_hash = sha256_file(source_path)
    print(f"SHA-256: {source_hash}")

    print("Counting and validating JSON records...")
    total_in_file = count_cases(source_path)
    if args.expect_cases is not None and total_in_file != args.expect_cases:
        raise ValueError(f"--expect-cases {args.expect_cases:,} but the file contains {total_in_file:,} records.")
    selected_cases = min(args.max_cases, total_in_file) if args.max_cases else total_in_file
    if selected_cases == 0:
        raise ValueError("The JSON dataset contains no cases.")
    print(f"Cases in file: {total_in_file:,}")
    print(f"Cases selected for this run: {selected_cases:,}")
    print(f"Embedding model: {MODEL_NAME}  dtype: {dtype_name}  device: {args.device}  batch size: {BATCH_SIZE}")
    print(f"Chunking: up to {CHUNK_TOKENS:,} content tokens, {CHUNK_OVERLAP:,}-token overlap, max input {MAX_SEQ_LENGTH:,} tokens")

    manifest_fingerprint = prepare_manifest(
        checkpoint_dir, source_path, source_hash, selected_cases, BATCH_SIZE, args.device, dtype_name, args.model_revision,
    )

    checkpoint_count = math.ceil(selected_cases / CHECKPOINT_CASES)
    model = load_model(args.device, dtype_name, args.model_revision)
    tokenizer = model.tokenizer

    completed_cases = 0
    completed_checkpoints = 0
    session_chunks = session_tokens = session_oom = 0
    session_encode_seconds = 0.0

    with tqdm(total=selected_cases, desc="Embedding source cases", unit="case") as progress:
        for checkpoint_number, (first_case_id, case_group) in enumerate(
            grouped_cases(source_path, CHECKPOINT_CASES, selected_cases)
        ):
            last_case_id_exclusive = first_case_id + len(case_group)

            # Deep check on resume: a same-size bit-flipped checkpoint is caught here, not at assembly.
            problem = checkpoint_problem(checkpoint_dir, checkpoint_number, manifest_fingerprint, deep=True)
            if problem is None:
                _, _, done_path = checkpoint_paths(checkpoint_dir, checkpoint_number)
                marker = json.loads(done_path.read_text(encoding="utf-8"))
                completed_cases += len(case_group)
                completed_checkpoints += 1
                progress.update(len(case_group))
                progress.set_postfix(chunks=marker["total_vectors"], status="resumed")
                continue
            if problem != "no completion marker":
                tqdm.write(f"Checkpoint {checkpoint_number} is not reusable ({problem}); recomputing it.")

            texts: List[str] = []
            metadata_rows: List[Dict[str, Any]] = []
            for offset, case in enumerate(case_group):
                case_texts, case_metadata, _ = make_case_chunks(case, first_case_id + offset, tokenizer, strict=True)
                texts.extend(case_texts)
                metadata_rows.extend(case_metadata)
            if not texts:
                raise RuntimeError(f"Checkpoint {checkpoint_number} produced no text chunks; refusing to skip cases.")

            started = time.time()
            raw_vectors, recoveries = encode_texts(
                model, texts, args.device, args.oom_retries,
                on_progress=lambda done, total, n=checkpoint_number: progress.set_postfix(group=n, chunk=f"{done}/{total}"),
            )
            session_encode_seconds += time.time() - started
            vectors = finalize_vectors(raw_vectors, len(texts), f"checkpoint {checkpoint_number}")

            save_checkpoint(
                checkpoint_dir, checkpoint_number, vectors, texts, metadata_rows,
                manifest_fingerprint, first_case_id, last_case_id_exclusive, oom_recoveries=recoveries,
            )

            session_chunks += len(texts)
            session_tokens += sum(int(r["chunk_input_tokens"]) for r in metadata_rows)
            session_oom += recoveries
            completed_cases += len(case_group)
            completed_checkpoints += 1
            progress.update(len(case_group))
            progress.set_postfix(chunks=int(vectors.shape[0]), status="saved")

            del vectors, raw_vectors, texts, metadata_rows, case_group
            _release_gpu_memory(args.device)

    if completed_cases != selected_cases:
        raise RuntimeError(f"Processed {completed_cases} cases but expected {selected_cases}. Check the JSON input.")

    if session_encode_seconds > 0:
        print(
            f"\nThis session embedded {session_chunks:,} chunks / {session_tokens:,} tokens in "
            f"{session_encode_seconds / 60:.1f} min of encode time: "
            f"{session_chunks / session_encode_seconds:.2f} chunks/s, {session_tokens / session_encode_seconds:,.0f} tokens/s"
            f" (OOM recoveries: {session_oom})."
        )
        print("Use the tokens/s figure with  --dry-run --assumed-tokens-per-sec  to project the full run.")
    print(f"Embedding stage complete: {completed_cases:,} cases across {completed_checkpoints:,} checkpoints.")

    # [v2.1 FIX 9] The embedding model is no longer needed: release its VRAM/RAM before FAISS assembly.
    del model, tokenizer
    _release_gpu_memory(args.device)

    for checkpoint_number in range(checkpoint_count):
        problem = checkpoint_problem(checkpoint_dir, checkpoint_number, manifest_fingerprint, deep=False)
        if problem:
            raise RuntimeError(f"Checkpoint {checkpoint_number} failed final validation: {problem}")

    assembly_started = time.time()
    cases_done, vectors_done = assemble_faiss_index(
        checkpoint_dir=checkpoint_dir,
        selected_cases=selected_cases,
        checkpoint_count=checkpoint_count,
        manifest_fingerprint=manifest_fingerprint,
        index_folder=index_folder,
        source_path=source_path,
        source_hash=source_hash,
        source_total_records=total_in_file,
        device=args.device,
        dtype_name=dtype_name,
        model_revision=args.model_revision,
    )
    assembly_elapsed = time.time() - assembly_started

    print("\nSUCCESS: FAISS index created.")
    print(f"Source cases:       {cases_done:,}")
    print(f"FAISS vectors:      {vectors_done:,}")
    print(f"Embedding dimension: {EXPECTED_EMBEDDING_DIM}")
    print(f"Model:              {MODEL_NAME} ({dtype_name})")
    print(f"Index folder:       {index_folder}")
    print(f"Checkpoint folder:  {checkpoint_dir}   <-- KEEP until verify_index_cleaned.py passes")
    print(f"FAISS assembly:     {assembly_elapsed / 60:.1f} minutes")
    print("Next: python verify_index_cleaned.py --index-folder", index_folder.name, "--source-json", Path(args.json).name)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.dry_run:
            return run_dry_run(args)
        return run_build(args)
    except KeyboardInterrupt:
        # [v2.1 FIX 9] v2 only caught Ctrl+C inside the embedding loop; hashing/counting/assembly gave a raw traceback.
        print("\nInterrupted by user. Completed checkpoints are saved and valid.")
        print("Run the EXACT same command again to resume; completed checkpoints will be skipped.")
        return 130
    except EmbeddingOOMError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        raise
