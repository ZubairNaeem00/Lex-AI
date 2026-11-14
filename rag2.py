import os
import re
from typing import Any

from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

load_dotenv()

# ============================================================
# 1. CONFIGURATION
# ============================================================

CASES_INDEX_PATH = "faiss_index_cases"
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

TOP_K = 6
MAX_CHARS_PER_CHUNK = 6000
MAX_HISTORY_TURNS = 6


# ============================================================
# 2. INITIALIZE EMBEDDINGS, VECTOR STORE & LLM
# ============================================================

if not os.getenv("GROQ_API_KEY"):
    raise ValueError("GROQ_API_KEY is missing. Add it to your .env file.")

print("Loading embedding model...")
embeddings = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL,
    model_kwargs={"device": "cuda"},
    encode_kwargs={"normalize_embeddings": True, "batch_size": 16},
)

print("Loading FAISS index...")
cases_db = FAISS.load_local(
    CASES_INDEX_PATH,
    embeddings,
    allow_dangerous_deserialization=True,
)
print(f"FAISS index loaded ({cases_db.index.ntotal:,} vectors).")

llm = ChatGroq(
    model=GROQ_MODEL,
    temperature=0,
)


# ============================================================
# 3. AGENT TOOLS (GREETING FUNCTION)
# ============================================================

@tool
def greet(query: str = "") -> str:
    """
    Call this function whenever the user greets, says hello, hi, hey,
    or asks the agent to greet or say hello.
    Prints 'hello world' 10 times.
    """
    for _ in range(10):
        print("hello world")
    return "Tool 'greet' executed: Printed 'hello world' 10 times."


agent_tools = [greet]
tools_by_name = {"greet": greet}

try:
    llm_with_tools = llm.bind_tools(agent_tools)
except Exception:
    llm_with_tools = llm


# ============================================================
# 4. SESSION MEMORY
# ============================================================

sessions: dict[str, dict[str, Any]] = {}


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "history": [],
            "document_context": "",
        }
    return sessions[session_id]


def clear_session(session_id: str) -> None:
    sessions.pop(session_id, None)


# ============================================================
# 5. DOCUMENT FORMATTING & DEDUPLICATION
# ============================================================

def get_source_label(doc, index: int) -> str:
    meta = doc.metadata or {}
    case_name = (
        meta.get("case_name")
        or meta.get("title")
        or meta.get("act_name")
        or meta.get("source")
        or "Unknown"
    )
    citation = meta.get("citation", "")
    court = meta.get("court", "")
    date = meta.get("decision_date") or meta.get("date") or ""
    section = meta.get("section_number") or meta.get("section", "")
    page = meta.get("page_number") or meta.get("page", "")

    parts = [f"SOURCE-{index}: {case_name}"]
    if citation:
        parts.append(f"Citation: {citation}")
    if court:
        parts.append(f"Court: {court}")
    if date:
        parts.append(f"Date: {date}")
    if section:
        parts.append(f"Section {section}")
    if page:
        parts.append(f"Page {page}")
    return " | ".join(parts)


def format_documents(documents) -> str:
    if not documents:
        return "No relevant documents were retrieved."
    formatted = []
    for i, doc in enumerate(documents, start=1):
        label = get_source_label(doc, i)
        content = (doc.page_content or "").strip()[:MAX_CHARS_PER_CHUNK]
        formatted.append(f"[{label}]\nContent:\n{content}")
    return "\n\n".join(formatted)


def unique_documents(documents):
    seen = set()
    unique = []
    for doc in documents:
        key = (doc.page_content or "", str(doc.metadata or {}))
        if key not in seen:
            seen.add(key)
            unique.append(doc)
    return unique


# ============================================================
# 6. RETRIEVAL & QUERY RESOLUTION
# ============================================================

def resolve_question(question: str, history: list, document_context: str) -> str:
    if not history and not document_context.strip():
        return question

    history_text = ""
    for message in history[-MAX_HISTORY_TURNS * 2:]:
        role = "User" if isinstance(message, HumanMessage) else "Assistant"
        history_text += f"{role}: {message.content}\n"

    prompt = f"""Rewrite the latest user question as a standalone query for retrieving relevant legal case law, statutes, and judgments.
Use earlier conversation and document context only to resolve references.
Return only the rewritten search query.

DOCUMENT CONTEXT:
{document_context[:5000] or "No document context available."}

RECENT CONVERSATION:
{history_text or "No earlier conversation."}

LATEST QUESTION:
{question}
"""
    response = llm.invoke(prompt)
    rewritten = str(response.content).strip()
    return rewritten or question


