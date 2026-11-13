"""Shared in-memory case sessions.

A case/session owns all data used by the app:
- the full chat history used by the RAG agent,
- UI events (messages, analysis cards, generation cards),
- uploaded documents with their full extracted text, current report, original
  report, and edit history,
- the document-generation workflow state and generated-document metadata.

The demo stores sessions in memory. Restarting the server clears all cases;
this limitation is documented in README.md. Full documents/history are kept
here, while prompts only receive bounded extracts built by case_context.py.
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}"


@dataclass
class CaseDocument:
    document_id: str
    filename: str
    extracted_text: str
    report: Dict[str, Any]
    original_report: Dict[str, Any]
    edits: List[Dict[str, Any]] = field(default_factory=list)
    uploaded_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)

    def public(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "report": copy.deepcopy(self.report),
            "edits": copy.deepcopy(self.edits),
            "uploaded_at": self.uploaded_at,
            "updated_at": self.updated_at,
            "characters": len(self.extracted_text or ""),
            "has_extracted_text": bool(self.extracted_text),
        }


@dataclass
class CaseSession:
    session_id: str
    title: str = "New case"
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    history: List[BaseMessage] = field(default_factory=list)
    ui_events: List[Dict[str, Any]] = field(default_factory=list)
    documents: "OrderedDict[str, CaseDocument]" = field(default_factory=OrderedDict)
    extra_case_details: Dict[str, str] = field(default_factory=dict)
    generations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_generation_id: Optional[str] = None
    generated_documents: List[Dict[str, Any]] = field(default_factory=list)
    # Owning account (str ObjectId) once a token is presented; empty = anonymous demo.
    user_id: Optional[str] = None
    # Mongo mirror bookkeeping: cursors and ObjectIds, never user-visible content.
    sync: Dict[str, Any] = field(default_factory=dict, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def langchain_messages(self) -> List[BaseMessage]:
        return self.history

    def touch(self) -> None:
        self.updated_at = utcnow()

    def add_message(
        self,
        role: str,
        content: str,
        *,
        sources: Optional[List[str]] = None,
        tool_called: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        record_history: bool = True,
        visible: bool = True,
    ) -> None:
        content = str(content or "")
        with self.lock:
            if record_history:
                message: BaseMessage = (
                    HumanMessage(content=content)
                    if role == "user"
                    else AIMessage(content=content)
                )
                self.history.append(message)
            event: Dict[str, Any] = {
                "type": "message",
                "role": role,
                "content": content,
                "ts": utcnow(),
                "in_history": bool(record_history),
            }
            if not visible:
                event["hidden"] = True
            if sources:
                event["sources"] = list(sources)
            if tool_called:
                event["tool_called"] = tool_called
            if extra:
                event.update(extra)
            self.ui_events.append(event)
            self.touch()

    def add_ui_event(self, event_type: str, **payload: Any) -> Dict[str, Any]:
        with self.lock:
            event = {"type": event_type, "ts": utcnow(), **payload}
            self.ui_events.append(event)
            self.touch()
            return event

    def title_from_message(self, text: str) -> bool:
        """Name an untouched case after its first message, the way chat apps do.

        Only ever fires while the case still carries the placeholder name, so a
        manual rename or an analysis-derived title is never overwritten.
        """
        cleaned = " ".join(str(text or "").split()).strip(" \t\r\n.,;:!?")
        if not cleaned:
            return False
        with self.lock:
            if self.title != "New case":
                return False
            self.title = cleaned[:48] + ("…" if len(cleaned) > 48 else "")
            self.touch()
            return True

    def add_document(
        self,
        *,
        filename: str,
        extracted_text: str,
        report: Dict[str, Any],
        document_id: Optional[str] = None,
        uploaded_at: Optional[str] = None,
    ) -> CaseDocument:
        with self.lock:
            document = CaseDocument(
                document_id=document_id or new_id("doc_"),
                filename=filename,
                extracted_text=extracted_text,
                report=copy.deepcopy(report),
                original_report=copy.deepcopy(report),
                uploaded_at=uploaded_at or utcnow(),
            )
            self.documents[document.document_id] = document
            if self.title == "New case":
                doc_type = str(report.get("document_type") or "").strip()
                if not doc_type or doc_type.lower() == "unknown":
                    doc_type = str(report.get("title") or "").strip()
                self.title = (doc_type or "Legal document")[:80]
            self.add_ui_event("analysis", document_id=document.document_id)
            return document

    def get_document(self, document_id: str) -> Optional[CaseDocument]:
        return self.documents.get(document_id)

    def update_document_report(
        self,
        document_id: str,
        report: Dict[str, Any],
        edits: List[Dict[str, Any]],
    ) -> CaseDocument:
        with self.lock:
            document = self.documents[document_id]
            document.report = copy.deepcopy(report)
            document.edits.extend(copy.deepcopy(edits))
            document.updated_at = utcnow()
            self.add_ui_event("analysis_edited", document_id=document_id)
            return document

    def add_generated_document(
        self,
        template_name: str,
        file_path: str,
        download_url: str,
        values: Dict[str, str],
        *,
        generation_id: Optional[str] = None,
        document_id: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        metadata = {
            "id": document_id or new_id("gen_doc_"),
            "generation_id": generation_id,
            "template_name": template_name,
            "filename": file_path.replace("\\", "/").rsplit("/", 1)[-1],
            "file_path": file_path,
            "download_url": download_url,
            "values": copy.deepcopy(values),
            "created_at": created_at or utcnow(),
        }
        with self.lock:
            self.generated_documents.append(metadata)
            self.touch()
        return metadata

    def find_generated_document(self, filename: str) -> Optional[Dict[str, Any]]:
        for item in self.generated_documents:
            if item.get("filename") == filename and item.get("download_url"):
                return item
        return None

    def get_active_generation(self) -> Optional[Dict[str, Any]]:
        if not self.active_generation_id:
            return None
        return self.generations.get(self.active_generation_id)

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            active = self.get_active_generation()
            return {
                "case_id": self.session_id,
                "title": self.title,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "events": copy.deepcopy(self.ui_events),
                "documents": [doc.public() for doc in self.documents.values()],
                "generation": copy.deepcopy(active) if active else None,
                "generations": copy.deepcopy(list(self.generations.values())),
                "generated_documents": copy.deepcopy(self.generated_documents),
                "message_count": len(self.history),
                "storage": "in-memory",
            }


class SessionManager:
    def __init__(self) -> None:
        self._sessions: "OrderedDict[str, CaseSession]" = OrderedDict()
        self._lock = threading.RLock()

    def create_session(self, title: Optional[str] = None) -> CaseSession:
        session = CaseSession(session_id=new_id("case_"), title=title or "New case")
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str, create: bool = True) -> Optional[CaseSession]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None and create:
                session = CaseSession(session_id=session_id or new_id("case_"))
                self._sessions[session.session_id] = session
            return session

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "case_id": session.session_id,
                    "title": session.title,
                    "updated_at": session.updated_at,
                    "documents": len(session.documents),
                }
                for session in self._sessions.values()
            ]


session_manager = SessionManager()
