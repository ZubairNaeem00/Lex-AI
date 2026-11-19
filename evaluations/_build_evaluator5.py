"""Scratch builder for evaluator5.ipynb (write-first, then embed real outputs)."""
import io, json, contextlib, uuid, traceback
from pathlib import Path

MD = r'''# evaluator5 - End-to-end RAG answer quality (Groq)

Evaluators 2-4 measured **retrieval only** (Recall/MRR/nDCG/gate). This notebook measures the
**generation half of RAG**: it runs the *real* legal agent (`ask_legal_agent`, `provider=groq`)
on a stratified sample of the grounded case gold and scores the answers.

**Metrics**
- **Faithfulness / groundedness** - one Groq LLM-as-judge call per query, comparing the answer
  against the *exact* retrieved context the model saw (captured non-invasively via a `format_evidence` spy).
- **Refusal accuracy** - the same judge flags whether the reply declines the substance; we compute
  TNR (unanswerable refused) / TPR (answerable answered).
- **Answer relevance** - offline bge cosine(answer, query); no extra API call.
- **Citation correctness** - offline: source citations valid in corpus, dangling `[SOURCE-n]` markers,
  gold case present in retrieved sources (context recall), gold case actually cited in the answer.

**Method / limitations (read before quoting numbers)**
- **Cases channel isolated.** The law statute index does not load in this eval process (RAM is shared
  with the running backend, which already holds both indexes). The gold is case-centric, so this
  evaluates the case-law RAG channel. `law_index` state is printed below.
- Web fallback disabled (`WEB_FALLBACK_ENABLED=0`) to isolate the local pipeline.
- Stratified sample n=75 (20 citation / 20 case_name / 20 issue / 15 unanswerable), SEED=42 - not all 450.
- Faithfulness/refusal use an LLM judge (`openai/gpt-oss-120b`, temp 0) - a scalable proxy, not human gold.
- Fresh session per query (no history) so the agent skips query-rewrite; ~1 generation + 1 judge call each.
'''

CELL_A = r'''import os, re, sys, time, json, threading, random
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
HERE = Path.cwd()
if not (HERE / "golden_queries_bge.jsonl").exists() and (HERE / "evaluations" / "golden_queries_bge.jsonl").exists():
    HERE = HERE / "evaluations"
REPO = HERE.parent
for _n in ("NO_PROXY", "no_proxy"):
    _v = os.getenv(_n)
    if _v and "[" in _v:
        os.environ[_n] = re.sub(r"\[([^\[\]]+)\]", r"\1", _v)
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
import faiss
faiss.omp_set_num_threads(1)
import numpy as np
import groq_utils
import legal_agent as la
for _th in threading.enumerate():
    if _th.name == "legal-prewarm":
        _th.join()
STATUS = la.retrieval_status()
print("law:", STATUS["law"]["state"], " cases:", STATUS["cases"]["state"], flush=True)

CAP = {}
_ORIG_FE = la.format_evidence
def _spy(evidence):
    ctx = _ORIG_FE(evidence)
    CAP["context"] = ctx
    CAP["n"] = len(evidence)
    return ctx
la.format_evidence = _spy

def canon(s):
    s = (s or "").split("Bookmark")[0].replace("Citation Name:", "")
    return re.sub(r"[^a-z0-9]", "", s.lower())

_store = la.get_store(la.KIND_CASES)
CIT_KEYS = set()
for _d in _store.docstore._dict.values():
    c = (_d.metadata or {}).get("citation")
    if c:
        CIT_KEYS.add(canon(c))
print("corpus citation keys:", len(CIT_KEYS), flush=True)
EMBED = la.get_embeddings()
JUDGE = groq_utils.get_groq_llm(temperature=0.0, max_tokens=400)
GOLD = HERE / "golden_queries_bge.jsonl"
SEED = 42; PER_TYPE = 20; N_UNANS = 15; PACE = 1.0; PROVIDER = "groq"
print("judge model:", groq_utils.GROQ_MODEL, " target sample:", PER_TYPE * 3 + N_UNANS, flush=True)
'''

