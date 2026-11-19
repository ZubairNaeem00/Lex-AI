"""Scratch builder for evaluator6.ipynb (law Qwen index: dense FAISS vs hybrid).
Write-first skeleton; pass --skeleton to create the file without executing."""
import io, json, contextlib, uuid, traceback, sys
from pathlib import Path

MD = r'''# evaluator6 - Law statute retrieval: dense FAISS vs hybrid (FAISS + BM25)

Offline retrieval evaluation of the **Qwen3 statute index** (`faiss_index_law`), no API calls.
Compares two approaches on `law_golden_queries.jsonl`:
1. **Dense** - FAISS vector search only.
2. **Hybrid** - the app's real `hybrid_retrieval.hybrid_search` (BM25 + dense, weighted RRF),
   the same code path production uses for the law channel (`bm25_cache/law`).

**Adaptation from the supplied `eval_law_qwen.py`**
- That script assumed a raw `IndexFlatIP` folder `faiss_law_qwen` + `law_sections.json` + `section_ids.json`.
  This repo instead has `faiss_index_law` (raw **IndexFlatL2**, Qwen3-Embedding-0.6B, 1024-d unit vectors)
  exposed as a LangChain store by `law_index_store.build_law_store`. We use that real store.
- Score is squared-L2 distance; **cosine = 1 - d/2** (higher is better), used for the gate exactly like
  the script's inner-product cosine.
- Gold keys look like `186_Fiscal_..._2005::s15`. The numeric prefix is `pakistan_code_id`; we match a
  gold section to index chunks by `(pakistan_code_id, section_no)` -> `case_id` (PPC, whose key has no
  numeric prefix, matches by upper-cased act-title slug). A retrieved chunk hits gold when its
  `metadata.case_id` equals the gold section's `case_id`.
- Sections have ~2 chunks each, so we rank **distinct sections by first occurrence** in each method's
  ordered hit list (faithful to RRF re-ordering), then take TOP_K=10.

**Metrics**: Recall@1/5/10, MRR@10, nDCG@10 (bootstrap 95% CI), by query type (direct/paraphrase),
ceiling on gold-in-index, and the unanswerable gate (AUC + dev/test threshold sweep).
'''

CELL_A = r'''import os, re, sys, json, time, random, sqlite3
from pathlib import Path
from collections import defaultdict
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
HERE = Path.cwd()
if not (HERE / "law_golden_queries.jsonl").exists() and (HERE / "evaluations" / "law_golden_queries.jsonl").exists():
    HERE = HERE / "evaluations"
REPO = HERE.parent
sys.path.insert(0, str(REPO))
import faiss
faiss.omp_set_num_threads(1)
import numpy as np
import hybrid_retrieval
from law_index_store import build_law_store

LAW_DIR = str(REPO / "faiss_index_law")
GOLD = HERE / "law_golden_queries.jsonl"
KIND = "law"
FETCH_K = 100
TOP_K = 10
SEED = 42
N_BOOT = 2000
THRESH_GRID = np.round(np.arange(0.30, 0.901, 0.01), 2)

t0 = time.time()
print("Building law store (Qwen3, faiss_index_law) ...", flush=True)
store = build_law_store(LAW_DIR)
print(f"store ready: {store.index.ntotal} vectors, dim {store.index.d}, metric L2 ({round(time.time()-t0,1)}s)", flush=True)
hybrid_retrieval._get_entry(KIND, store)

con = sqlite3.connect(f"file:{Path(LAW_DIR)/'metadata.sqlite3'}?mode=ro", uri=True)
by_pcid = defaultdict(set); by_slug = defaultdict(set)
n_sections = 0
for cid, sec, pcid, title in con.execute("SELECT case_id, section_no, pakistan_code_id, act_title FROM statute_sections"):
    n_sections += 1
    sec = str(sec).strip()
    by_pcid[(int(pcid), sec)].add(int(cid))
    by_slug[(str(title).upper().replace(" ", "_"), sec)].add(int(cid))
con.close()

def gold_case_ids(key):
    law_id, sec = key.split("::s"); sec = sec.strip()
    p = law_id.split("_")[0]
    if p.isdigit():
        return by_pcid.get((int(p), sec), set())
    return by_slug.get((law_id, sec), set())

rows = [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()]
gkeys = sorted({r["relevant_citations"][0] for r in rows if r["answerable"]})
covered = {k for k in gkeys if gold_case_ids(k)}
print(f"statute sections in index: {n_sections}", flush=True)
print(f"gold rows {len(rows)}  distinct gold sections {len(gkeys)}  in index {len(covered)} ({100*len(covered)/len(gkeys):.1f}%)", flush=True)
miss = [k for k in gkeys if k not in covered]
print("gold sections NOT in index:", miss, flush=True)
print("setup done", round(time.time() - t0, 1), "s", flush=True)
'''

