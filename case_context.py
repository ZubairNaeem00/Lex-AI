"""Build compact case context from full case data.

Full extracted text, reports, and chat history stay in the session. The
functions here select facts, summaries, and short excerpts for a specific
question so prompts remain small and avoid repeating the whole case.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from context_budget import (
    CHARS_PER_TOKEN,
    compact_lines,
    count_tokens,
    truncate_chars,
    truncate_to_tokens,
)


CANONICAL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "applicants_full_name",
        "patterns": [
            r"\baccused\b.*\bname\b",
            r"\bname\b.*\baccused\b",
            r"^accused$",
            r"\bapplicant\b.*\bname\b",
            r"\bname\b.*\bapplicant\b",
            r"^applicant$",
            r"\bpetitioner\b.*\bname\b",
            r"\bname\b.*\bpetitioner\b",
            r"^petitioner$",
            r"^name$",
        ],
        "exclude": [
            r"father",
            r"mother",
            r"complainant",
            r"respondent",
            r"witness",
            r"victim",
            r"investigat",
            r"officer",
            r"court",
            r"police",
            r"company",
        ],
    },
    {
        "name": "applicant_fathers_name",
        "patterns": [
            r"father.*name",
            r"name.*father",
            r"\bs\s*/\s*o\b",
            r"\bd\s*/\s*o\b",
            r"\bson of\b",
            r"\bdaughter of\b",
        ],
        "exclude": [r"complainant", r"victim", r"witness", r"informant"],
    },
    {
        "name": "applicants_address",
        "patterns": [
            r"\baddress\b",
            r"\bresident\b",
            r"\bresidence\b",
            r"\bresiding\b",
            r"\bdwelling\b",
        ],
        "exclude": [
            r"law firm", r"advocate", r"counsel", r"company", r"employer", r"court",
            r"complainant", r"victim", r"witness", r"informant",
        ],
    },
    {
        "name": "applicants_cnic_no",
        "patterns": [
            r"\bcnic\b",
            r"\bnic\b",
            r"identity card",
            r"national identity",
            r"\b(accused|applicant|petitioner|person)\b.*\bid\b",
        ],
        "exclude": [r"complainant", r"victim", r"witness", r"informant"],
    },
    {
        "name": "police_station",
        "patterns": [r"police station", r"\bthana\b", r"\bps\b"],
        "exclude": [r"officer", r"investigat"],
    },
    {
        "name": "list_relevant_sections",
        "patterns": [
            r"\bsections?\b",
            r"\bppc\b",
            r"penal code",
            r"\bcrpc\b",
            r"charges?",
            r"statutes?",
            r"\bprovisions?\b",
        ],
        "exclude": [
            r"section of (the )?court",
            r"section officer",
            r"in\s*charge",
            r"description",
            r"narrative",
            r"contents?",
            r"facts",
            r"alleged",
            r"nature of",
            r"summary",
            r"details",
        ],
    },
    {
        "name": "police_station_investigation_officer",
        "patterns": [
            r"investigating officer",
            r"investigation officer",
            r"\bi\s*\.?\s*o\s*\.?\b",
            r"officer in charge",
        ],
        "exclude": [],
    },
    {
        "name": "fir_number",
        "patterns": [r"\bfir\b.*\b(no|number|registration)\b", r"\bfir\b\s*[:#]?\s*\d", r"^fir$"],
        "exclude": [r"date", r"year", r"contents", r"details?", r"copy"],
    },
    {
        "name": "court_name_location",
        "patterns": [r"\bcourt\b", r"forum", r"sessions judge", r"magistrate", r"tribunal"],
        "exclude": [r"court fees?", r"court clerk"],
    },
    {
        "name": "law_firm_address",
        "patterns": [r"law firm", r"advocate", r"counsel", r"attorney", r"legal representative"],
        "exclude": [],
    },
]

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "what", "which", "who",
    "whom", "whose", "does", "did", "has", "have", "had", "was", "were", "are",
    "is", "be", "been", "being", "about", "into", "under", "over", "after",
    "before", "please", "tell", "explain", "case", "legal", "law", "my", "our",
    "his", "her", "their", "its", "you", "your", "can", "could", "should",
    "would", "will", "shall", "may", "might", "must", "not", "but", "any",
    "all", "how", "why", "when", "where", "there", "here", "also", "then",
    "than", "such", "and/or", "according", "given", "provide", "help",
}

_NAME_WITH_RELATION = re.compile(
    r"^(?P<name>.+?)\s+(?:son|daughter|s\s*/\s*o|d\s*/\s*o)\s*(?:of)?\s+(?P<father>.+)$",
    re.IGNORECASE,
)

_ADDRESS_HINT = re.compile(
    r"\b(house|h\.?\s*no|r/o|street|st\.|road|colony|town|village|district|"
    r"tehsil|phase|block|flat|plot|sector|mohalla)\b",
    re.IGNORECASE,
)

_EDIT_PATH_RE = re.compile(
    r"^(?:"
    r"title|document_type|summary|"
    r"unclear_information\.\d+|"
    r"sections\.\d+\.(?:title|summary|bullets\.\d+|"
    r"fields\.\d+\.(?:label|value)|"
    r"table\.rows\.\d+\.\d+)"
    r")$"
)


def normalize_label(label: Any) -> str:
    text = str(label or "").lower()
    text = re.sub(r"[*_#`]+", " ", text)
    text = re.sub(r"[^a-z0-9/.\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_APPLICANT_CANONICALS = {
    "applicants_full_name",
    "applicant_fathers_name",
    "applicants_address",
    "applicants_cnic_no",
}

_OTHER_PARTY_SECTION = re.compile(
    r"complainant|informant|victim|witness|prosecut|police|court|officer|investigat",
    re.IGNORECASE,
)


def canonical_for_label(label: str, section_title: str = "") -> Optional[str]:
    normalized = normalize_label(label)
    if not normalized:
        return None
    other_party_section = bool(_OTHER_PARTY_SECTION.search(section_title or ""))
    for spec in CANONICAL_SPECS:
        if other_party_section and spec["name"] in _APPLICANT_CANONICALS:
            continue
        if any(re.search(pattern, normalized) for pattern in spec["exclude"]):
            continue
        if any(re.search(pattern, normalized) for pattern in spec["patterns"]):
            return spec["name"]
    return None


def collection_fields(report: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for section_index, section in enumerate(report.get("sections") or []):
        section_title = section.get("title") or "Details"
        for field_index, item in enumerate(section.get("fields") or []):
            label = item.get("label") or ""
            value = item.get("value") or ""
            if not str(label).strip() or not str(value).strip():
                continue
            yield {
                "section_index": section_index,
                "section_title": section_title,
                "field_index": field_index,
                "label": label,
                "value": str(value),
                "path": f"sections.{section_index}.fields.{field_index}.value",
            }


def corrected_paths(document: Any) -> set[str]:
    return {edit.get("path", "") for edit in (document.edits or [])}


def correction_triples(document: Any) -> List[Tuple[str, str, str]]:
    """Return (label, original value, corrected value) for user edits."""
    labels = {
        item["path"]: item["label"] for item in collection_fields(document.report)
    }
    corrections: List[Tuple[str, str, str]] = []
    for edit in document.edits or []:
        path = str(edit.get("path") or "")
        old_value = str(edit.get("old_value") or "").strip()
        new_value = str(edit.get("new_value") or "").strip()
        if not path or not old_value or not new_value or old_value == new_value:
            continue
        label = labels.get(path)
        if not label:
            if path == "title":
                label = "Document title"
            elif path == "summary":
                label = "Summary"
            else:
                label = path
        corrections.append((label, old_value, new_value))
    return corrections


def apply_text_corrections(text: str, document: Any) -> str:
    """Apply corrected fact values to model-bound text only.

    The stored extracted text and the original analysis remain untouched; this
    prevents a corrected name or number from being contradicted by an excerpt
    that still contains the original extraction.
    """
    if not text:
        return text
    for _, old_value, new_value in correction_triples(document):
        if len(old_value) < 6 or old_value.lower() in {"not stated", "unknown", "n/a"}:
            continue
        text = text.replace(old_value, new_value)
    return text


def document_canonical_facts(document: Any) -> Dict[str, str]:
    facts: Dict[str, str] = {}
    for item in collection_fields(document.report):
        canonical = canonical_for_label(item["label"], item["section_title"])
        if canonical and canonical not in facts:
            facts[canonical] = truncate_chars(item["value"], 500)

    full_name = facts.get("applicants_full_name", "")
    relation = _NAME_WITH_RELATION.match(full_name)
    address_tail = ""
    if relation:
        facts["applicants_full_name"] = truncate_chars(relation.group("name"), 200)
        father, _, address_tail = relation.group("father").partition(",")
        facts.setdefault("applicant_fathers_name", truncate_chars(father.strip(), 200))
        address_tail = address_tail.strip()
    else:
        name, _, address_tail = full_name.partition(",")
        if name.strip() and address_tail.strip():
            facts["applicants_full_name"] = truncate_chars(name.strip(), 200)
            address_tail = address_tail.strip()

    if (
        address_tail
        and not facts.get("applicants_address")
        and _ADDRESS_HINT.search(address_tail)
    ):
        facts["applicants_address"] = truncate_chars(address_tail, 500)

    if not facts.get("police_station_investigation_officer") and facts.get("police_station"):
        # The bail template explicitly allows the police station when the IO's
        # name is unavailable; this avoids asking the user for data the case
        # already contains.
        facts["police_station_investigation_officer"] = facts["police_station"]

    return facts


def case_facts_for_generation(
    session: Any,
    *,
    include_draft_answers: bool = True,
) -> Dict[str, str]:
    """Return compact known facts (canonical + useful labels + drafting answers).

    Set include_draft_answers=False when starting a new document so answers
    given for a previous person/document are not silently reused.
    """
    documents = sorted(
        list(session.documents.values()),
        key=lambda doc: getattr(doc, "updated_at", ""),
        reverse=True,
    )
    facts: Dict[str, str] = {}
    for document in documents:
        for key, value in document_canonical_facts(document).items():
            facts.setdefault(key, value)

    # Keep a small set of non-canonical report fields (e.g. complainant,
    # offence description) available to the extraction LLM.
    extra_pairs: List[Tuple[str, str]] = []
    seen_labels: set[str] = set()
    for document in documents:
        for item in collection_fields(document.report):
            label = str(item["label"]).strip()
            key = normalize_label(label)
            if not key or key in seen_labels:
                continue
            if canonical_for_label(label, item["section_title"]):
                continue
            seen_labels.add(key)
            extra_pairs.append((f"{item['section_title']}: {label}", item["value"]))
            if len(extra_pairs) >= 18:
                break
        if len(extra_pairs) >= 18:
            break

    for label, value in extra_pairs:
        facts[label] = truncate_chars(value, 220)

    if include_draft_answers:
        for key, value in (session.extra_case_details or {}).items():
            if value:
                facts[key] = truncate_chars(value, 400)

    return {
        key: value
        for key, value in facts.items()
        if value is not None and str(value).strip()
    }


def known_facts_text(facts: Dict[str, str], max_tokens: int) -> str:
    pairs = []
    for key, value in facts.items():
        label = key.replace("_", " ").title() if re.match(r"^[a-z0-9_]+$", key) else key
        pairs.append((label, value))
    return truncate_to_tokens(compact_lines(pairs), max_tokens)


def _query_terms(question: str) -> List[str]:
    terms = []
    for token in re.findall(r"[a-zA-Z0-9/]+", (question or "").lower()):
        if len(token) < 2 or token in _STOPWORDS:
            continue
        terms.append(token)
    return list(dict.fromkeys(terms))


def _text_blocks(text: str) -> List[str]:
    raw = re.sub(r"\r\n?", "\n", text or "")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", raw) if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in raw.split("\n") if line.strip()]
    cleaned = []
    for block in blocks:
        block = re.sub(r"^\s*[-*_]{3,}\s*$", "", block)
        block = re.sub(r"[ \t]+", " ", block).strip()
        if block:
            cleaned.append(block)
    return cleaned


def relevant_excerpts(text: str, question: str, max_chars: int = 1200) -> str:
    """Lexically select the most relevant paragraphs from a full document."""
    if not text or max_chars <= 0:
        return ""
    terms = _query_terms(question)
    blocks = _text_blocks(text)
    if not blocks:
        return ""

    scored: List[Tuple[float, int, str]] = []
    for index, block in enumerate(blocks):
        lower = block.lower()
        score = 0.0
        for term in terms:
            if term in lower:
                score += 2.0 + min(lower.count(term), 3) * 0.5
        if score > 0:
            score += max(0.0, 0.5 - index * 0.01)
        scored.append((score, index, block))

    selected: List[str] = []
    total = 0
    for score, index, block in sorted(scored, key=lambda item: item[0], reverse=True):
        if score <= 0 and selected:
            continue
        block = truncate_chars(block, 850)
        if total + len(block) > max_chars and selected:
            continue
        selected.append((index, block))
        total += len(block) + 2
        if len(selected) >= 6 or total >= max_chars * 0.92:
            break

    if not selected and blocks:
        selected = [(0, truncate_chars(blocks[0], min(700, max_chars)))]

    selected.sort(key=lambda item: item[0])
    excerpt = "\n---\n".join(block for _, block in selected)
    return truncate_chars(excerpt, max_chars)


_PARTY_SECTION = re.compile(
    r"complainant|informant|accused|offender|applicant|petitioner|respondent|victim|witness",
    re.IGNORECASE,
)


def _document_block(document: Any, index: int) -> Tuple[str, List[Tuple[str, str]]]:
    report = document.report or {}
    doc_type = str(report.get("document_type") or "").strip()
    if not doc_type or doc_type.lower() == "unknown":
        doc_type = "Document"
    title = str(report.get("title") or "").strip()
    header = f"[DOC-{index}] {document.filename} — {doc_type}"
    if title and normalize_label(title) != normalize_label(doc_type):
        header += f": {title}"

    summary = truncate_chars(report.get("summary") or "", 320)
    summary = apply_text_corrections(summary, document)
    edits = corrected_paths(document)
    all_fields = list(collection_fields(report))
    corrected_fields = [item for item in all_fields if item["path"] in edits]
    uncorrected = [item for item in all_fields if item["path"] not in edits]
    canonical_fields = [
        item
        for item in uncorrected
        if canonical_for_label(item["label"], item["section_title"])
    ]
    canonical_paths = {item["path"] for item in canonical_fields}
    other_fields = [item for item in uncorrected if item["path"] not in canonical_paths]
    # Corrections and canonical facts must never fall outside the compact window.
    selected_fields = (corrected_fields + canonical_fields + other_fields)[:12]
    selected_fields.sort(
        key=lambda item: (item["section_index"], item["field_index"])
    )
    field_lines: List[Tuple[str, str]] = []
    for item in selected_fields:
        label = str(item["label"]).strip()
        if _PARTY_SECTION.search(str(item["section_title"])):
            label = f"{item['section_title']}: {label}"
        value = str(item["value"]).strip()
        if edits and item["path"] in edits:
            value = f"{value} [user-corrected]"
        field_lines.append((label, value))

    parts = [header]
    if summary:
        parts.append(f"Summary: {summary}")
    if field_lines:
        parts.append("Key particulars:\n" + compact_lines(field_lines, 170))
    else:
        parts.append("No structured field values were extracted.")
    return "\n".join(parts), field_lines


def build_case_context(
    session: Any,
    question: str = "",
    *,
    max_tokens: int = 900,
    include_excerpts: bool = True,
) -> str:
    """Build the compact case-context block used in legal prompts."""
    documents = list(session.documents.values())
    details = {
        key: value for key, value in (session.extra_case_details or {}).items() if value
    }

    if not documents and not details:
        return ""

    fact_budget = max_tokens
    excerpt_budget = 0
    if include_excerpts and documents:
        fact_budget = max(220, int(max_tokens * 0.62))
        excerpt_budget = max(120, max_tokens - fact_budget)

    blocks: List[str] = []
    correction_lines: List[str] = []
    for index, document in enumerate(documents, start=1):
        block, _ = _document_block(document, index)
        blocks.append(block)
        for label, old_value, new_value in correction_triples(document):
            correction_lines.append(
                f"- DOC-{index} {label}: {old_value!r} -> {new_value!r}"
            )

    facts_text = "\n\n".join(blocks)
    if correction_lines:
        corrections_text = (
            "USER-CORRECTED VALUES (AUTHORITATIVE): These values replace the original\n"
            "extraction in every summary, field, and excerpt. Always use them and never\n"
            "revert to the original value, even if older text below shows it.\n"
            + "\n".join(
                truncate_chars(line, 260) for line in correction_lines[:20]
            )
        )
        facts_text = corrections_text + "\n\n" + facts_text
    if details:
        detail_pairs = [
            (key.replace("_", " ").title() if re.match(r"^[a-z0-9_]+$", key) else key, value)
            for key, value in details.items()
        ]
        facts_text += (
            "\n\nDETAILS SUPPLIED BY THE USER DURING DOCUMENT PREPARATION "
            "(user-provided, not source-verified):\n"
            + compact_lines(detail_pairs, 180)
        )

    facts_text = truncate_to_tokens(facts_text, fact_budget, suffix=" …[case facts trimmed]")

    if include_excerpts and excerpt_budget > 0 and documents:
        per_doc_chars = max(
            260,
            int((excerpt_budget * CHARS_PER_TOKEN) / max(1, len(documents))),
        )
        excerpt_blocks = []
        for index, document in enumerate(documents, start=1):
            excerpt = relevant_excerpts(document.extracted_text, question, max_chars=per_doc_chars)
            excerpt = apply_text_corrections(excerpt, document)
            if excerpt:
                excerpt_blocks.append(f"[DOC-{index} excerpt]\n{excerpt}")
        excerpts = "\n\n".join(excerpt_blocks)
        excerpts = truncate_to_tokens(
            excerpts, excerpt_budget, suffix=" …[excerpts trimmed]"
        )
        if excerpts:
            facts_text += (
                "\n\nMOST RELEVANT EXCERPTS (documents are stored in full; only "
                "these excerpts are sent):\n" + excerpts
            )

    return facts_text


def build_generation_context(session: Any, request: str, max_tokens: int = 500) -> str:
    """Compact case description for field extraction (facts are passed separately)."""
    documents = list(session.documents.values())
    if not documents:
        return "No uploaded documents. Use only the user's instruction and known facts."

    blocks = []
    remaining_chars = int(max_tokens * CHARS_PER_TOKEN)
    per_doc = max(160, remaining_chars // max(1, len(documents)))
    for index, document in enumerate(documents, start=1):
        report = document.report or {}
        doc_type = str(report.get("document_type") or "Document").strip()
        summary = truncate_chars(report.get("summary") or "", max(120, per_doc // 2))
        summary = apply_text_corrections(summary, document)
        excerpt = relevant_excerpts(
            document.extracted_text, request, max_chars=max(160, per_doc // 2)
        )
        excerpt = apply_text_corrections(excerpt, document)
        block = f"[DOC-{index}] {document.filename} — {doc_type}"
        if summary:
            block += f"\nSummary: {summary}"
        if excerpt:
            block += f"\nRelevant excerpt: {excerpt}"
        blocks.append(block)

    return truncate_to_tokens(
        "\n\n".join(blocks), max_tokens, suffix=" …[context trimmed]"
    )


def annotate_report(report: Dict[str, Any], edits: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy a report and mark fields corrected by the user."""
    annotated = copy.deepcopy(report)
    edit_map: Dict[str, Dict[str, Any]] = {}
    for edit in edits or []:
        path = edit.get("path")
        if path and path not in edit_map:
            # Keep the first edit per path so "original extraction" always points
            # at the source value, even after the same field is edited twice.
            edit_map[path] = edit
    annotated["has_corrections"] = bool(edits)
    for section_index, section in enumerate(annotated.get("sections") or []):
        for field_index, item in enumerate(section.get("fields") or []):
            path = f"sections.{section_index}.fields.{field_index}.value"
            if path in edit_map:
                item["corrected"] = True
                item["original_value"] = edit_map[path].get("old_value")
    return annotated


