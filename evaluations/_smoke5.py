import os, re, sys, time, threading, json
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
for n in ("NO_PROXY", "no_proxy"):
    v = os.getenv(n)
    if v and "[" in v:
        os.environ[n] = re.sub(r"\[([^\[\]]+)\]", r"\1", v)
os.environ["LEGAL_LLM_PROVIDER"] = "groq"
os.environ["WEB_FALLBACK_ENABLED"] = "0"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
sys.path.insert(0, str(REPO))
t = time.time()
import faiss
faiss.omp_set_num_threads(1)
import groq_utils
import legal_agent as la
for th in threading.enumerate():
    if th.name == "legal-prewarm":
        th.join()
print("prewarm done", round(time.time() - t, 1), "s; law", la.retrieval_status()["law"]["state"], "cases", la.retrieval_status()["cases"]["state"], flush=True)

captured = {}
_orig = la.format_evidence
def spy(evidence):
    ctx = _orig(evidence)
    captured["context"] = ctx
    captured["n"] = len(evidence)
    return ctx
la.format_evidence = spy

q = "what is the ruling on bail in non-bailable offences"
r = la.ask_legal_agent(q, session_id="smoke5b", provider="groq")
ans = r.get("answer") or ""
print("ANSWER:", ans[:800], flush=True)
print("SOURCES:", (r.get("sources") or [])[:6], flush=True)
print("CTX chars:", len(captured.get("context", "")), "evidence n:", captured.get("n"), flush=True)

ctx = captured.get("context", "")[:6000]
prompt = (
    "You are a strict RAG faithfulness judge. Given CONTEXT (retrieved legal passages) and ANSWER, "
    "judge whether every factual/legal claim in ANSWER is supported by CONTEXT. Ignore style. "
    'Return ONLY JSON: {"score": <0..1 fraction of claims supported>, "unsupported": ["short claim"], "reason": "<one sentence>"}. '
    "If ANSWER refuses or says it cannot find authority, score=1.0 and unsupported=[].\n\n"
    f"CONTEXT:\n{ctx}\n\nANSWER:\n{ans[:2500]}\n"
)
llm = groq_utils.get_groq_llm(temperature=0.0, max_tokens=400)
resp = groq_utils.invoke_llm(llm, prompt, label="faithfulness judge")
txt = resp.content if hasattr(resp, "content") else str(resp)
m = re.search(r"\{.*\}", txt, re.S)
print("JUDGE RAW:", txt[:400], flush=True)
print("JUDGE PARSED:", json.loads(m.group(0)) if m else "NO JSON", flush=True)
print("SMOKE DONE", round(time.time() - t, 1), "s", flush=True)