CELL_B = r'''SRC_CIT_RE = re.compile(r"Citation Name:(.*?)Bookmark", re.S)
MARK_RE = re.compile(r"\[SOURCE-(\d+)\]")
ERROR_MARKERS = ("temporarily rate-limited", "rejected the request as too large",
                 "language model request failed", "could not process the request size",
                 "local ollama request failed")

def is_error(ans):
    a = (ans or "").lower()
    return any(m in a for m in ERROR_MARKERS)

def source_citations(sources):
    out = []
    for lab in sources or []:
        m = SRC_CIT_RE.search(lab or "")
        out.append(canon(m.group(1)) if m else "")
    return out

def judge_answer(ctx, ans):
    prompt = ('You are a strict evaluator of a Pakistani legal RAG system. You are given CONTEXT '
              '(retrieved court-judgment passages) and ANSWER (the system reply). Judge two things:\n'
              '1. faithfulness: the fraction of factual/legal claims in ANSWER supported by CONTEXT (0..1). '
              'A reply that correctly declines because the authority is absent is faithful (1.0). Do NOT '
              'penalize an answer for noting that statutory texts are unavailable while it still answers '
              'from the judgments.\n'
              '2. refused: true if ANSWER declines the substance of the question (cannot find relevant '
              'authority / cannot answer / the authorities do not address it); false if it gives a '
              'substantive answer, even with caveats.\n'
              'Return ONLY JSON: {"faithfulness": <0..1>, "refused": <true|false>, '
              '"unsupported": ["short claim"], "reason": "<one sentence>"}\n\n'
              'CONTEXT:\n' + (ctx or "")[:6000] + '\n\nANSWER:\n' + (ans or "")[:2500])
    try:
        resp = groq_utils.invoke_llm(JUDGE, prompt, label="judge")
        txt = resp.content if hasattr(resp, "content") else str(resp)
        m = re.search(r"\{.*\}", txt, re.S)
        d = json.loads(m.group(0)) if m else {}
        return {"faithfulness": float(d.get("faithfulness", 0.0)),
                "refused": bool(d.get("refused", False)),
                "unsupported": d.get("unsupported", []) or [],
                "reason": d.get("reason", "")}
    except Exception as e:
        return {"faithfulness": None, "refused": None, "unsupported": [],
                "reason": f"judge error: {type(e).__name__}"}

def relevance(query, ans):
    try:
        qv = np.asarray(EMBED.embed_query(query), dtype=np.float32)
        av = np.asarray(EMBED.embed_query((ans or "")[:1200]), dtype=np.float32)
        return float(np.dot(qv, av) / (np.linalg.norm(qv) * np.linalg.norm(av) + 1e-9))
    except Exception:
        return None

def boot_ci(vals, n=1000, seed=42):
    vals = [v for v in vals if v is not None]
    if not vals:
        return (float("nan"), float("nan"), float("nan"))
    rng = random.Random(seed)
    arr = np.array(vals, dtype=float)
    means = np.array([np.mean(rng.choices(arr.tolist(), k=len(arr))) for _ in range(n)])
    return (float(arr.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))
'''

CELL_C = r'''rows = [json.loads(l) for l in open(GOLD, encoding="utf-8")]
rng = random.Random(SEED)
sample = []
for qt in ("citation", "case_name", "issue"):
    pool = [r for r in rows if r.get("query_type") == qt and r.get("answerable")]
    sample += rng.sample(pool, min(PER_TYPE, len(pool)))
unans = [r for r in rows if not r.get("answerable")]
sample += rng.sample(unans, min(N_UNANS, len(unans)))
print("sample n =", len(sample), flush=True)

records = []; t0 = time.time()
for i, r in enumerate(sample, 1):
    q = r["query"]; qt = r.get("query_type"); ansable = bool(r.get("answerable"))
    gold = [canon(c) for c in (r.get("relevant_citations") or [])]
    CAP.clear()
    sid = f"eval5-{r.get('id', i)}"
    rec = {"id": r.get("id"), "query": q, "query_type": qt, "answerable": ansable, "gold": gold}
    try:
        st = time.time()
        res = la.ask_legal_agent(q, session_id=sid, provider=PROVIDER)
        rec["gen_s"] = round(time.time() - st, 2)
        ans = res.get("answer") or ""
        rec["answer"] = ans; rec["sources"] = res.get("sources") or []; rec["scores"] = res.get("scores") or []
        rec["search_query"] = res.get("search_query"); rec["context_chars"] = len(CAP.get("context", ""))
        if is_error(ans):
            time.sleep(10)
            CAP.clear()
            res = la.ask_legal_agent(q, session_id=sid + "-r", provider=PROVIDER)
            ans = res.get("answer") or ""
            rec["answer"] = ans; rec["sources"] = res.get("sources") or []; rec["scores"] = res.get("scores") or []
            rec["context_chars"] = len(CAP.get("context", ""))
        if is_error(ans):
            rec["status"] = "error"
        else:
            sc = source_citations(rec["sources"])
            rec["source_citations"] = sc
            rec["valid_source_rate"] = (sum(1 for c in sc if c in CIT_KEYS) / len(sc)) if sc else None
            markers = [int(x) for x in MARK_RE.findall(ans)]
            rec["n_markers"] = len(markers)
            rec["dangling_markers"] = sum(1 for m in markers if m < 1 or m > len(rec["sources"]))
            rec["gold_in_sources"] = (any(g in sc for g in gold) if gold else None)
            gidx = [j + 1 for j, c in enumerate(sc) if c in gold] if gold else []
            rec["gold_cited"] = (any(m in gidx for m in markers) if gold else None)
            j = judge_answer(CAP.get("context", ""), ans)
            rec["faithfulness"] = j["faithfulness"]; rec["refused"] = j["refused"]
            rec["unsupported"] = j["unsupported"]; rec["judge_reason"] = j["reason"]
            rec["status"] = "refused" if j["refused"] else "answered"
            rec["relevance"] = relevance(q, ans) if rec["status"] == "answered" else None
    except Exception as e:
        rec["status"] = "error"; rec["error"] = f"{type(e).__name__}: {e}"
    records.append(rec)
    if i % 10 == 0 or i == len(sample):
        na = sum(1 for x in records if x.get("status") == "answered")
        nr = sum(1 for x in records if x.get("status") == "refused")
        ne = sum(1 for x in records if x.get("status") == "error")
        print(f"  {i}/{len(sample)} ({round(time.time()-t0)}s) answered={na} refused={nr} error={ne}", flush=True)
    if i % 25 == 0:
        json.dump(records, open(HERE / "eval_results_answer.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    time.sleep(PACE)
json.dump(records, open(HERE / "eval_results_answer.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved eval_results_answer.json  total", round(time.time() - t0), "s", flush=True)
'''