def retrieve_documents(query: str, top_k: int = TOP_K):
    docs_with_scores = cases_db.similarity_search_with_score(query, k=top_k)
    docs = [doc for doc, score in docs_with_scores]
    scores = [score for doc, score in docs_with_scores]
    return unique_documents(docs), scores


# ============================================================
# 7. LEGAL REASONING
# ============================================================

SYSTEM_PROMPT = """You are a legal information assistant specializing in Pakistani law.
You help users understand legal documents, laws, procedures, and relevant judicial decisions.
You are an assistant, not a substitute for a qualified Pakistani lawyer.

STRICT RULES:
- Never invent section numbers, case names, citations, or legal rules.
- Cite retrieved sources using [SOURCE-1], [SOURCE-2] exactly as provided.
- Apply the retrieved law to the known case facts explicitly.
"""


def generate_legal_answer(question: str, document_context: str, retrieved_context: str, history: list) -> str:
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    messages.extend(history[-MAX_HISTORY_TURNS * 2:])
    user_prompt = f"""LATEST USER QUESTION:
{question}

RETRIEVED LEGAL SOURCES:
{retrieved_context}
"""
    messages.append(HumanMessage(content=user_prompt))
    response = llm.invoke(messages)
    return str(response.content).strip()


# ============================================================
# 8. MAIN AGENT FUNCTION
# ============================================================

def is_greeting(text: str) -> bool:
    patterns = [
        r"\b(hello|hi|hey|heyy|heya)\b",
        r"\b(greet|greetings|say hello|say hi|say hey)\b",
        r"\b(good morning|good afternoon|good evening)\b",
        r"\b(salam|assalam|aoa)\b",
    ]
    return any(re.search(pat, text.lower()) for pat in patterns)


def ask_legal_agent(question: str, session_id: str = "default") -> dict:
    if not question or not question.strip():
        return {"answer": "Please enter a question.", "search_query": "", "sources": [], "scores": [], "tool_called": None}

    session = get_session(session_id)
    history = session["history"]
    document_context = session["document_context"]

    tool_called = None
    is_greet_query = is_greeting(question)

    # Trigger greeting tool if user greets or asks to greet
    if is_greet_query:
        tool_called = "greet"
        greet.invoke({})  # Prints 'hello world' 10 times from within the function

    # Check if this is purely a greeting
    clean_q = re.sub(r"[^\w\s]", "", question.lower()).strip()
    legal_keywords = ["law", "section", "bail", "case", "court", "fir", "theft", "murder", "punishment", "ppc", "crpc"]
    has_legal_content = any(k in clean_q for k in legal_keywords)

    if is_greet_query and not has_legal_content:
        answer = "Hello! I am your Pakistani Legal Assistant. What legal question or case can I assist you with today?"
        history.extend([HumanMessage(content=question), AIMessage(content=answer)])
        session["history"] = history[-MAX_HISTORY_TURNS * 2:]
        return {"answer": answer, "search_query": "", "sources": [], "scores": [], "tool_called": tool_called}

    search_query = resolve_question(question, history, document_context)
    docs, scores = retrieve_documents(search_query, top_k=TOP_K)
    retrieved_context = format_documents(docs)
    answer = generate_legal_answer(question, document_context, retrieved_context, history)

    history.extend([HumanMessage(content=question), AIMessage(content=answer)])
    session["history"] = history[-MAX_HISTORY_TURNS * 2:]

    return {
        "answer": answer,
        "search_query": search_query,
        "sources": [get_source_label(doc, i) for i, doc in enumerate(docs, 1)],
        "scores": [round(float(s), 4) for s in scores[:len(docs)]],
        "tool_called": tool_called,
    }


if __name__ == "__main__":
    print("Testing Greeting Tool:")
    res = ask_legal_agent("Hello! Can you greet me?")
    print("Agent reply:", res["answer"])