CELL_B = r'''def group_sections(pairs, top_k):
    seen = {}; order = []
    for doc, d in pairs:
        cid = (doc.metadata or {}).get("case_id")
        if cid is None:
            continue
        cid = int(cid)
        if cid not in seen:
            seen[cid] = 1.0 - float(d) / 2.0
            order.append(cid)
            if len(order) >= top_k:
                break
    return [(cid, seen[cid]) for cid in order]

def make_records(rows, ranked_lists):
    out = []
    for r, ranked in zip(rows, ranked_lists):
        keys = [cid for cid, _ in ranked]
        rec = {"id": r["id"], "query": r["query"], "query_type": r["query_type"],
               "answerable": r["answerable"],
               "top_score": ranked[0][1] if ranked else -1.0,
               "top_sections": keys[:5]}
        if r["answerable"]:
            gcs = gold_case_ids(r["relevant_citations"][0])
            rec["gold"] = r["relevant_citations"][0]
            rec["gold_in_index"] = bool(gcs)
            rec["rank"] = next((i + 1 for i, cid in enumerate(keys) if cid in gcs), None)
        out.append(rec)
    return out

def retrieval_metrics(recs, K=TOP_K):
    ranks = [r.get("rank") for r in recs]
    def hit(k):
        return [1.0 if (x is not None and x <= k) else 0.0 for x in ranks]
    return {"Recall@1": hit(1), "Recall@5": hit(5), "Recall@10": hit(10),
            "MRR@10": [1 / x if (x is not None and x <= K) else 0.0 for x in ranks],
            "nDCG@10": [1 / np.log2(x + 1) if (x is not None and x <= K) else 0.0 for x in ranks]}

def bootstrap_ci(vals, rng):
    v = np.asarray(vals, float)
    if v.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    idx = rng.integers(0, len(v), size=(N_BOOT, len(v)))
    means = v[idx].mean(axis=1)
    return float(v.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

LINES = []
def say(s=""):
    print(s, flush=True); LINES.append(s)

def show_block(title, recs, rng):
    say(f"\n{title}  (n={len(recs)})")
    if not recs:
        say("  no queries"); return {}
    res = {}
    for name, vals in retrieval_metrics(recs).items():
        mu, lo, hi = bootstrap_ci(vals, rng)
        res[name] = mu
        say(f"  {name:10s} {mu:.3f}   95% CI [{lo:.3f}, {hi:.3f}]")
    return res

def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)

def balanced(ans, un, t):
    a = float(np.mean([r["top_score"] >= t for r in ans])) if ans else 0.0
    u = float(np.mean([r["top_score"] < t for r in un])) if un else 0.0
    return (a + u) / 2, a, u

def split_dev_test(recs):
    groups = sorted({r["gold"] for r in recs if r["answerable"] and r.get("gold_in_index")})
    random.Random(SEED).shuffle(groups)
    dev_groups = set(groups[: len(groups) // 2])
    un = [r for r in recs if not r["answerable"]]
    random.Random(SEED + 1).shuffle(un)
    half = len(un) // 2
    dev_ans = [r for r in recs if r["answerable"] and r.get("gold") in dev_groups]
    test_ans = [r for r in recs if r["answerable"] and r.get("gold") not in dev_groups]
    return dev_ans, test_ans, un[:half], un[half:]
'''

