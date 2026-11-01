"""Dedicated multi-turn document-generation workflow.

The workflow is stored on the case session, so the next user message can be
routed to it instead of the legal RAG agent while it is waiting for a field.
It asks one missing field at a time, normalizes conversational replies into
clean values, and pauses at a review stage before rendering the document.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from context_budget import (
    GENERATION_CONTEXT_TOKEN_BUDGET,
    MAX_GENERATION_ANSWER_CHARS,
    truncate_chars,
)
from doc_generation import (
    TEMPLATE_FOLDER,
    _has_value,
    extract_fields_from_context,
    generate_document,
    get_supported_templates,
    get_template_catalog,
    get_template_fields,
    normalize_field_answer,
)
from session_manager import CaseSession, new_id, utcnow


ACTION_RE = re.compile(
    r"\b(draft|drafting|generate|prepare|create|write|compose|make|fill|"
    r"need|want|require)\b",
    re.IGNORECASE,
)
DOCUMENT_NOUN_RE = re.compile(
    r"\b(application|petition|affidavit|notice|contract|agreement|document|"
    r"bail papers|legal draft)\b",
    re.IGNORECASE,
)
QUESTION_PREFIX_RE = re.compile(
    r"^\s*(how (do|can|should) (i|we)|how to|what is|what are|explain|"
    r"tell me about|why)\b",
    re.IGNORECASE,
)
NEW_DRAFT_RE = re.compile(
    r"\b(?:new|another|different|separate|fresh|second)\b[\s\S]{0,80}"
    r"\b(?:application|petition|affidavit|document|draft)\b"
    r"|\b(?:application|petition|affidavit|document|draft)\b[\s\S]{0,60}"
    r"\b(?:for (?:someone|somebody|another person|a different person)|new)\b",
    re.IGNORECASE,
)
CANCEL_WORDS = {"cancel", "stop", "abort", "quit", "cancel that"}
RETRY_WORDS = {"retry", "try again", "regenerate", "try once more"}

TEMPLATE_HINTS = [
    ("Bail Application.docx", re.compile(r"\b(bail|497|498|zamanat|release from jail|custody)\b", re.I)),
    (
        "Dissolution Of Marriage Application.docx",
        re.compile(r"\b(divorce|dissolution|khula|talaq|marriage)\b", re.I),
    ),
    ("Employment Contract.docx", re.compile(r"\b(employment|job|contract of employment|appointment)\b", re.I)),
    ("Legal Notice.docx", re.compile(r"\b(legal notice|notice)\b", re.I)),
]

FIELD_QUESTIONS = {
    "applicants_full_name": "What is the applicant's full legal name?",
    "applicant_fathers_name": "What is the applicant's father's full name?",
    "applicants_address": "What is the applicant's full residential address?",
    "applicants_cnic_no": "What is the applicant's CNIC number?",
    "police_station": "Which police station registered the FIR?",
    "list_relevant_sections": "Which PPC/CrPC sections are stated in the FIR?",
    "police_station_investigation_officer": "Who is the investigating officer (or which police station is handling the case)?",
    "fir_number": "What is the FIR number and year?",
    "court_name_location": "Which court should the application be filed in?",
    "law_firm_address": "What advocate or law-firm name and address should appear at the end?",
}


class GenerationConflict(RuntimeError):
    """Raised when a generation cannot be edited in its current state."""


def _template_file_exists(name: str) -> bool:
    return (TEMPLATE_FOLDER / name).exists()


def choose_template(message: str) -> Optional[str]:
    text = message or ""
    for template, pattern in TEMPLATE_HINTS:
        if pattern.search(text):
            return template
    if re.search(r"\b(application|petition|affidavit)\b", text, re.I):
        return "Bail Application.docx"
    return None


def detect_generation_request(message: str) -> Optional[str]:
    """Return the template path if the message requests document drafting.

    Ordinary explanatory questions ("how do I draft...") are not treated as
    generation requests unless the user asks for their own case.
    """
    text = (message or "").strip()
    if not text:
        return None
    if QUESTION_PREFIX_RE.search(text) and not re.search(
        r"\b(for my|for me|my case|our case|my client|our client)\b", text, re.I
    ):
        return None

    has_action = bool(ACTION_RE.search(text))
    has_noun = bool(DOCUMENT_NOUN_RE.search(text))
    explicit = bool(
        re.search(
            r"\b(draft|generate|prepare|create|write|make)\b.*\b(application|petition|affidavit)\b",
            text,
            re.I,
        )
    )
    if not (explicit or (has_action and has_noun)):
        return None

    template = choose_template(text)
    if not template:
        return None
    if not _template_file_exists(template):
        return template
    return template


def _is_new_draft_request(message: str) -> bool:
    text = (message or "").strip()
    return bool(text and NEW_DRAFT_RE.search(text) and detect_generation_request(text))


def _template_label(template_name: str) -> str:
    return Path(template_name).stem


def _field_label(name: str) -> str:
    return str(name or "").replace("_", " ").title()


def _field_progress(template_name: str, values: Dict[str, str]) -> Dict[str, Any]:
    fields = get_template_fields(template_name)
    required = [field for field in fields if field.get("required")]
    completed = [field for field in required if _has_value(values.get(field["name"]))]
    return {
        "completed": len(completed),
        "total": len(required),
    }


def _missing_fields(template_name: str, values: Dict[str, str]) -> List[Dict[str, Any]]:
    return [
        field
        for field in get_template_fields(template_name)
        if field.get("required") and not _has_value(values.get(field["name"]))
    ]


def _question_for_field(field: Dict[str, Any], gen: Dict[str, Any]) -> str:
    name = field["name"]
    base = FIELD_QUESTIONS.get(name)
    if not base:
        description = str(field.get("description") or "").strip()
        base = f"Please provide the {name.replace('_', ' ')}."
        if description:
            base += f" ({description})"
    progress = _field_progress(gen["template_name"], gen["values"])
    if progress["total"]:
        base += (
            f" This is required for the {_template_label(gen['template_name'])} "
            f"({progress['completed']}/{progress['total']} required details collected)."
        )
    return base


def generation_snapshot(gen: Dict[str, Any]) -> Dict[str, Any]:
    """Return public workflow state.

    Field values and the user's raw answers are intentionally omitted; they are
    available only through the explicit review/edit endpoint.
    """
    fields = get_template_fields(gen.get("template_name", ""))
    field_by_name = {field["name"]: field for field in fields}
    missing = _missing_fields(gen.get("template_name", ""), gen.get("values") or {})
    pending = field_by_name.get(gen.get("pending_field") or "")
    result = gen.get("result") or {}
    status = gen.get("status", "collecting")
    return {
        "id": gen.get("id"),
        "status": status,
        "template_name": gen.get("template_name"),
        "template_label": _template_label(gen.get("template_name", "")),
        "user_request": gen.get("user_request", ""),
        "question": gen.get("question", ""),
        "pending_field": (
            {
                "name": pending["name"],
                "label": _field_label(pending["name"]),
                "description": pending.get("description", ""),
            }
            if pending
            else None
        ),
        "missing_fields": [
            {
                "name": field["name"],
                "label": _field_label(field["name"]),
                "description": field.get("description", ""),
            }
            for field in missing
        ],
        "progress": _field_progress(gen.get("template_name", ""), gen.get("values") or {}),
        "field_count": len(fields),
        "review_ready": bool(fields) and not missing,
        "result": (
            {
                "status": result.get("status"),
                "message": result.get("message", ""),
                "template_name": result.get("template_name"),
                "filename": result.get("filename"),
                "download_url": result.get("download_url"),
            }
            if result
            else None
        ),
        "error": gen.get("error"),
        "can_edit": status in {"collecting", "review", "completed", "error", "cancelled"},
        "can_cancel": status in {"collecting", "review", "generating", "error"},
        "can_retry": status == "error",
        "created_at": gen.get("created_at"),
        "updated_at": gen.get("updated_at"),
    }


def get_generation_fields(session: CaseSession, generation_id: str) -> Optional[Dict[str, Any]]:
    """Return field definitions and current values for the review modal."""
    gen = session.generations.get(generation_id)
    if gen is None:
        return None
    fields = get_template_fields(gen.get("template_name", ""))
    values = gen.get("values") or {}
    sources = gen.get("value_sources") or {}
    missing = _missing_fields(gen.get("template_name", ""), values)
    missing_names = {field["name"] for field in missing}
    return {
        "case_id": session.session_id,
        "generation_id": gen.get("id"),
        "status": gen.get("status"),
        "template_name": gen.get("template_name"),
        "template_label": _template_label(gen.get("template_name", "")),
        "user_request": gen.get("user_request", ""),
        "fields": [
            {
                "name": field["name"],
                "label": _field_label(field["name"]),
                "description": field.get("description", ""),
                "required": bool(field.get("required")),
                "default": str(field.get("default") or ""),
                "value": str(values.get(field["name"]) or ""),
                "source": sources.get(field["name"], ""),
                "missing": field["name"] in missing_names,
            }
            for field in fields
        ],
        "missing_fields": [
            {"name": field["name"], "label": _field_label(field["name"])}
            for field in missing
        ],
        "progress": _field_progress(gen.get("template_name", ""), values),
        "can_generate": not missing,
    }


def _store_and_event(session: CaseSession, gen: Dict[str, Any], status_event: str = "update") -> None:
    gen["updated_at"] = utcnow()
    session.generations[gen["id"]] = gen
    session.add_ui_event(
        "generation",
        generation=generation_snapshot(gen),
        generation_event=status_event,
    )
    session.touch()


def _result(session: CaseSession, gen: Dict[str, Any], *, kind: str = "generation") -> Dict[str, Any]:
    return {
        "kind": kind,
        "generation": generation_snapshot(gen),
        "case_id": session.session_id,
    }


def _unsupported_answer(template_name: str) -> str:
    supported = get_supported_templates()
    supported_text = ", ".join(item["name"] for item in supported) or "none"
    available = ", ".join(item["name"] for item in get_template_catalog())
    return (
        f"I can start the document workflow, but **{_template_label(template_name)}** "
        "is not configured with fillable fields yet, so I will not invent its contents.\n\n"
        f"Fully supported templates: {supported_text}. "
        f"DOCX templates present: {available}.\n\n"
        "Please request a supported document (for example, a bail application)."
    )


def start_generation(session: CaseSession, message: str) -> Dict[str, Any]:
    existing = session.get_active_generation()
    if existing and existing.get("status") == "collecting":
        return _result(session, existing)

    template = detect_generation_request(message)
    if not template:
        return {
            "kind": "message",
            "answer": "Tell me what legal document you want to draft, for example a bail application.",
        }
    if not _template_file_exists(template) or not get_template_fields(template):
        answer = _unsupported_answer(template)
        session.add_message("user", message)
        session.add_message("assistant", answer)
        return {"kind": "message", "answer": answer, "case_id": session.session_id}

    # The request itself is shown in the chat, but generation answers are kept
    # in the generation session rather than injected into every RAG prompt.
    session.add_message("user", message, record_history=False)

    gen: Dict[str, Any] = {
        "id": new_id("gen_"),
        "session_id": session.session_id,
        "template_name": template,
        "user_request": message,
        "status": "collecting",
        "values": {},
        "value_sources": {},
        "locked_fields": [],
        "field_edits": [],
        "answers": [],
        "pending_field": None,
        "question": "",
        "error": None,
        "result": None,
        "reviewed_at": None,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    session.generations[gen["id"]] = gen
    session.active_generation_id = gen["id"]

    try:
        fields = get_template_fields(template)
        # A new draft starts from analyzed case documents and the new request,
        # never from answers given for a previous person/document.
        known_facts = _generation_known_facts(session, include_draft_answers=False)
        values: Dict[str, str] = {}
        sources: Dict[str, str] = {}
        for field in fields:
            name = field["name"]
            if _has_value(known_facts.get(name)):
                values[name] = truncate_chars(known_facts[name], 500)
                sources[name] = "case documents"
        required_names = [field["name"] for field in fields if field.get("required")]
        if any(not _has_value(values.get(name)) for name in required_names):
            # Only spend a Groq call when the case already lacks required data.
            context = _generation_context(session, message)
            extraction = extract_fields_from_context(
                prompt=message,
                case_context=context,
                fields=fields,
                known_facts=known_facts,
            )
            for field in fields:
                name = field["name"]
                if _has_value(extraction.values.get(name)):
                    values[name] = truncate_chars(extraction.values[name], 500)
                    sources[name] = "request"
        gen["values"] = values
        gen["value_sources"] = sources
    except Exception as exc:
        print(f"[Generation] start error: {type(exc).__name__}: {exc}", flush=True)
        gen["error"] = (
            "I could not prepare the document workflow. Your case data is safe. "
            "Please retry."
        )
        gen["status"] = "error"
        _store_and_event(session, gen)
        return _result(session, gen)

    return _advance(session, gen)


def _generation_context(session: CaseSession, request: str) -> str:
    from case_context import build_generation_context

    return build_generation_context(
        session, request, max_tokens=GENERATION_CONTEXT_TOKEN_BUDGET
    )


def _generation_known_facts(
    session: CaseSession,
    *,
    include_draft_answers: bool = False,
) -> Dict[str, str]:
    from case_context import case_facts_for_generation

    return case_facts_for_generation(
        session, include_draft_answers=include_draft_answers
    )


def _advance(
    session: CaseSession,
    gen: Dict[str, Any],
    *,
    auto_generate: bool = False,
) -> Dict[str, Any]:
    template_name = gen["template_name"]
    fields = get_template_fields(template_name)
    locked = set(gen.get("locked_fields") or [])
    sources = gen.setdefault("value_sources", {})

    # Reports may be corrected (or another document analyzed) while the
    # workflow is collecting answers. Use the latest corrected facts only for
    # fields the user has not supplied or edited.
    known = _generation_known_facts(session, include_draft_answers=False)
    for field in fields:
        name = field["name"]
        if name in locked:
            continue
        if not _has_value(gen["values"].get(name)) and _has_value(known.get(name)):
            gen["values"][name] = truncate_chars(known[name], 500)
            sources[name] = "case documents"

    missing = _missing_fields(template_name, gen.get("values") or {})

    if missing:
        field = missing[0]
        gen["status"] = "collecting"
        gen["pending_field"] = field["name"]
        gen["question"] = _question_for_field(field, gen)
        gen["error"] = None
        _store_and_event(session, gen)
        return _result(session, gen)

    if auto_generate:
        return _render_generation(session, gen)

    gen["status"] = "review"
    gen["pending_field"] = None
    gen["question"] = ""
    gen["error"] = None
    _store_and_event(session, gen)
    return _result(session, gen)


def _render_generation(session: CaseSession, gen: Dict[str, Any]) -> Dict[str, Any]:
    template_name = gen["template_name"]
    gen["status"] = "generating"
    gen["pending_field"] = None
    gen["question"] = ""
    gen["error"] = None
    if session.active_generation_id is None:
        session.active_generation_id = gen["id"]
    _store_and_event(session, gen)

    try:
        context = _generation_context(session, gen["user_request"])
        result = generate_document(
            user_prompt=gen["user_request"],
            case_history="",
            session_context={
                "session_id": session.session_id,
                "document_context": context,
                "case_facts": dict(gen["values"]),
            },
            template_name=template_name,
            provided_values=dict(gen["values"]),
            force_generation=False,
        )

        if result.get("status") == "success":
            gen["status"] = "completed"
            gen["values"] = {
                **dict(gen.get("values") or {}),
                **dict(result.get("collected_values") or {}),
            }
            gen["result"] = result
            session.add_generated_document(
                template_name,
                result.get("file_path", ""),
                result.get("download_url", ""),
                result.get("collected_values") or {},
                generation_id=gen["id"],
            )
            if session.active_generation_id == gen["id"]:
                session.active_generation_id = None
            _store_and_event(session, gen, "completed")
            return _result(session, gen)

        if result.get("status") == "missing_fields":
            sources = gen.setdefault("value_sources", {})
            for name, value in (result.get("collected_values") or {}).items():
                if _has_value(value):
                    gen["values"][name] = truncate_chars(value, 500)
                    sources.setdefault(name, "request")
            gen["status"] = "collecting"
            missing = _missing_fields(template_name, gen["values"])
            if missing:
                field = missing[0]
                gen["pending_field"] = field["name"]
                gen["question"] = _question_for_field(field, gen)
            _store_and_event(session, gen)
            return _result(session, gen)

        gen["status"] = "error"
        gen["error"] = result.get("message") or "The document could not be generated."
        _store_and_event(session, gen)
        return _result(session, gen)
    except Exception as exc:
        print(f"[Generation] generation error: {type(exc).__name__}: {exc}", flush=True)
        gen["status"] = "error"
        gen["error"] = (
            "The document could not be generated because the language model or "
            "template rendering failed. Your answers are saved; retry or edit the details."
        )
        _store_and_event(session, gen)
        return _result(session, gen)


def update_generation_fields(
    session: CaseSession,
    generation_id: str,
    values: Dict[str, Any],
    *,
    generate: bool = True,
) -> Optional[Dict[str, Any]]:
    """Apply reviewed/edited values, then optionally render the document."""
    gen = session.generations.get(generation_id)
    if gen is None:
        return None
    if gen.get("status") == "generating":
        raise GenerationConflict("This document is already being generated.")

    active = session.get_active_generation()
    if (
        active
        and active.get("id") != generation_id
        and active.get("status") in {"collecting", "review", "generating"}
    ):
        raise GenerationConflict(
            "Finish or cancel the current draft before editing another one."
        )

    fields = get_template_fields(gen.get("template_name", ""))
    field_names = {field["name"] for field in fields}
    gen.setdefault("locked_fields", [])
    gen.setdefault("value_sources", {})
    gen.setdefault("field_edits", [])
    gen_values = gen.setdefault("values", {})
    now = utcnow()

    for name, raw_value in (values or {}).items():
        if name not in field_names:
            continue
        new_value = truncate_chars(
            str(raw_value if raw_value is not None else ""), 800, suffix=""
        )
        old_value = str(gen_values.get(name) or "")
        if old_value.strip() != new_value.strip():
            gen["field_edits"].append(
                {
                    "field": name,
                    "old_value": old_value,
                    "new_value": new_value,
                    "at": now,
                }
            )
        if new_value:
            gen_values[name] = new_value
            session.extra_case_details[name] = new_value
        else:
            gen_values.pop(name, None)
            session.extra_case_details.pop(name, None)
        if name not in gen["locked_fields"]:
            gen["locked_fields"].append(name)
        gen["value_sources"][name] = "you"
    gen["reviewed_at"] = now

    if not generate and gen.get("status") == "completed":
        # Keep the last download visible; the edits take effect on regenerate.
        _store_and_event(session, gen)
        return _result(session, gen)

    missing = _missing_fields(gen.get("template_name", ""), gen_values)
    if generate:
        if not missing:
            return _render_generation(session, gen)
        field = missing[0]
        gen["status"] = "collecting"
        gen["pending_field"] = field["name"]
        gen["question"] = _question_for_field(field, gen)
        gen["error"] = None
        _store_and_event(session, gen)
        return _result(session, gen)

    gen["error"] = None
    if missing:
        field = missing[0]
        gen["status"] = "collecting"
        gen["pending_field"] = field["name"]
        gen["question"] = _question_for_field(field, gen)
    else:
        gen["status"] = "review"
        gen["pending_field"] = None
        gen["question"] = ""
    _store_and_event(session, gen)
    return _result(session, gen)


def continue_generation(session: CaseSession, message: str) -> Optional[Dict[str, Any]]:
    gen = session.get_active_generation()
    if not gen or gen.get("status") != "collecting":
        return None

    text = (message or "").strip()

    if _is_new_draft_request(text):
        cancel_generation(session)
        return start_generation(session, text)

    if text.lower() in CANCEL_WORDS:
        session.add_message("user", text, record_history=False)
        cancelled = cancel_generation(session)
        return _result(session, cancelled) if cancelled else None

    if not text:
        _store_and_event(session, gen)
        return _result(session, gen)

    field_name = gen.get("pending_field")
    fields = get_template_fields(gen["template_name"])
    if not field_name:
        return _advance(session, gen)
    field = next((item for item in fields if item["name"] == field_name), None)

    if field is not None:
        normalized = normalize_field_answer(
            field,
            fields,
            gen.get("question", ""),
            text,
        )
    else:
        normalized = {
            field_name: truncate_chars(
                text, MAX_GENERATION_ANSWER_CHARS, suffix=""
            )
        }

    sources = gen.setdefault("value_sources", {})
    locked = gen.setdefault("locked_fields", [])
    for name, value in normalized.items():
        if not _has_value(value):
            continue
        gen["values"][name] = truncate_chars(value, 800, suffix="")
        sources[name] = "you"
        if name not in locked:
            locked.append(name)
    if not _has_value(gen["values"].get(field_name)):
        gen["values"][field_name] = truncate_chars(
            text, MAX_GENERATION_ANSWER_CHARS, suffix=""
        )
        sources[field_name] = "you"
        if field_name not in locked:
            locked.append(field_name)

    gen["answers"].append(
        {
            "field": field_name,
            "label": _field_label(field_name),
            "question": gen.get("question", ""),
            "answer": text,
            "value": gen["values"].get(field_name, ""),
            "at": utcnow(),
        }
    )
    session.extra_case_details[field_name] = gen["values"].get(field_name, "")
    # The raw reply is kept for the generation record and case context, but
    # field values must never appear as chat bubbles in the transcript.
    session.add_message("user", text, record_history=False, visible=False)
    gen["pending_field"] = None
    gen["question"] = ""
    return _advance(session, gen)


def cancel_generation(session: CaseSession) -> Optional[Dict[str, Any]]:
    gen = session.get_active_generation()
    if not gen:
        return None
    gen["status"] = "cancelled"
    gen["pending_field"] = None
    gen["question"] = ""
    gen["error"] = None
    session.active_generation_id = None
    _store_and_event(session, gen)
    return gen


def retry_generation(session: CaseSession) -> Optional[Dict[str, Any]]:
    gen = session.get_active_generation()
    if not gen:
        # Retry the most recent failed generation if it is no longer active.
        failed = [
            item
            for item in session.generations.values()
            if item.get("status") == "error"
        ]
        if not failed:
            return None
        gen = failed[-1]
    if gen.get("status") not in {"error", "cancelled"}:
        return _result(session, gen)
    was_error = gen.get("status") == "error"
    gen["error"] = None
    gen["status"] = "collecting"
    session.active_generation_id = gen["id"]
    return _advance(session, gen, auto_generate=was_error)


def retry_word_requested(message: str) -> bool:
    return (message or "").strip().lower() in RETRY_WORDS
