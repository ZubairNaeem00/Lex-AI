"""Corpus-grounded retrieval gold set for faiss_index_cases (bge-base).

Offline, reproducible, no API calls. Every answerable query's gold case is
present in the index by construction. Queries are derived from each case's
UNIQUE summary headnote and case name, so they are realistically retrievable
rather than verbatim copies. Out-of-corpus queries are marked unanswerable.

Run from evaluations/:  python build_gold_cases.py
Writes golden_queries_bge.jsonl and prints coverage + contamination diagnostics.
"""
from __future__ import annotations

import json
import pickle
import random
import re
from collections import defaultdict
from pathlib import Path

INDEX_DIR = Path("../faiss_index_cases")
OUT = Path("golden_queries_bge.jsonl")
TARGET_CASES = 150
SEED = 42
MIN_SUMMARY = 80

STOP_ISSUES = {
    "scope", "permissibility", "effect", "contention raised", "contentions raised",
    "held", "facts", "brief facts", "question", "issue", "headnote", "head note",
}
SECTION_REF = re.compile(r"^(ss?\.|secs?\.|sched|art\.|r\.|rule|order|\d)")


def canon(s: str) -> str:
    s = re.sub(r"(?i)citation\s*name\s*:", " ", s or "")
    s = re.split(r"(?i)bookmark", s)[0]
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean_citation(raw: str) -> str:
    s = re.sub(r"(?i)citation\s*name\s*:", "", raw or "")
    s = re.split(r"(?i)bookmark", s)[0]
    return " ".join(s.split())


def issue_phrases(summary: str):
    out = []
    for part in summary.split("---"):
        p = part.strip(" -\t")
        pl = p.lower()
        if len(p) < 15 or pl in STOP_ISSUES or SECTION_REF.match(pl):
            continue
        if len(p.split()) < 3:
            continue
        out.append(p)
    return out


UNANSWERABLE = [
    "what is the punishment for treason under the United States Constitution",
    "how do I file for divorce under English family law",
    "what are the requirements for a valid patent under the European Patent Convention",
    "how is corporate tax calculated under the UK Corporation Tax Act",
    "what is the procedure for impeachment of the President of India",
    "rules of evidence in Canadian criminal trials",
    "how to register a trademark in Japan",
    "what is the capital of Australia",
    "how do I bake sourdough bread at home",
    "explain the theory of general relativity",
    "what are the GDPR data protection requirements for EU companies",
    "how does the French civil code handle contract formation",
    "what is the penalty for insider trading under US SEC regulations",
    "procedure for adopting a child under German law",
    "what is the statute of limitations for personal injury in California",
    "how to incorporate a company in Delaware",
    "what are the Miranda rights in United States criminal procedure",
    "explain the doctrine of consideration in English contract law",
    "what is the process for judicial review in the UK Supreme Court",
    "how are damages calculated in Australian tort law",
    "requirements for a valid will under New York law",
    "how does the Canadian charter of rights protect freedom of expression",
    "what is the punishment for theft under the Japanese Penal Code",
    "procedure for bankruptcy filing in the United States",
    "what are the employment rights of workers in the European Union",
    "how to appeal a traffic fine in New South Wales",
    "explain the separation of powers in the Brazilian constitution",
    "what is the legal age of marriage in Sweden",
    "how do I claim asylum in the United Kingdom",
    "what is the role of the jury in a Scottish criminal trial",
]


def main() -> None:
    with open(INDEX_DIR / "index.pkl", "rb") as f:
        docstore, _ = pickle.load(f)
    d = getattr(docstore, "_dict", docstore)

    by_case = defaultdict(lambda: {"name": "", "summary": [], "chunks": 0})
    chunk_owner = defaultdict(set)          # content hash -> citations (contamination probe)
    total_chunks = 0
    for doc in d.values():
        m = doc.metadata or {}
        c = m.get("citation", "")
        e = by_case[c]
        e["chunks"] += 1
        total_chunks += 1
        if m.get("case_name"):
            e["name"] = m["case_name"]
        t = (doc.page_content or "").strip()
        if t:
            chunk_owner[hash(t)].add(c)
        if t.upper().startswith("CASE SUMMARY:"):
            body = t[len("CASE SUMMARY:"):].strip()
            if body:
                e["summary"].append(body)

    shared = sum(1 for owners in chunk_owner.values() if len(owners) > 1)
    print("=== Corpus diagnostics (faiss_index_cases) ===")
    print(f"cases: {len(by_case)}  chunks: {total_chunks}  distinct chunk texts: {len(chunk_owner)}")
    print(f"chunk texts shared across >1 case: {shared} "
          f"({100*shared/max(len(chunk_owner),1):.1f}%)  <- cross-case contamination")

    sum_key = defaultdict(set)
    for c, e in by_case.items():
        s = " ".join(e["summary"])
        e["summary_text"] = s
        if s:
            sum_key[canon(s)].add(c)
    empty = sum(1 for e in by_case.values() if not e["summary_text"])
    eligible = [
        c for c, e in by_case.items()
        if len(e["summary_text"]) >= MIN_SUMMARY and e["name"]
        and len(sum_key[canon(e["summary_text"])]) == 1
    ]
    print(f"cases with empty summary: {empty}  |  eligible (unique summary >= {MIN_SUMMARY} chars): {len(eligible)}")

    rng = random.Random(SEED)
    rng.shuffle(eligible)
    picked = eligible[:TARGET_CASES]

    rows = []
    qid = 0
    for c in picked:
        e = by_case[c]
        cc = clean_citation(c)
        name = e["name"]
        issues = issue_phrases(e["summary_text"])
        if issues:
            issue_q = "what is the ruling on " + " ".join(issues[:2]).lower()
        else:
            issue_q = f"what was decided in {name}"
        for qt, q in (("citation", cc), ("case_name", name), ("issue", issue_q)):
            qid += 1
            rows.append({"query": q, "query_type": qt, "relevant_citations": [c],
                         "answerable": True, "id": f"b{qid:04d}", "language": "en"})
    for q in UNANSWERABLE:
        qid += 1
        rows.append({"query": q, "query_type": "unanswerable", "relevant_citations": [],
                     "answerable": False, "id": f"b{qid:04d}", "language": "en"})

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    keys = {canon(c) for c in by_case} - {""}
    gold = {canon(c) for r in rows if r["answerable"] for c in r["relevant_citations"]} - {""}
    ans = sum(r["answerable"] for r in rows)
    print("\n=== Gold set ===")
    print(f"wrote {OUT}  rows {len(rows)}  answerable {ans}  unanswerable {len(UNANSWERABLE)}")
    print(f"distinct gold cases {len(gold)}  coverage {len(gold & keys)}/{len(gold)} (100% by construction)")
    print("query types:", dict(__import__("collections").Counter(r["query_type"] for r in rows)))
    print("\nsamples:")
    for r in rows[:6]:
        print(f"  [{r['query_type']:9}] {r['query'][:95]}")


if __name__ == "__main__":
    main()