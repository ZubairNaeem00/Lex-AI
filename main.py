"""LegalLens FastAPI backend.

One case session drives:
- LlamaParse document extraction + dynamic Groq analysis reports,
- editable reports and corrected case facts,
- the legal RAG chat,
- the dedicated multi-turn document-generation workflow,
- generated DOCX downloads.

Run with: uvicorn main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import copy
import os
import tempfile
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv(".env")

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from case_context import annotate_report, apply_edit_path
from context_budget import (
    CASE_CONTEXT_TOKEN_BUDGET,
    HISTORY_TOKEN_BUDGET,
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    RETRIEVAL_TOKEN_BUDGET,
)
from doc_generation import (
    GENERATED_FOLDER,
    get_supported_templates,
    get_template_catalog,
)
from document_analysis import (
    AnalysisConfigError,
    DocumentAnalysis,
    DocumentAnalysisError,
    analyze_document,
    extract_text,
)
from generation_workflow import (
    CANCEL_WORDS,
    GenerationConflict,
    GenerationDocumentMissing,
    cancel_generation,
    continue_generation,
    detect_generation_request,
    generation_snapshot,
    get_generation_fields,
    read_generation_document,
    retry_generation,
    retry_word_requested,
    save_generation_document,
    start_generation,
    update_generation_fields,
)
from legal_agent import (
    CASES_INDEX_PATH,
    LAW_INDEX_PATH,
    OLLAMA_MODEL,
    ask_legal_agent,
    retrieval_status,
)
from session_manager import CaseSession, session_manager, utcnow
from api import ALL_ROUTERS
from auth.config import AUTH_SETTINGS
from auth.deps import AuthenticatedUser, deny_anonymous, get_optional_user
from auth.rate_limit import configure as configure_rate_limiter
from db import persistence
from db.config import database

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = Path(GENERATED_FOLDER).resolve()

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

app = FastAPI(title="LegalLens — Pakistani Legal AI", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

configure_rate_limiter(app)
for _router in ALL_ROUTERS:
    app.include_router(_router)


def _user_or_401(user: Optional[AuthenticatedUser]) -> AuthenticatedUser:
    """The AI routes are account-scoped once AUTH_REQUIRED is on."""
    deny_anonymous(user)
    return user  # type: ignore[return-value]


def _runtime_session(case_id: str, user: Optional[AuthenticatedUser]) -> CaseSession:
    """Resolve a live session for this account, restoring it from MongoDB.

    A session owned by somebody else is reported as 404 so case ids cannot be
    probed, matching how the durable `/api/cases` routes behave.
    """
    _user_or_401(user)
    try:
        session = persistence.resolve(case_id, user)
    except PermissionError:
        raise HTTPException(404, "Case not found. Start a new case.") from None
    if session is None:
        raise HTTPException(404, "Case not found. Start a new case.")
    return session


def _persisted_sessions(user: Optional[AuthenticatedUser]) -> List[Dict[str, Any]]:
    """Sidebar list: this account's durable cases, falling back to live memory."""
    if user is None:
        return session_manager.list_sessions()
    result = persistence.list_for_user(user)
    if result is None:
        return session_manager.list_sessions()
    return result


class ChatRequest(BaseModel):
    case_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=12000)


