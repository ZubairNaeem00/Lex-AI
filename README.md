# LegalLens — Pakistani Legal AI Assistant

A local FastAPI + vanilla JavaScript demo that combines:

- source-grounded legal RAG over two local FAISS indexes (Pakistani statutes and
  court judgments) queried together for every legal question,
- LlamaParse document extraction with dynamic Groq analysis reports,
- editable analysis reports tied to a shared case session,
- a dedicated multi-turn document-generation workflow with DOCX download.

The chat UI runs in `frontend/` (Create React App, `npm start` on port 3000, proxied to
this backend on port 8000).

## Quick start (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in this folder (see `.env.example`):

```env
GROQ_API_KEY=your_groq_key
LLAMA_CLOUD_API_KEY=your_llamacloud_key
GROQ_MODEL=openai/gpt-oss-120b
```

Start the server:

```bat
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>.

The process needs roughly 20–45 seconds before `/api/health` is ready because the
embedding model and FAISS index are loaded lazily. The **first** legal question also
pays the one-time cost of loading `BAAI/bge-base-en-v1.5`; in local testing this took
up to about two minutes. Later questions are normally a few seconds. Two indexes are
read, never rebuilt, and both are searched for every legal question:
`faiss_index_law/` (51,475 vectors of Acts/PPC/CrPC text) and `faiss_index_cases/`
(209,168 vectors of judgments). They share one 768-dim embedding model, so passages
stay comparable; the statute and judgment passages are presented to the model as two
separate groups and labeled `SOURCE-n [STATUTE]` / `SOURCE-n [CASE LAW]`. If one index
is missing or a search fails, the other still answers and the model is told which
retriever was unavailable (see `/api/health` → `retrievers`).

A question that contains several parts ("what is X, its conditions, and the steps?") is
split into up to `MAX_FACETS` focused sub-queries (by Groq, with a comma/conjunction
fallback). Every sub-query and the whole question are searched against **both** indexes;
hits are de-duplicated, ordered so one part cannot crowd the others out, and filtered so
a passage must either name the topic or stay close to the best hit of its own query.
Coverage is then checked per part, and a part left without support gets a second,
differently-worded retrieval attempt (including one that names an Act already confirmed
to discuss the topic) before the model is asked to answer. The model receives a
PARTS REQUESTED list stating which sources support which part, so a gap in one part
never stops the other parts from being answered.

Do not use `--reload` for a demo: every reload restarts the in-memory store.

## Architecture

| File | Responsibility |
| --- | --- |
| `main.py` | FastAPI routes, upload limits, case/document/generation/download endpoints |
| `session_manager.py` | In-memory `CaseSession` + `SessionManager`, locks, messages, UI events |
| `document_analysis.py` | LlamaParse extraction (Urdu/English OCR) and structured Groq analysis |
| `case_context.py` | Compact case context, canonical facts, correction propagation, report edits |
| `legal_agent.py` | Query rewrite, multi-part question split, bounded dual-index FAISS retrieval (statutes + judgments), grounded prompt, Groq retries |
| `generation_workflow.py` | Drafting state machine: answer normalization, review, field editing, DOCX generation |
| `doc_generation.py` | Template schema, field extraction, DOCX rendering |
| `context_budget.py` | Token counting, truncation, history/context/retrieval budgets |
| `groq_utils.py` | Shared Groq client, usage logs, rate/token-limit classification |
| `static/` | Single-page chat UI, analysis cards, editable fields, generation cards |

One case ID (`case_...`) owns:

- chat messages and compacted history,
- uploaded documents, original extracted text, original analysis, and edits,
- corrected canonical facts,
- generation answers and generated-document metadata,
- the append-only UI event stream used to restore the conversation after reload.

Uploading before the first chat creates/uses the same case. A new case starts with no
documents, messages, or generation state.

### Correction precedence

The original extracted text and original report are preserved. Edits update the
authoritative report and are recorded with old/new values. Compact model context adds
an `USER-CORRECTED VALUES (AUTHORITATIVE)` block, replaces corrected values in summaries
and excerpts sent to the model, and labels them `[user-corrected]`; the UI keeps showing
both current and original values. RAG answers and generated DOCX files use the corrected
values.

## Token-budget strategy

Defaults are deliberately below Groq's 8,000 TPM limit for `openai/gpt-oss-120b`:

| Budget | Default |
| --- | --- |
| Legal-chat input | 3,600 tokens |
| Legal-chat output | 1,200 tokens |
| Recent history | 650 tokens, 3 turns, 600 chars/message |
| Case context | 900 tokens |
| Retrieved context | 1,000 tokens, 4 passages, 1,200 chars/passage |
| Follow-up rewrite | 1,100 input / 100 output |
| Analysis | one structured call on the full extracted text |
| Generation context / known facts | 500 / 450 tokens |

Every chat and generation value can be overridden in `.env`; see the variable names in
`context_budget.py`. Full documents, reports, and history stay in the session. Only
recent turns, selected excerpts, and capped retrieval passages are sent to Groq. On a
token/rate error the legal answer is retried with 60% and then 40% of the context. If
all retries fail, the user gets a recoverable error message; case data is not deleted.

## Document generation workflow

A drafting request creates a generation attached to the case. The workflow asks for
missing required fields one at a time, then stops at a **review** stage; it never
renders a DOCX until the user explicitly clicks **Save & generate**. Draft cards show
status, progress, and the next question, but never the collected field values.

- **Conversational answers are normalized.** A reply such as “my name is Zubar” is
  sent through a bounded LLM normalization call that returns only the field value
  (`Zubar`) plus any other explicitly supplied fields. Deterministic cleanup handles
  CNIC/FIR formats and lead-in phrases if the model is unavailable. The raw reply is
  recorded in the generation’s `answers` and case details for context, but its chat
  event is marked hidden and never rendered as a chat bubble.
- **Values are stored, not displayed.** Field values live in the generation record,
  `extra_case_details`, and the review form. They are not included in the session
  snapshot or on the draft card. The review modal is the only place the UI shows them.
- **Review and edit.** **Edit details** / **Edit & regenerate** opens a form with every
  template field, its source (`case documents`, `request`, or `you`), and any default.
  **Save details** stores edits without rendering; **Save & generate** renders a new
  DOCX. Edited fields are locked so later automatic fact refreshes cannot overwrite
  them, and each change is recorded with old/new values.
- **Fresh drafts are isolated.** Saying “draft a new bail application for a different
  person” cancels the active draft and starts a new one. New drafts seed only from
  corrected case documents and the request text; answers given for a previous person
  are deliberately excluded. Old drafts keep their own values and downloads.
- **Clear all** blanks the review form so a different person's details can be entered
  from scratch before saving.

## Supported documents

Only `Templates/Bail Application.docx` is fully parameterized (10 fields). The analysis
and chat work for any uploaded legal document. The other DOCX files are present but do
not have a schema, so the app refuses to invent their contents and tells the user which
template is supported.

Document text extraction uses **LlamaParse only**, with Urdu/English OCR and automatic
translation of extracted Urdu text to English. No local OCR fallback is used.

## API summary

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | UI |
| GET | `/api/health` | Config/template/index status |
| POST | `/api/sessions` | New case |
| GET | `/api/sessions/{case_id}` | Snapshot (messages, docs, edits, generations) |
| DELETE | `/api/sessions/{case_id}` | Delete case |
| POST | `/api/analyze` | Multipart upload + optional `case_id` |
| PUT | `/api/sessions/{case_id}/documents/{document_id}/report` | Apply report edits |
| GET | `/api/sessions/{case_id}/documents/{document_id}/text` | Original extracted text |
| POST | `/api/chat` | RAG answer or generation-workflow step |
| GET | `/api/sessions/{case_id}/generation` | Active generation state |
| GET | `/api/sessions/{case_id}/generation/{generation_id}/fields` | Review-form fields and current values |
| PUT | `/api/sessions/{case_id}/generation/{generation_id}/fields` | Save edited values, optionally regenerate |
| POST | `/api/sessions/{case_id}/generation/cancel` | Cancel draft |
| POST | `/api/sessions/{case_id}/generation/retry` | Retry failed draft |
| GET | `/sessions/{case_id}/download/{filename}` | Download generated DOCX |

Uploads: PDF, PNG, JPG, JPEG, WEBP, TIFF; maximum 25 MB by default (`MAX_UPLOAD_MB`).

## Testing performed (2026-10-24)

The following were actually run locally with the browser and/or HTTP API:

- upload → LlamaParse → structured analysis card → edit accused/party name;
- RAG answer on the corrected case used the corrected name and marked it
  `(user-corrected)`, not the original extraction;
- complainant address/CNIC were not offered as applicant values; the generation
  workflow asked only for the applicant's own address and CNIC (6/8 → 8/8 required
  fields);
- bail generation completed on the final build with a downloadable DOCX (HTTP 200,
  correct MIME type). DOCX inspection confirmed: corrected name, applicant address
  and CNIC, complainant address/CNIC absent, s.497 heading, sections `379, 411 PPC`
  without the alleged-offence description, FIR 245/2026, IO, and Sessions Court;
- a legal question asked after generation returned to the RAG path and answered with
  the corrected name and sections;
- two uploaded documents and two consecutive legal questions stayed under the 8,000
  TPM budget (observed request totals roughly 2.1k–3.4k tokens);
- unsupported “legal notice” and “divorce application” requests returned a clear
  refusal instead of an invented document;
- cancel and retry were exercised (including a temporary missing-template failure,
  followed by a successful retry);
- new-case isolation: a fresh case had zero messages/documents/events while the old
  case retained its messages;
- invalid `.txt` and empty `.pdf` uploads returned 400 without crashing the server;
- browser reload restored chat messages, analysis cards/edits, and generation cards;
- the restored original analysis flow was tested with `FIR-41_2022.pdf`: LlamaParse
  returned 6,124 characters, the HTTP API returned a complete report (HTTP 200), and the
  browser rendered a 7-section analysis card; canonical facts resolved the accused
  (Qasir Iqbal), CNIC, address, FIR number, police station, IO, and cited PECA/PPC
  provisions for bail generation.

The final legal prompt is deliberately conservative: if retrieved authorities do not
establish a requested rule, the assistant restricts itself to a source-limitation
statement instead of supplying general-law procedure. Retrieval quality depends on the
existing judgment index and can return marginal authorities; answers should be verified.

## Testing performed (2026-10-26)

The generation review workflow was exercised through the browser and HTTP API:

- conversational replies (“my name is Zubar”, “my father’s name is …”, “our address
  is …”, CNIC, FIR, police station, IO, sections) were normalized to bare values in the
  generation record; the DOCX contained `Zubar Khan`, the father’s name, address, CNIC
  and FIR, with no “my name is” / “our address is” phrases;
- field answers sent through the chat composer were marked hidden: the transcript kept
  only the original drafting request, no answer bubble appeared during or after the
  request (the composer showed “Saving the detail…”), and a page reload rendered the
  same hidden state while the normalized values remained available in the generation
  record and review fields;
- a completed draft card contained no applicant name, address, or CNIC; those strings
  appeared only in the user’s normal chat bubbles and in the deliberate review modal;
- the workflow stopped at **review** after all required fields were collected and did
  not auto-render; **Save & generate** then produced a downloadable DOCX;
- the review modal displayed all 10 template fields with clean values and source chips;
  **Save details** persisted an edited law-firm address without changing the existing
  download, and a subsequent **Save & generate** produced a new DOCX containing it;
- a “new bail application for a different person” request started from 0/8 required
  details with no applicant values seeded from the previous draft;
- canceling the active draft updated its card to **Cancelled** without affecting the
  completed draft or its download;
- no browser console errors were reported during the sequence.

## Testing performed (2026-10-27)

The React frontend in `frontend/` (the app's own multi-page UI) was wired to this
backend and the full workflow was exercised in a browser against
`http://localhost:3000/chat` (CRA dev server proxying `/api` and `/sessions` to the
FastAPI backend on `127.0.0.1:8000`):

