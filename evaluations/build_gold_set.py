"""Build the ~200-query retrieval gold set (evaluations/gold_set.json).

Every entry is grounded in the indexed corpus: we take real numbered sections
whose chunk text is present in the law FAISS index, record the Act + page(s)
that contain them, and phrase two citation-style and one natural-style query
around that section. Headings that occur in several Acts only get queries that
name the Act, so no gold entry is unfairly ambiguous. Random seed fixed for a
reproducible, reportable set.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_DIR)
sys.path.insert(0, str(PROJECT_DIR))
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import legal_agent as la  # noqa: E402  (loads indexes)

SECTION_HEAD = re.compile(r"^\s*(\d{1,4}[A-Z]?)\s*[.\u00b7]\s*(.+)$")
HEADING_STOP = re.compile(r"[.\u00b7:]|\s--\s")
BOILERPLATE = {
    "short title", "extent", "commencement", "definitions", "interpretation",
    "savings", "repeal", "repeal and saving", "repeal and savings",
    "statement of objects and reasons", "act to apply", "application of the act",
    "application of act", "rules", "power to make rules", "notification",
    "validation", "removal of difficulties", "saving of pending proceedings",
}
TARGET_GROUPS = 66
MAX_PER_ACT = 4
MIN_BODY_CHARS = 200


def clean_act_name(title: str) -> str:
    name = re.sub(r"\(.*?\)", " ", title)
    name = re.sub(r",\s*\d{4}\s*$", "", name.strip())
    name = re.sub(r"^\d+\s*", "", name.strip())
    name = re.sub(r"\s{2,}", " ", name).strip(" ,")
    return re.sub(r"\s*\(under review\)\s*$", "", name, flags=re.I).strip()


NEXT_SECTION = re.compile(r"(?m)^\s*\d{1,4}[A-Z]?\s*[.\u00b7]")


def heading_from(text: str):
    first_line = text.split("\n", 1)[0]
    m = SECTION_HEAD.match(first_line)
    if not m:
        return None, None
    # Contents-page lines end in a page number ("... prescribed time 283" or dots + digits).
    if re.search(r"(\d{1,4}|\.{3,})\s*$", first_line):
        return None, None
    rest = text[len(first_line):]
    nxt = NEXT_SECTION.search(rest)
    if (nxt.start() if nxt else len(rest)) < 120:
        return None, None  # another numbered line immediately follows: a contents run
    rest = HEADING_STOP.split(m.group(2), maxsplit=1)[0].strip()
    words = rest.split()
    if not 2 <= len(words) <= 8:
        return None, None
    if not all(re.fullmatch(r"[A-Za-z'’-]+", w) for w in words):
        return None, None
    hl = rest.lower()
    if hl in BOILERPLATE or hl.split()[0] in {"amendment", "amend", "repealed"}:
        return None, None
    return m.group(1), hl


def main() -> None:
    store = la.get_store("law")
    groups: dict = {}
    heading_families: dict = defaultdict(set)

    for doc in store.docstore._dict.values():
        text = (doc.page_content or "").strip()
        if len(text) < MIN_BODY_CHARS:
            continue
        num, hl = heading_from(text)
        if not hl:
            continue
        meta = doc.metadata or {}
        fam = la._act_family(meta)
        if not fam:
            continue
        page = str(meta.get("page_label") or meta.get("page_number") or meta.get("page") or "")
        key = (fam, num, hl)
        g = groups.setdefault(key, {"pages": set(), "count": 0, "titles": Counter()})
        g["count"] += 1
        if page.isdigit():
            g["pages"].add(int(page))
        g["titles"][_law_name(meta)] += 1
        heading_families[hl].add(fam)

    eligible = [
        (key, g) for key, g in groups.items()
        if g["pages"] and key[0] not in ("", "pakistani") and max(g["count"], 1)
    ]
    rng = random.Random(42)
    rng.shuffle(eligible)

    picked, per_act = [], Counter()
    for key, g in eligible:
        fam = key[0]
        if per_act[fam] >= MAX_PER_ACT:
            continue
        picked.append((key, g))
        per_act[fam] += 1
        if len(picked) >= TARGET_GROUPS:
            break

    def relevant(act_display: str, pages) -> int:
        slug = la._act_family({"act_name": act_display})
        return sum(
            g["count"] for (fam, _n, _h), g in groups.items()
            if (fam.startswith(slug) or slug.startswith(fam)) and g["pages"] & set(pages)
        ) or 1

    gold = []
    for (fam, num, hl), g in picked:
        name = clean_act_name(g["titles"].most_common(1)[0][0])
        if not name:
            continue
        pages = sorted(g["pages"])
        n_rel = relevant(name, pages)
        unique = len(heading_families[hl]) == 1
        natural_q = (
            f"what is {hl} in pakistani law" if unique
            else f"what does the {name} say about {hl}"
        )
        for query, qtype in [
            (f"what is section {num} of the {name}", "citation"),
            (f"tell me about section {num} ({name})", "citation"),
            (natural_q, "natural"),
        ]:
            gold.append({
                "query": query, "act": name, "pages": pages, "type": qtype,
                "n_relevant": n_rel, "section": num, "heading": hl,
            })

    curated = [
        {"query": "what section 379 of pakistan penal code says",
         "act": "Pakistan Penal Code", "pages": [137], "type": "citation"},
        {"query": "PPC section 379",
         "act": "Pakistan Penal Code", "pages": [137], "type": "citation"},
        {"query": "what is punishment for theft",
         "act": "Pakistan Penal Code", "pages": [137], "type": "natural"},
        {"query": "punishment for theft under section 379 PPC",
         "act": "Pakistan Penal Code", "pages": [137], "type": "citation"},
        {"query": "tazir punishment for theft Enforcement of Hudood Ordinance 1979",
         "act": "Offences Against Property (Enforcement of Hudood)", "pages": [7],
         "type": "natural"},
    ]
    seen = {e["query"] for e in gold}
    for item in curated:
        if item["query"] in seen:
            continue
        item["n_relevant"] = relevant(item["act"], item["pages"])
        gold.append(item)

    Path("evaluations/gold_set.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")

    acts = {e["act"] for e in gold}
    print(f"gold entries: {len(gold)}  |  acts: {len(acts)}  |  "
          f"types: {dict(Counter(e['type'] for e in gold))}")
    print("sample queries:")
    for e in gold[:3] + gold[-3:]:
        print(f"  [{e['type']:8}] {e['query'][:78]} -> {e['act'][:32]} p.{e['pages']} n_rel={e['n_relevant']}")


def _law_name(meta) -> str:
    return la._law_document_title(meta)


if __name__ == "__main__":
    main()
