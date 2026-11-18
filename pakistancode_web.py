"""Web fallback: fetch federal law texts from the official Pakistan Code website.

Used only when the local indexes do not supply enough authority. The site's own
search endpoint is broken server-side, so this module crawls the alphabetical
law catalog (cached on disk), matches law titles against the query, then fetches
the law's detail page and official PDF and extracts the relevant pages with
PyMuPDF. Every network step fails soft: the chat pipeline never breaks because
the website is slow or down.
"""

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = Path(os.getenv("WEB_CACHE_DIR", str(BASE_DIR / "web_cache")))
SITE_BASE = "https://pakistancode.gov.pk/english/"
CATALOG_URL = SITE_BASE + "LGu0xAD"

WEB_FALLBACK_ENABLED = os.getenv("WEB_FALLBACK_ENABLED", "1").strip().lower() not in ("0", "false", "no")
MAX_LAWS = int(os.getenv("WEB_MAX_LAWS", "2"))
MAX_PAGES_PER_LAW = int(os.getenv("WEB_MAX_PAGES", "2"))
PAGE_CHAR_LIMIT = 1600
REQUEST_TIMEOUT = int(os.getenv("WEB_TIMEOUT", "25"))
CATALOG_TTL_DAYS = 30
MAX_PDF_BYTES = 25 * 1024 * 1024

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LegalLens-FYP"}

_ALIASES = {
    "ppc": "pakistan penal code",
    "crpc": "code of criminal procedure",
    "cpc": "code of civil procedure",
    "qso": "qanun-e-shahadat order",
    "constitution": "constitution of the islamic republic of pakistan",
}

_MATCH_FILLERS = frozenset(
    """
    section sections article provision provisions punishment penalty penalties
    procedure process steps step requirement requirements condition conditions
    meaning definition define explain what which how when who under pursuant
    law laws act acts ordinance ordinances code rule rules pakistan pakistani
    the and for of in on a an is are does do can shall may
    state states stated says said person persons case cases court courts
    """.split()
)


def _request(url: str, **kwargs) -> Optional[requests.Response]:
    try:
        return requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.exceptions.SSLError:
        # pakistancode.gov.pk serves an incomplete certificate chain: Windows
        # trusts it via AIA fetching, certifi cannot. Retry unverified for this
        # read-only public source only.
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            return requests.get(
                url, headers=_HEADERS, timeout=REQUEST_TIMEOUT, verify=False, **kwargs
            )
        except requests.RequestException:
            return None
    except requests.RequestException:
        return None


def _get(url: str) -> Optional[requests.Response]:
    response = _request(url)
    if response is not None and response.status_code == 200:
        return response
    return None


def _query_terms(query: str) -> List[str]:
    expanded = query.lower()
    for short, full in _ALIASES.items():
        expanded = re.sub(rf"\b{short}\b", full, expanded)
    terms = [
        word
        for word in re.findall(r"[a-z0-9]+", expanded)
        if len(word) > 2 and word not in _MATCH_FILLERS
    ]
    return list(dict.fromkeys(terms))