class EditOperation(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    value: str = Field(default="", max_length=5000)


class EditReportRequest(BaseModel):
    edits: list[EditOperation] = Field(min_length=1, max_length=60)


class GenerationFieldsRequest(BaseModel):
    values: Dict[str, str] = Field(default_factory=dict)
    generate: bool = True


class GenerationDocumentRequest(BaseModel):
    html: str = Field(default="", max_length=600_000)


class SessionUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    pinned: Optional[bool] = None


def _session_payload(session: CaseSession) -> dict:
    snapshot = session.snapshot()
    document_map = {doc.document_id: doc for doc in session.documents.values()}
    for document in snapshot.get("documents") or []:
        stored = document_map.get(document["document_id"])
        if stored is not None:
            document["report"] = annotate_report(stored.report, stored.edits)
    active = session.get_active_generation()
    snapshot["generation"] = generation_snapshot(active) if active else None
    snapshot["generations"] = [
        generation_snapshot(gen) for gen in session.generations.values()
    ]
    snapshot["limits"] = {
        "max_input_tokens": MAX_INPUT_TOKENS,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "history_token_budget": HISTORY_TOKEN_BUDGET,
        "case_context_token_budget": CASE_CONTEXT_TOKEN_BUDGET,
        "retrieval_token_budget": RETRIEVAL_TOKEN_BUDGET,
        "max_upload_mb": MAX_UPLOAD_MB,
    }
    snapshot["server_time"] = utcnow()
    snapshot["storage"] = "mongodb" if persistence.enabled() else "in-memory"
    return snapshot


@app.get("/")
def home():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(500, "Frontend files are missing from static/.")
    return FileResponse(str(index))


@app.get("/api/health")
def health():
    groq_ok = bool(os.getenv("GROQ_API_KEY"))
    llama_ok = bool(os.getenv("LLAMA_CLOUD_API_KEY"))
    cases_present = Path(CASES_INDEX_PATH).exists()
    law_present = Path(LAW_INDEX_PATH).exists()
    warnings = []
    if not groq_ok:
        warnings.append("GROQ_API_KEY is missing.")
    if not llama_ok:
        warnings.append("LLAMA_CLOUD_API_KEY is missing.")
    if not cases_present:
        warnings.append(
            "The FAISS cases index is missing; legal answers will have no retrieved precedents."
        )
    if not law_present:
        warnings.append(
            "The FAISS statutes index (faiss_index_law) is missing; legal answers will "
            "have no retrieved statutory provisions."
        )
    mongo = database.status()
    if not mongo["connected"]:
        warnings.append(
            f"MongoDB is not connected ({mongo.get('reason', 'unknown')}); "
            "accounts and cases are not being stored."
        )
    return {
        "status": "ok" if not warnings else "degraded",
        "groq_configured": groq_ok,
        "llama_configured": llama_ok,
        "model": GROQ_MODEL,
        "legal_model": OLLAMA_MODEL,
        "index_present": cases_present,
        "cases_index_present": cases_present,
        "law_index_present": law_present,
        "retrievers": retrieval_status(),
        "templates": get_supported_templates(),
        "template_catalog": get_template_catalog(),
        "warnings": warnings,
        "database": {
            "enabled": mongo["enabled"],
            "connected": mongo["connected"],
            "name": mongo["database"],
            "reason": mongo.get("reason"),
        },
        "auth_required": AUTH_SETTINGS.auth_required,
        "storage": "mongodb" if persistence.enabled() else "in-memory",
        "limits": {
            "max_input_tokens": MAX_INPUT_TOKENS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_upload_mb": MAX_UPLOAD_MB,
        },
    }


@app.get("/api/templates")
def templates():
    return {
        "supported": get_supported_templates(),
        "catalog": get_template_catalog(),
    }


@app.post("/api/sessions")
def create_session(user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    _user_or_401(user)
    session = session_manager.create_session()
    if user is not None:
        persistence.bind(session, user)
    return _session_payload(session)


@app.get("/api/sessions")
def list_sessions(user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    _user_or_401(user)
    return {
        "sessions": _persisted_sessions(user),
        "storage": "mongodb" if persistence.enabled() else "in-memory",
    }


@app.get("/api/sessions/{case_id}")
def get_session(case_id: str, user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    return _session_payload(session)


@app.patch("/api/sessions/{case_id}")
def update_session(case_id: str, payload: SessionUpdateRequest,
                   user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    """Rename or pin a conversation from the sidebar."""
    session = _runtime_session(case_id, user)
    if payload.name is None and payload.pinned is None:
        raise HTTPException(400, "Provide a name or a pinned flag.")
    title = session.title
    if payload.name is not None:
        renamed = persistence.rename(user, session, payload.name)
        if renamed is None:
            raise HTTPException(400, "The conversation name cannot be blank.")
        title = renamed
    pinned = persistence.is_pinned(user, session)
    if payload.pinned is not None:
        pinned = persistence.set_pinned(user, session, payload.pinned)
    return {"case_id": session.session_id, "title": title, "pinned": bool(pinned)}


@app.delete("/api/sessions/{case_id}")
def delete_session(case_id: str, only_if_empty: bool = False,
                   user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    """Delete a conversation. `only_if_empty` is what New Conversation uses to
    reclaim the blank case it just left behind, and can never remove real work."""
    session = _runtime_session(case_id, user)
    outcome = persistence.drop(user, session, only_if_empty=only_if_empty)
    if not outcome.get("deleted") and outcome.get("persisted"):
        raise HTTPException(409, outcome.get("reason") or "Conversation cannot be deleted.")
    deleted = session_manager.delete_session(session.session_id)
    if not deleted and not outcome.get("deleted"):
        raise HTTPException(404, "Case not found.")
    return {"deleted": True, "case_id": session.session_id, "persisted": outcome.get("persisted", False)}


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    case_id: Optional[str] = Form(default=None),
    user: Optional[AuthenticatedUser] = Depends(get_optional_user),
):
    _user_or_401(user)
    original_name = Path(file.filename or "upload").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            400,
            "Supported formats: PDF, PNG, JPG, WEBP, TIFF. "
            "Convert other files to PDF before uploading.",
        )

    if case_id:
        session = _runtime_session(case_id, user)
    else:
        session = session_manager.create_session()
        if user is not None:
            persistence.bind(session, user)

    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await file.close()

    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is too large. Maximum size is {MAX_UPLOAD_MB} MB.")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp.write(data)
            temp_path = temp.name

        extracted = await run_in_threadpool(extract_text, temp_path)
        report = await run_in_threadpool(analyze_document, extracted)
        document = session.add_document(
            filename=original_name,
            extracted_text=extracted,
            report=report,
        )
        persistence.sync_session(session)
        return {
            "case_id": session.session_id,
            "document_id": document.document_id,
            "filename": document.filename,
            "report": annotate_report(document.report, document.edits),
            "edits": [],
            "extracted_characters": len(extracted),
            "case_title": session.title,
        }
    except (AnalysisConfigError, DocumentAnalysisError) as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        print("[Analyze] unexpected error:\n" + traceback.format_exc(), flush=True)
        raise HTTPException(
            502,
            f"Analysis failed ({type(exc).__name__}). Check the server terminal and API keys.",
        ) from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@app.put("/api/sessions/{case_id}/documents/{document_id}/report")
def edit_report(case_id: str, document_id: str, payload: EditReportRequest,
                user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    with session.lock:
        document = session.get_document(document_id)
        if document is None:
            raise HTTPException(404, "Document not found in this case.")

        working = copy.deepcopy(document.report)
        applied = []
        for operation in payload.edits:
            try:
                old_value, new_value = apply_edit_path(
                    working, operation.path, operation.value
                )
            except ValueError as exc:
                raise HTTPException(
                    400, f"Invalid edit '{operation.path}': {exc}"
                ) from exc
            if old_value != new_value:
                applied.append(
                    {
                        "path": operation.path,
                        "old_value": old_value,
                        "new_value": new_value,
                        "edited_at": utcnow(),
                    }
                )

        try:
            validated = DocumentAnalysis.model_validate(working).model_dump()
        except Exception as exc:
            raise HTTPException(422, f"Edited report is not valid: {exc}") from exc

        if applied:
            document = session.update_document_report(document_id, validated, applied)
        report = annotate_report(document.report, document.edits)
        persistence.sync_session(session)
        return {
            "case_id": case_id,
            "document_id": document_id,
            "report": report,
            "edits": document.edits,
            "applied_edits": applied,
            "case_title": session.title,
        }


@app.get("/api/sessions/{case_id}/documents/{document_id}/text")
def get_document_text(case_id: str, document_id: str,
                      user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    document = session.get_document(document_id)
    if document is None:
        raise HTTPException(404, "Document not found in this case.")
    return {
        "case_id": case_id,
        "document_id": document_id,
        "filename": document.filename,
        "extracted_text": document.extracted_text,
        "original_report": copy.deepcopy(document.original_report),
        "current_report": annotate_report(document.report, document.edits),
        "edits": copy.deepcopy(document.edits),
        "uploaded_at": document.uploaded_at,
    }


@app.post("/api/chat")
def chat(payload: ChatRequest, user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(payload.case_id, user)
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "Please enter a message.")

    try:
        with session.lock:
            session.title_from_message(message)
            return _run_chat_step(session, message)
    finally:
        persistence.sync_session(session)


def _run_chat_step(session: CaseSession, message: str) -> dict:
    try:
        active = session.get_active_generation()
        if active and active.get("status") == "collecting":
            result = continue_generation(session, message)
            if result is not None:
                return result

        if active and active.get("status") == "error":
            if retry_word_requested(message):
                result = retry_generation(session)
                if result is not None:
                    result.setdefault("case_id", session.session_id)
                    return result
            if message.lower() in CANCEL_WORDS:
                session.add_message("user", message, record_history=False)
                cancelled = cancel_generation(session)
                if cancelled is not None:
                    return {
                        "kind": "generation",
                        "generation": generation_snapshot(cancelled),
                        "case_id": session.session_id,
                    }

        if active and active.get("status") == "review" and message.lower() in CANCEL_WORDS:
            session.add_message("user", message, record_history=False)
            cancelled = cancel_generation(session)
            if cancelled is not None:
                return {
                    "kind": "generation",
                    "generation": generation_snapshot(cancelled),
                    "case_id": session.session_id,
                }

        if active and active.get("status") == "generating":
            return {
                "kind": "generation",
                "generation": generation_snapshot(active),
                "case_id": session.session_id,
            }

        if detect_generation_request(message):
            result = start_generation(session, message)
            result.setdefault("case_id", session.session_id)
            return result

        result = ask_legal_agent(message, session.session_id)
        return {"kind": "legal", "case_id": session.session_id, **result}
    except HTTPException:
        raise
    except Exception as exc:
        print("[Chat] unexpected error:\n" + traceback.format_exc(), flush=True)
        raise HTTPException(
            500,
            f"The request failed ({type(exc).__name__}). "
            "Your case data is intact; please retry.",
        ) from exc


@app.get("/api/sessions/{case_id}/generation")
def get_generation(case_id: str, user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    active = session.get_active_generation()
    return {
        "case_id": case_id,
        "generation": generation_snapshot(active) if active else None,
        "generations": [
            generation_snapshot(gen) for gen in session.generations.values()
        ],
    }


@app.get("/api/sessions/{case_id}/generation/{generation_id}/fields")
def read_generation_fields(case_id: str, generation_id: str,
                           user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    payload = get_generation_fields(session, generation_id)
    if payload is None:
        raise HTTPException(404, "Document generation not found in this case.")
    return payload


@app.put("/api/sessions/{case_id}/generation/{generation_id}/fields")
def write_generation_fields(
    case_id: str,
    generation_id: str,
    payload: GenerationFieldsRequest,
    user: Optional[AuthenticatedUser] = Depends(get_optional_user),
):
    session = _runtime_session(case_id, user)
    with session.lock:
        try:
            result = update_generation_fields(
                session,
                generation_id,
                payload.values,
                generate=payload.generate,
            )
        except GenerationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        if result is None:
            raise HTTPException(404, "Document generation not found in this case.")
        persistence.sync_session(session)
        result.setdefault("case_id", case_id)
        return result


@app.get("/api/sessions/{case_id}/generation/{generation_id}/document")
def preview_generation_document(
    case_id: str,
    generation_id: str,
    user: Optional[AuthenticatedUser] = Depends(get_optional_user),
):
    """Editable Word-style HTML for a completed draft, read from its DOCX."""
    session = _runtime_session(case_id, user)
    with session.lock:
        try:
            payload = read_generation_document(session, generation_id)
        except GenerationDocumentMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            print("[DraftPreview] unexpected error:\n" + traceback.format_exc(), flush=True)
            raise HTTPException(
                500, "This draft could not be opened for editing. Download still works."
            ) from exc
    if not payload:
        raise HTTPException(404, "Document generation not found in this case.")
    return payload


@app.put("/api/sessions/{case_id}/generation/{generation_id}/document")
def revise_generation_document(
    case_id: str,
    generation_id: str,
    payload: GenerationDocumentRequest,
    user: Optional[AuthenticatedUser] = Depends(get_optional_user),
):
    """Save the edited draft as a new DOCX revision served by the download route."""
    session = _runtime_session(case_id, user)
    if not payload.html.strip():
        raise HTTPException(400, "The edited draft is empty, so nothing was saved.")
    with session.lock:
        try:
            result = save_generation_document(session, generation_id, payload.html)
        except GenerationDocumentMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except GenerationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, SyntaxError) as exc:
            raise HTTPException(
                400, f"The edited draft could not be saved ({type(exc).__name__})."
            ) from exc
        except Exception as exc:
            print("[DraftRevision] unexpected error:\n" + traceback.format_exc(), flush=True)
            raise HTTPException(500, "The revised draft could not be saved.") from exc
        if not result:
            raise HTTPException(404, "Document generation not found in this case.")
        persistence.sync_session(session)
        return result


@app.post("/api/sessions/{case_id}/generation/cancel")
def cancel_document_generation(case_id: str,
                               user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    with session.lock:
        gen = cancel_generation(session)
        if gen is None:
            raise HTTPException(409, "There is no active document-generation workflow.")
        persistence.sync_session(session)
        return {
            "kind": "generation",
            "generation": generation_snapshot(gen),
            "case_id": case_id,
        }


@app.post("/api/sessions/{case_id}/generation/retry")
def retry_document_generation(case_id: str,
                              user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    with session.lock:
        result = retry_generation(session)
        if result is None:
            raise HTTPException(409, "There is no failed document-generation workflow to retry.")
        persistence.sync_session(session)
        result.setdefault("case_id", case_id)
        return result


@app.get("/sessions/{case_id}/download/{filename}")
def download_generated_document(case_id: str, filename: str,
                                user: Optional[AuthenticatedUser] = Depends(get_optional_user)):
    session = _runtime_session(case_id, user)
    safe_name = Path(filename).name
    metadata = session.find_generated_document(safe_name)
    if metadata is None:
        raise HTTPException(404, "Generated document not found for this case.")

    candidate = Path(metadata.get("file_path") or (GENERATED_DIR / safe_name))
    try:
        resolved = candidate.resolve()
    except OSError:
        raise HTTPException(404, "Generated document path is invalid.") from None

    if GENERATED_DIR not in resolved.parents or not resolved.is_file():
        raise HTTPException(404, "Generated document file is missing.")

    return FileResponse(
        str(resolved),
        filename=safe_name,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