def _resolve_container(root: Any, parts: Sequence[str]) -> Tuple[Any, str]:
    current = root
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                raise ValueError(f"Unknown report path segment: {part}")
            current = current[part]
        elif isinstance(current, list):
            try:
                index = int(part)
            except (TypeError, ValueError):
                raise ValueError("List index expected in report path.") from None
            if index < 0 or index >= len(current):
                raise ValueError("Report path index is out of range.")
            current = current[index]
        else:
            raise ValueError("Report path cannot be resolved.")
    return current, parts[-1]


def read_edit_path(report: Dict[str, Any], path: str) -> Any:
    if not _EDIT_PATH_RE.match(path or ""):
        raise ValueError("This report field cannot be edited.")
    parts = path.split(".")
    container, leaf = _resolve_container(report, parts)
    if isinstance(container, list):
        try:
            return container[int(leaf)]
        except (TypeError, ValueError, IndexError):
            raise ValueError("Report path index is invalid.") from None
    if isinstance(container, dict):
        if leaf not in container:
            raise ValueError("Report path does not exist.")
        return container[leaf]
    raise ValueError("Report path cannot be resolved.")


def apply_edit_path(report: Dict[str, Any], path: str, value: Any) -> Tuple[str, str]:
    """Apply one edit to a report copy and return (old_value, new_value)."""
    if not _EDIT_PATH_RE.match(path or ""):
        raise ValueError("This report field cannot be edited.")
    old_value = read_edit_path(report, path)
    new_value = str(value if value is not None else "").replace("\r\n", "\n").strip()
    max_length = 200 if path in {"title", "document_type"} else 4000
    if len(new_value) > max_length:
        raise ValueError(f"Value is too long (maximum {max_length} characters).")

    parts = path.split(".")
    container, leaf = _resolve_container(report, parts)
    if isinstance(container, list):
        index = int(leaf)
        if index < 0 or index >= len(container):
            raise ValueError("Report path index is out of range.")
        container[index] = new_value
    elif isinstance(container, dict):
        if leaf not in container:
            raise ValueError("Report path does not exist.")
        container[leaf] = new_value
    else:
        raise ValueError("Report path cannot be resolved.")

    return str(old_value if old_value is not None else ""), new_value