def _parse_law_links(html: str) -> List[Dict[str, str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    laws, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        title = anchor.get_text(strip=True)
        if (
            title
            and len(href) > 15
            and not href.startswith(("#", "http"))
            and ".php" not in href
            and "?" not in href
        ):
            url = urljoin(SITE_BASE, href)
            if url not in seen:
                seen.add(url)
                laws.append({"title": title, "url": url})
    return laws


def _build_catalog() -> List[Dict[str, str]]:
    print("Building Pakistan Code web catalog (one-time crawl)...", flush=True)
    laws, seen = [], set()
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        for page in range(1, 9):
            response = _get(f"{CATALOG_URL}?alp={letter}&page={page}&action=inactive")
            if response is None:
                break
            found = _parse_law_links(response.text)
            new = [law for law in found if law["url"] not in seen]
            if not new:
                break
            for law in new:
                seen.add(law["url"])
                laws.append(law)
            time.sleep(0.3)
    print(f"Pakistan Code catalog ready: {len(laws)} laws.", flush=True)
    return laws


def get_catalog() -> List[Dict[str, str]]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "catalog.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            age_days = (time.time() - data.get("fetched", 0)) / 86400
            if age_days < CATALOG_TTL_DAYS and data.get("laws"):
                return data["laws"]
        except (ValueError, OSError):
            pass
    laws = _build_catalog()
    if laws:
        path.write_text(
            json.dumps({"fetched": time.time(), "laws": laws}, ensure_ascii=False),
            encoding="utf-8",
        )
    return laws


def match_laws(query: str, limit: int = MAX_LAWS) -> List[Dict[str, str]]:
    import math

    terms = _query_terms(query)
    if not terms:
        return []
    catalog = get_catalog()
    if not catalog:
        return []

    def norm(word: str) -> str:
        return word[:-1] if len(word) > 3 and word.endswith("s") else word

    expanded_q = query.lower()
    for short, full in _ALIASES.items():
        expanded_q = re.sub(rf"\b{short}\b", full, expanded_q)
    q_words = set(re.findall(r"[a-z0-9]+", expanded_q))
    # A query naming one Act in full ("pakistan penal code") should outrank a
    # different Act that merely shares one rare title word.
    phrase_bonus = {full for full in _ALIASES.values() if set(full.split()) <= q_words}

    title_words = [
        {norm(word) for word in re.findall(r"[a-z0-9]+", law["title"].lower())}
        for law in catalog
    ]
    # Rare title words ("copyright") must outrank common ones ("registration").
    idf = {
        term: math.log((len(catalog) + 1) / (sum(1 for words in title_words if norm(term) in words) + 1)) + 1
        for term in terms
    }
    scored = []
    for law, words in zip(catalog, title_words):
        score = sum(idf[term] for term in terms if norm(term) in words)
        if score > 0 and any(ph in law["title"].lower() for ph in phrase_bonus):
            score += 4.0
        if score > 0:
            scored.append((score, law))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored:
        return []
    cutoff = scored[0][0] * 0.45
    return [law for score, law in scored[:limit] if score >= cutoff]


def _is_scanned(pages: List[str]) -> bool:
    return not pages or sum(len(page) for page in pages) / len(pages) < 100


def _law_pages(law: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Detail page -> official PDF -> per-page text, cached by detail URL."""
    key = hashlib.sha1(law["url"].encode("utf-8")).hexdigest()[:16]
    cache_path = CACHE_DIR / "texts" / f"{key}.json"
    if cache_path.exists():
        try:
            record = json.loads(cache_path.read_text(encoding="utf-8"))
            if not _is_scanned(record.get("pages", [])):
                return record
        except (ValueError, OSError):
            pass

    response = _get(law["url"])
    if response is None:
        return None
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(response.text, "lxml")
    pdf_url = None
    for anchor in soup.find_all("a", href=True):
        if "pdffiles" in anchor["href"] or anchor["href"].lower().endswith(".pdf"):
            pdf_url = urljoin(law["url"], anchor["href"])
            break
    if not pdf_url:
        return None

    pdf_response = _request(pdf_url, stream=True)
    if pdf_response is None or pdf_response.status_code != 200:
        return None
    try:
        content = pdf_response.raw.read(MAX_PDF_BYTES + 1, decode_content=True)
    except requests.RequestException:
        return None
    if len(content) > MAX_PDF_BYTES:
        return None

    import fitz

    try:
        doc = fitz.open(stream=content, filetype="pdf")
        pages = [page.get_text("text").strip() for page in doc]
        doc.close()
    except Exception:
        return None
    if _is_scanned(pages):
        return None  # scanned PDF: OCR would be too slow for a live chat fallback

    record = {"title": law["title"], "url": law["url"], "pdf_url": pdf_url, "pages": pages}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


_SECTION_MENTION = re.compile(r"\bsection\s*(?:no\.?\s*)?(\d{1,4}[A-Z]?)\b", re.I)
_NEXT_SECTION = re.compile(r"(?m)^\s*\d{1,4}[A-Z]?\s*[.\u00b7]")


def _boilerplate_lines(pages: List[str]) -> set:
    """Lines printed on most pages are running headers/footers, not content."""
    from collections import Counter

    counts: Counter = Counter()
    for text in pages:
        counts.update(
            {
                line.strip()
                for line in text.splitlines()
                if 0 < len(line.strip()) <= 60
            }
        )
    threshold = max(3, int(0.35 * max(1, len(pages))))
    return {line for line, seen in counts.items() if seen >= threshold}


def _relevant_pages(
    record: Dict[str, Any], terms: List[str], query: str = ""
) -> List[Dict[str, Any]]:
    pages = record["pages"]
    boiler = _boilerplate_lines(pages)
    cleaned = [
        "\n".join(
            line for line in text.splitlines() if line.strip() and line.strip() not in boiler
        )
        for text in pages
    ]
    lowered = [text.lower() for text in cleaned]
    n = max(1, len(pages))
    idf = {
        term: (
            0.0
            if term.isdigit()
            else 1.0 + math.log(n / (1 + sum(1 for page in lowered if term in page)))
        )
        for term in terms
    }
    numbers = _SECTION_MENTION.findall((query or "").lower())

    anchor_pat = (
        re.compile(r"(?mi)^\s*" + re.escape(numbers[0]) + r"\s*[.\u00b7]")
        if numbers
        else None
    )
    scored = []
    for number, text in enumerate(cleaned, start=1):
        if not text:
            continue
        page = lowered[number - 1]
        score = sum(idf[term] * min(page.count(term), 3) for term in terms)
        anchored = False
        if anchor_pat is not None:
            anchor = anchor_pat.search(text)
            if anchor:
                nxt = _NEXT_SECTION.search(text, anchor.end())
                if (nxt.start() if nxt else len(text)) - anchor.end() >= 80:
                    score += 20.0  # this page contains the section itself, not a listing
                    anchored = True
        scored.append((score, number, anchored))
    scored.sort(key=lambda item: item[0], reverse=True)
    chosen = [item for item in scored if item[0] > 0][:MAX_PAGES_PER_LAW]
    if not chosen:
        chosen = scored[:1]
    parts = []
    for _, number, anchored in chosen:
        raw = pages[number - 1]
        start = 0
        if anchored:
            # Sections usually start mid-page; window around the anchor so the
            # truncated excerpt actually contains the asked provision.
            m = anchor_pat.search(raw)
            start = max(0, m.start() - 200) if m else 0
        parts.append({"page": number, "text": raw[start : start + PAGE_CHAR_LIMIT]})
    return parts


def search_web_laws(queries: List[str]) -> List[Dict[str, Any]]:
    """Return web authority hits ({kind, doc, score, facet}) for the queries.

    Never raises: any network or parsing failure yields fewer (or zero) hits.
    """
    if not WEB_FALLBACK_ENABLED:
        return []
    from langchain_core.documents import Document

    hits: List[Dict[str, Any]] = []
    seen_urls = set()
    try:
        for query in queries[:3]:
            terms = _query_terms(query)
            for law in match_laws(query):
                if law["url"] in seen_urls:
                    continue
                seen_urls.add(law["url"])
                record = _law_pages(law)
                if record is None:
                    continue
                for part in _relevant_pages(record, terms, query):
                    meta = {
                        "act_name": record["title"],
                        "source": record["url"],
                        "citation": "Pakistan Code online (pakistancode.gov.pk)",
                        "page_label": str(part["page"]),
                        "total_pages": len(record["pages"]),
                        "_web_source": True,
                    }
                    hits.append(
                        {
                            "kind": "law",
                            "doc": Document(page_content=part["text"], metadata=meta),
                            "score": None,
                            "facet": -1,
                            "query": query,
                        }
                    )
                time.sleep(0.3)
    except Exception as exc:
        print(f"Pakistan Code web fallback failed ({type(exc).__name__}: {exc}).", flush=True)
    if hits:
        print(f"Pakistan Code web fallback supplied {len(hits)} passages.", flush=True)
    return hits