- a new case was created automatically and restored from `localStorage` on reload;
- FIR-41_2022.pdf was uploaded through the chat Document Analysis modal; the
  structured report rendered as an editable card and the case title updated;
- a field correction ("FIR No. 41/2022 (verified)") saved through **Correct a value**,
  showed the CORRECTED badge with "corrected · was:" note, and the confirmation
  "1 correction saved — later answers and drafts will use it.";
- "Which PPC sections apply?" returned a sourced answer with a "Retrieved sources (4)"
  disclosure; timestamps rendered correctly;
- "Generate a bail application" started the draft workflow: the card asked for the
  applicant's CNIC with a 6/8 progress counter and an "Answering: Applicants Cnic No"
  header chip;
- **Edit details** opened the review modal with 8 fields pre-filled from the corrected
  case context; filling CNIC + sections and clicking **Save & generate** produced a
  "READY TO DOWNLOAD" card, and the typed answers never appeared as chat bubbles;
- the Download DOCX link (proxied `/sessions/{id}/download/{filename}`) returned a
  valid Microsoft Word 2007+ file (13,739 bytes);
- "Summarize this case" after generation returned a structured case summary from the
  case context, confirming normal RAG chat continues after drafting;
- the session sidebar listed both real cases with live document counts.

Fixes made during integration: ChatPage read `timestamp`/`text`/`ai` while the API
emits `ts`/`content`/`assistant`; `analyzeDocument` was called with swapped arguments;
GenerationCard's `onEdit` passes an id string, not an object; the analyze-modal file
input was `display:none`, which also blocked screen readers; CORS middleware was added
for direct `:3000` ↔ `:8000` calls (the CRA proxy covers same-origin use).

## Known limitations

- Sessions are in memory. Restarting the server deletes all cases, documents, edits,
  and generated-document records. That is intentional for this local demo.
- Only the bail application is fillable. Other DOCX files need schemas/placeholders.
- The first embedding load is slow on CPU and needs internet access for the model
  download the first time.
- LlamaParse and Groq require internet access and API keys; provider retention policies
  apply. Use anonymized test documents.
- Document analysis sends the full extracted text in one structured Groq call. Very long
  documents can exceed the model's context or token-per-minute limit; split or shorten
  such documents before analysis.
- Generated files are stored under `Generated/`; the demo has no authentication or
  multi-user isolation. Do not expose it as a public service without adding auth,
  persistent storage, and per-user file controls.
- `speech.py`, `rag2.py`, and `templateselector.ipynb` are legacy experiments and are
  not wired into the running app. `requirements.txt` lists only the app's runtime
  dependencies.
- This is an educational tool, not legal advice. Always verify statutes, citations, and
  draft documents with an enrolled Pakistani advocate.