CELL_D = r'''L = []
def say(s=""):
    print(s, flush=True); L.append(s)
recs = records
err = [r for r in recs if r.get("status") == "error"]
ansd = [r for r in recs if r.get("status") == "answered"]
ref = [r for r in recs if r.get("status") == "refused"]
say("########## END-TO-END RAG ANSWER QUALITY (Groq, cases channel) ##########")
say(f"sample n={len(recs)}  answered={len(ansd)}  refused={len(ref)}  errors={len(err)}")
say(f"judge={groq_utils.GROQ_MODEL}  provider=groq  web_fallback=off  law_index={STATUS['law']['state']}")
say("")
say("=== Faithfulness / groundedness (LLM judge vs exact retrieved context) ===")
faith = [r["faithfulness"] for r in recs if r.get("faithfulness") is not None]
m, lo, hi = boot_ci(faith)
say(f"  mean {m:.3f}  95% CI [{lo:.3f}, {hi:.3f}]  (n={len(faith)})")
say(f"  fully grounded (==1.0): {sum(1 for v in faith if v >= 0.999)}/{len(faith)}")
uns = [len(r.get("unsupported") or []) for r in recs if r.get("faithfulness") is not None]
if uns:
    say(f"  mean unsupported claims per answer: {np.mean(uns):.2f}")
for qt in ("citation", "case_name", "issue", "unanswerable"):
    f = [r["faithfulness"] for r in recs if r.get("query_type") == qt and r.get("faithfulness") is not None]
    if f:
        say(f"  {qt:12s} mean {np.mean(f):.3f} (n={len(f)})")
say("")
say("=== Answer relevance (offline bge cosine answer vs query) ===")
for qt in ("citation", "case_name", "issue"):
    v = [r["relevance"] for r in recs if r.get("query_type") == qt and r.get("relevance") is not None]
    if v:
        say(f"  {qt:12s} mean {np.mean(v):.3f} (n={len(v)})")
allrel = [r["relevance"] for r in recs if r.get("relevance") is not None]
if allrel:
    say(f"  overall      mean {np.mean(allrel):.3f} (n={len(allrel)})")
say("")
say("=== Citation correctness ===")
vsr = [r["valid_source_rate"] for r in recs if r.get("valid_source_rate") is not None]
if vsr:
    say(f"  source citations valid in corpus: {np.mean(vsr):.3f} (n={len(vsr)})")
dm = [r["dangling_markers"] for r in recs if r.get("n_markers")]
if dm:
    say(f"  answers with dangling [SOURCE-n] markers: {sum(1 for d in dm if d > 0)}/{len(dm)}")
gis = [bool(r["gold_in_sources"]) for r in recs if r.get("gold_in_sources") is not None]
if gis:
    say(f"  gold case in retrieved sources (context recall): {np.mean(gis):.3f} (n={len(gis)})")
gc = [bool(r["gold_cited"]) for r in recs if r.get("gold_cited") is not None]
if gc:
    say(f"  gold case actually cited in answer: {np.mean(gc):.3f} (n={len(gc)})")
for qt in ("citation", "case_name", "issue"):
    g = [bool(r["gold_in_sources"]) for r in recs if r.get("query_type") == qt and r.get("gold_in_sources") is not None]
    if g:
        say(f"    {qt:12s} gold-in-sources {np.mean(g):.3f} (n={len(g)})")
say("")
say("=== Refusal accuracy (judge-classified) ===")
una = [r for r in recs if not r.get("answerable") and r.get("status") != "error"]
ansable = [r for r in recs if r.get("answerable") and r.get("status") != "error"]
tnr = sum(1 for r in una if r.get("status") == "refused") / len(una) if una else float("nan")
tpr = sum(1 for r in ansable if r.get("status") == "answered") / len(ansable) if ansable else float("nan")
say(f"  unanswerable refused (TNR): {tnr:.3f} (n={len(una)})")
say(f"  answerable answered (TPR):  {tpr:.3f} (n={len(ansable)})")
say(f"  balanced: {(tnr + tpr) / 2:.3f}")
say("")
gs = [r["gen_s"] for r in recs if r.get("gen_s")]
if gs:
    say(f"=== Latency ===  mean generation {np.mean(gs):.2f}s  (n={len(gs)})")
say("")
say("=== Worked examples ===")
def example(qt, pred=None):
    c = [r for r in recs if r.get("query_type") == qt and r.get("status") != "error" and (pred is None or pred(r))]
    return c[0] if c else None
for qt, pred in (("issue", lambda r: (r.get("faithfulness") or 0) >= 0.99), ("citation", None), ("case_name", None), ("unanswerable", None)):
    r = example(qt, pred)
    if not r:
        continue
    say(f"\n[{qt}] {r['query']}")
    say(f"  status={r.get('status')} faithfulness={r.get('faithfulness')} relevance={r.get('relevance')}")
    say(f"  sources: {('; '.join(r.get('sources') or []))[:240]}")
    say(f"  answer: {(r.get('answer') or '')[:420]}")
    say(f"  judge: {r.get('judge_reason')}")
say("")
say("Limitations: cases channel isolated (law statute index not loaded in eval process; RAM shared with")
say("running backend); gold is case-centric; web fallback disabled; stratified sample n=75, not full 450;")
say("faithfulness/refusal via LLM judge (openai/gpt-oss-120b) - a scalable proxy, not human-annotated gold.")
(HERE / "eval_summary_answer.txt").write_text("\n".join(L), encoding="utf-8")
print("wrote eval_summary_answer.txt", flush=True)
'''