CELL_C = r'''dense_ranked = []; hybrid_ranked = []
t = time.time()
for i, r in enumerate(rows, 1):
    q = r["query"]
    dpairs = store.similarity_search_with_score(q, k=FETCH_K)
    hpairs = hybrid_retrieval.hybrid_search(KIND, store, q, FETCH_K)
    if hpairs is None:
        hpairs = dpairs
    dense_ranked.append(group_sections(dpairs, TOP_K))
    hybrid_ranked.append(group_sections(hpairs, TOP_K))
    if i % 50 == 0 or i == len(rows):
        print(f"  {i}/{len(rows)} queries ({round(time.time()-t)}s)", flush=True)
dense_recs = make_records(rows, dense_ranked)
hybrid_recs = make_records(rows, hybrid_ranked)
json.dump(dense_recs, open(HERE / "eval_results_law_dense.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(hybrid_recs, open(HERE / "eval_results_law_hybrid.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("search done", round(time.time() - t), "s; saved eval_results_law_dense.json / _hybrid.json", flush=True)
'''

CELL_D = r'''APPS = [("DENSE (FAISS only)", dense_recs), ("HYBRID (FAISS + BM25, app RRF)", hybrid_recs)]
summaries = {}
for name, recs in APPS:
    say(f"\n########## {name}  |  faiss_index_law (Qwen3)  ##########")
    say("=== Setup ===")
    say(f"Vectors {store.index.ntotal}  dim {store.index.d}  metric L2 (cos = 1 - d/2)")
    say(f"Statute sections {n_sections}  | gold rows {len(rows)}  FETCH_K/TOP_K {FETCH_K}/{TOP_K}")
    ans = [r for r in recs if r["answerable"]]
    un = [r for r in recs if not r["answerable"]]
    ceil = [r for r in ans if r.get("gold_in_index")]
    say(f"Gold sections {len(gkeys)}  in index {len(covered)} ({100*len(covered)/len(gkeys):.1f}%)")
    rng = np.random.default_rng(SEED)
    say("\n=== Retrieval: all answerable ===")
    show_block("All answerable", ans, rng)
    say("\n=== Retrieval: ceiling (gold section in index) ===")
    ov = show_block("Gold in index", ceil, rng)
    say("\n=== By query type (gold in index) ===")
    bytype = {}
    for qt in ("direct", "paraphrase"):
        bytype[qt] = show_block(qt, [r for r in ceil if r["query_type"] == qt], rng)
    say("\n=== Unanswerable gate ===")
    a = auc([r["top_score"] for r in ans], [r["top_score"] for r in un])
    say(f"AUC {a:.3f}  (0.5 chance, 1.0 perfect)")
    dev_ans, test_ans, dev_un, test_un = split_dev_test(recs)
    thr = float(max(THRESH_GRID, key=lambda x: balanced(dev_ans, dev_un, x)[0]))
    bal, a_rate, u_rate = balanced(test_ans, test_un, thr)
    say(f"dev-chosen thr {thr:.2f} -> test TPR {a_rate:.3f} (n={len(test_ans)})  TNR {u_rate:.3f} (n={len(test_un)})  balanced {bal:.3f}")
    say("top-score p10/50/90 answerable   " + str(np.percentile([r["top_score"] for r in ans], [10, 50, 90]).round(3)))
    say("top-score p10/50/90 unanswerable " + str(np.percentile([r["top_score"] for r in un], [10, 50, 90]).round(3)))
    summaries[name] = {"overall": ov, "bytype": bytype, "auc": a, "thr": thr, "tpr": a_rate, "tnr": u_rate,
                       "n_ans": len(ans), "n_ceil": len(ceil)}

say("\n########## SIDE-BY-SIDE  (law Qwen index, same gold) ##########")
say(f"{'metric':22s} {'dense':>10s} {'hybrid':>10s}")
for met in ("Recall@1", "Recall@5", "Recall@10", "MRR@10", "nDCG@10"):
    d = summaries[APPS[0][0]]["overall"].get(met, float("nan"))
    h = summaries[APPS[1][0]]["overall"].get(met, float("nan"))
    say(f"{met:22s} {d:10.3f} {h:10.3f}")
say(f"{'gate AUC':22s} {summaries[APPS[0][0]]['auc']:10.3f} {summaries[APPS[1][0]]['auc']:10.3f}")
say(f"{'gate TPR (test)':22s} {summaries[APPS[0][0]]['tpr']:10.3f} {summaries[APPS[1][0]]['tpr']:10.3f}")
say(f"{'gate TNR (test)':22s} {summaries[APPS[0][0]]['tnr']:10.3f} {summaries[APPS[1][0]]['tnr']:10.3f}")
say("\nRecall@10 by type (ceiling):")
say(f"{'type':14s} {'dense':>10s} {'hybrid':>10s}")
for qt in ("direct", "paraphrase"):
    d = summaries[APPS[0][0]]["bytype"][qt].get("Recall@10", float("nan"))
    h = summaries[APPS[1][0]]["bytype"][qt].get("Recall@10", float("nan"))
    say(f"{qt:14s} {d:10.3f} {h:10.3f}")

say("\n=== Unanswerable review list (hybrid top-score >= answerable p10) ===")
hr = hybrid_recs
ans_h = [r for r in hr if r["answerable"]]; un_h = [r for r in hr if not r["answerable"]]
cut = float(np.percentile([r["top_score"] for r in ans_h], 10))
flagged = sorted([r for r in un_h if r["top_score"] >= cut], key=lambda r: -r["top_score"])
say(f"{len(flagged)} of {len(un_h)} unanswerable queries score at/above answerable p10 ({cut:.3f}); top 15:")
for r in flagged[:15]:
    say(f"  {r['top_score']:.3f}  {r['query']}")
say("\nNote: dense = FAISS only; hybrid = app hybrid_retrieval (BM25 + dense, weighted RRF, same weights")
say("as production). Gold matched by (pakistan_code_id, section_no) -> case_id; 9 gold sections are not")
say("in the index (coverage gap), so ceiling metrics exclude them. Scores are cosine = 1 - L2/2.")
(HERE / "eval_summary_law.txt").write_text("\n".join(LINES) + "\n", encoding="utf-8")
print("\nwrote eval_summary_law.txt", flush=True)
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
OUT = Path("evaluator6.ipynb")
def save():
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
save()
print(f"CREATED {OUT} skeleton ({len(code_slots)} code cells)", flush=True)
if "--skeleton" in sys.argv:
    print("skeleton-only mode; execution deferred", flush=True)
    sys.exit(0)
print("executing to embed outputs...", flush=True)
ns = {}
for j, (ci, src) in enumerate(code_slots, start=1):
    buf = io.StringIO(); err = None
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(src, f"<cell{j}>", "exec"), ns)
    except Exception:
        err = traceback.format_exc()
    text = buf.getvalue(); outs = []
    if text:
        outs.append({"output_type": "stream", "name": "stdout", "text": text.splitlines(keepends=True)})
    if err:
        outs.append({"output_type": "error", "ename": "ExecutionError", "evalue": "see traceback",
                     "traceback": err.splitlines(keepends=True)})
    nb_cells[ci]["execution_count"] = j; nb_cells[ci]["outputs"] = outs
    save()
    print(f"  cell {j} done ({len(text)} stdout chars){' ERROR' if err else ''}", flush=True)
    if err:
        print(err, flush=True); break
print(f"EXECUTED {OUT} (outputs embedded)", flush=True)