cells = [("markdown", MD), ("code", CELL_A), ("code", CELL_B), ("code", CELL_C), ("code", CELL_D)]
nb_cells = []; code_slots = []
for kind, src in cells:
    if kind == "markdown":
        nb_cells.append({"cell_type": "markdown", "id": uuid.uuid4().hex[:8], "metadata": {},
                         "source": src.splitlines(keepends=True)})
    else:
        nb_cells.append({"cell_type": "code", "id": uuid.uuid4().hex[:8], "metadata": {},
                         "execution_count": None, "source": src.splitlines(keepends=True), "outputs": []})
        code_slots.append((len(nb_cells) - 1, src))
nb = {"cells": nb_cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.10"}},
      "nbformat": 4, "nbformat_minor": 5}
OUT = Path("evaluator5.ipynb")
def save():
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
save()
print(f"CREATED {OUT} skeleton ({len(code_slots)} code cells); executing to embed outputs...", flush=True)
ns = {}
for j, (ci, src) in enumerate(code_slots, start=1):
    buf = io.StringIO()
    err = None
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(src, f"<cell{j}>", "exec"), ns)
    except Exception:
        err = traceback.format_exc()
    text = buf.getvalue()
    outs = []
    if text:
        outs.append({"output_type": "stream", "name": "stdout", "text": text.splitlines(keepends=True)})
    if err:
        outs.append({"output_type": "error", "ename": "ExecutionError", "evalue": "see traceback",
                     "traceback": err.splitlines(keepends=True)})
    nb_cells[ci]["execution_count"] = j
    nb_cells[ci]["outputs"] = outs
    save()
    print(f"  cell {j} done ({len(text)} stdout chars){' ERROR' if err else ''}", flush=True)
    if err:
        print(err, flush=True)
        break
print(f"EXECUTED {OUT} (outputs embedded)", flush=True)