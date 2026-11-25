"""OMENZ Doc Read: turn a public PDF or document into clean text an agent can use (2026-11-24).

Evidence (DEMAND_SCAN_2026-11-24): "pdf / document parse" = 674 paying agents / 30d, 149 sellers, top seller 28 payers,
median $0.005. Deterministic, no AI: pypdf text extraction per page + metadata, link annotations, a stopword language
guess, a simple tables hint. Also .txt / .md / .html. Input: {url} (public https) or {content_base64, filename}.
Priced per DOCUMENT (not per page): first 50 pages read (pages_limited says so). Native text only, NO OCR: an image-only
/scanned PDF returns no_text_layer/needs_ocr = true instead of silently empty text.
Max 10 MB in, 15 s fetch budget (25 s total), text capped at 200k chars (truncated flag says so). Stores nothing.
"""
import base64
import binascii
import io
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import checker
import link_check

VERSION = "0.1.0"
MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 200_000
MAX_PAGES = 50  # priced per document: first 50 pages read; output says so (pages_limited)
TIMEOUT = 15  # fetch budget (s)
PARSE_BUDGET = 25  # total budget incl. parse (s); Vercel maxDuration is 30
logging.getLogger("pypdf").setLevel(logging.ERROR)  # font/EOF warnings are noise in function logs
MAX_HOPS = 5
UA = "OMENZ-DocRead/0.1 (+https://www.omenz.org)"
TEXT_EXT = {".txt": "text", ".md": "markdown", ".markdown": "markdown", ".html": "html", ".htm": "html", ".pdf": "pdf"}
STOP = {
    "en": "the and of to in is that for it with as was on are be this by not or have from at which but an they you we his her",
    "es": "el la de que y en los se del las un por con no una su para es al lo como más pero sus le ya o fue este",
    "fr": "le la de et les des en un une du est que pour qui dans pas au sur par plus ne se ce il sont avec",
    "de": "der die und den das von zu mit ist des sich nicht auf ein eine dem für im auch es an als werden aus er",
    "pt": "de que o a e do da em um para com não uma os no se na por mais as dos como mas foi ao ele das",
    "it": "di che il la e per un in non una sono del della è le con si da al lo come ma anche gli nel",
    "nl": "de het een en van in is dat op te zijn met voor niet aan er ook als bij door maar om uit worden",
}
STOP = {k: set(v.split()) for k, v in STOP.items()}
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def _err(code, msg, **extra):
    return {"version": VERSION, "stored": False, "error": msg, "code": code, **extra}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _ok_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.hostname:
        return "url must be https:// (public address)"
    pub = link_check._public(u.hostname)
    if pub is None:
        return "url host does not resolve"
    if pub is not True:
        return "url must be a public internet address (private/loopback/reserved blocked)"
    return None


def _fetch(url, deadline):
    """GET with every redirect hop re-checked (https + public), size and time capped."""
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=link_check._ctx()))
    for _ in range(MAX_HOPS + 1):
        bad = _ok_url(url)
        if bad:
            return None, None, _err("bad_url", bad, url=url)
        left = deadline - time.monotonic()
        if left <= 1:
            return None, None, _err("timeout", f"fetch took longer than {TIMEOUT}s")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,text/*;q=0.9,*/*;q=0.5"})
        try:
            r = opener.open(req, timeout=min(left, TIMEOUT))
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            return None, None, _err("fetch_failed", f"the URL answered HTTP {e.code}", url=url)
        except Exception as e:
            return None, None, _err("fetch_failed", f"couldn't reach the URL ({type(e).__name__})", url=url)
        with r:
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                return None, None, _err("too_large", f"document is {int(cl)} bytes; max {MAX_BYTES}")
            buf = bytearray()
            while True:
                if time.monotonic() > deadline:
                    return None, None, _err("timeout", f"download took longer than {TIMEOUT}s")
                chunk = r.read(65536)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_BYTES:
                    return None, None, _err("too_large", f"document is over {MAX_BYTES} bytes")
            return bytes(buf), {"final_url": url, "content_type": (r.headers.get("Content-Type") or "").lower()}, None
    return None, None, _err("fetch_failed", f"more than {MAX_HOPS} redirects")


def _kind(data, name, ctype):
    if data[:1024].lstrip()[:5] == b"%PDF-" or b"%PDF-" in data[:1024]:
        return "pdf"
    m = re.search(r"\.[a-z]+$", (name or "").lower().split("?")[0])
    if m and m.group(0) in TEXT_EXT:
        return TEXT_EXT[m.group(0)]
    if "pdf" in ctype:
        return "pdf"
    if "html" in ctype:
        return "html"
    if "markdown" in ctype:
        return "markdown"
    if ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        return "text"
    head = data[:2048].lower()
    if b"<html" in head or b"<!doctype html" in head:
        return "html"
    if b"\x00" in data[:4096]:
        return None
    return "text"


def _decode(data, ctype):
    m = re.search(r"charset=([\w-]+)", ctype or "")
    for enc in ([m.group(1)] if m else []) + ["utf-8"]:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("latin-1")


def _lang(text):
    words = re.findall(r"[^\W\d_]+", text[:50000].lower())
    if len(words) < 20:
        return {"code": None, "confidence": "low", "method": "stopword counts", "note": "too little text to guess"}
    score = {k: sum(1 for w in words if w in s) for k, s in STOP.items()}
    best = sorted(score.items(), key=lambda kv: -kv[1])
    top, n = best[0]
    second = best[1][1]
    if n < 5:
        return {"code": None, "confidence": "low", "method": "stopword counts", "note": "no supported language matched (en es fr de pt it nl)"}
    conf = "high" if n >= 2 * max(second, 1) and n / len(words) > 0.15 else "medium" if n > 1.3 * second else "low"
    return {"code": top, "confidence": conf, "method": "stopword counts over en es fr de pt it nl"}


def _tables_hint(pages_text):
    """Pages with 3+ consecutive lines that look columnar (tabs, or 3+ cells split by 2+ spaces / pipes)."""
    hits = []
    for i, t in enumerate(pages_text, 1):
        run = best = 0
        for line in t.splitlines():
            cells = [c for c in re.split(r"\t|\s{2,}|\s\|\s|^\||\|$", line.strip()) if c.strip()]
            if len(cells) >= 3:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best >= 3:
            hits.append(i)
    return {"likely": bool(hits), "pages": hits[:50],
            "note": "heuristic: 3+ consecutive column-like lines; cell structure is not reconstructed"}


def _date(v):
    if not v:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", str(v))
    if not m:
        return str(v)[:40]
    y, mo, d, h, mi, s = (g or "" for g in m.groups())
    out = y + (f"-{mo}" if mo else "") + (f"-{d}" if d else "")
    return out + (f"T{h}:{mi or '00'}:{s or '00'}" if h else "")


def _pdf(data, deadline):
    try:
        import pypdf
    except ImportError:
        return None, _err("unavailable", "PDF engine not installed on this server")
    try:
        rd = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if rd.is_encrypted:
            try:
                if not rd.decrypt(""):
                    return None, _err("encrypted", "PDF is password-protected")
            except Exception:
                return None, _err("encrypted", "PDF is encrypted with a method we can't open")
        n = len(rd.pages)
    except Exception as e:
        return None, _err("unreadable", f"not a readable PDF ({type(e).__name__})")
    meta = {}
    try:
        md = rd.metadata or {}
        meta = {"title": (md.get("/Title") or None), "author": (md.get("/Author") or None),
                "subject": md.get("/Subject") or None, "creator": md.get("/Creator") or None, "producer": md.get("/Producer") or None,
                "created": _date(md.get("/CreationDate")), "modified": _date(md.get("/ModDate"))}
        meta = {k: (str(v).strip()[:300] if v is not None else None) for k, v in meta.items()}
    except Exception:
        pass
    texts, links, note = [], [], None
    for i in range(min(n, MAX_PAGES)):
        if time.monotonic() > deadline:
            note = f"stopped at page {i} of {n}: {PARSE_BUDGET}s time budget"
            break
        p = None
        try:
            p = rd.pages[i]
            texts.append(p.extract_text() or "")
        except Exception:
            texts.append("")
        try:
            for a in ((p.get("/Annots") if p is not None else None) or []):
                a = a.get_object()
                uri = (a.get("/A") or {}).get("/URI") if a.get("/Subtype") == "/Link" else None
                if uri:
                    links.append({"url": str(uri)[:2000], "page": i + 1, "source": "annotation"})
        except Exception:
            pass
    if n > MAX_PAGES and not note:
        note = f"read first {MAX_PAGES} of {n} pages (per-document limit)"
    return {"kind": "pdf", "page_count": n, "meta": meta, "texts": texts, "links": links, "pages_note": note,
            "pdf_version": getattr(rd, "pdf_header", "")[1:] or None}, None


def _textdoc(data, kind, ctype):
    raw = _decode(data, ctype)
    meta = {"title": None, "author": None, "created": None}
    links = []
    if kind == "html":
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
        meta["title"] = checker.visible_text(m.group(1))[:300] if m else None
        m = re.search(r"<meta[^>]+name=[\"']author[\"'][^>]+content=[\"']([^\"']*)", raw, re.I)
        meta["author"] = m.group(1)[:300] if m else None
        for h in re.findall(r"<a\b[^>]*\bhref=[\"']([^\"'#][^\"']*)", raw, re.I):
            if h.lower().startswith(("http://", "https://")):
                links.append({"url": h[:2000], "page": 1, "source": "href"})
        text = checker.visible_text(re.sub(r"<(br|/p|/div|/h\d|/li|/tr)\b[^>]*>", "\n", raw, flags=re.I))
    else:
        text = raw.replace("\r\n", "\n")
        if kind == "markdown":
            m = re.search(r"^#\s+(.+)$", text, re.M)
            meta["title"] = m.group(1).strip()[:300] if m else None
    return {"kind": kind, "page_count": 1, "meta": meta, "texts": [text], "links": links, "pages_note": None}, None


def read(d):
    t0 = time.monotonic()
    deadline = t0 + TIMEOUT
    if not isinstance(d, dict):
        return _err("bad_input", "send a JSON object: {url} or {content_base64, filename}")
    url, b64 = d.get("url"), d.get("content_base64")
    src = {}
    if url and b64:
        return _err("bad_input", "send url OR content_base64, not both")
    if url:
        if not isinstance(url, str) or len(url) > 4000:
            return _err("bad_url", "url must be a string under 4000 chars")
        data, info, e = _fetch(url.strip(), deadline)
        if e:
            return e
        name = urllib.parse.urlparse(info["final_url"]).path
        src = {"type": "url", "url": url, "final_url": info["final_url"], "content_type": info["content_type"] or None}
        ctype = info["content_type"]
    elif b64:
        if not isinstance(b64, str):
            return _err("bad_input", "content_base64 must be a base64 string")
        if len(b64) > MAX_BYTES * 4 // 3 + 8:
            return _err("too_large", f"document is over {MAX_BYTES} bytes")
        try:
            data = base64.b64decode(re.sub(r"^data:[^,]*,", "", b64.strip()), validate=False)
        except (binascii.Error, ValueError):
            return _err("bad_input", "content_base64 is not valid base64")
        if len(data) > MAX_BYTES:
            return _err("too_large", f"document is {len(data)} bytes; max {MAX_BYTES}")
        name = str(d.get("filename") or "")
        src = {"type": "upload", "filename": name or None}
        ctype = ""
    else:
        return _err("bad_input", "send {url: 'https://...pdf'} or {content_base64, filename}")
    if not data:
        return _err("empty", "document is empty")
    kind = _kind(data, name, ctype)
    if kind is None:
        return _err("unsupported", "unsupported document type; supported: PDF, .txt, .md, .html")
    doc, e = _pdf(data, t0 + PARSE_BUDGET) if kind == "pdf" else _textdoc(data, kind, ctype)
    if e:
        return e
    texts = doc["texts"]
    full = "\n".join(texts)
    pages, used, truncated = [], 0, False
    for i, t in enumerate(texts, 1):
        t = t.strip()
        room = MAX_CHARS - used
        if room <= 0:
            truncated = True
            break
        if len(t) > room:
            t, truncated = t[:room], True
        used += len(t)
        pages.append({"page": i, "chars": len(t), "text": t})
    seen, links = set(), []
    for l in doc["links"] + [{"url": u.rstrip(".,;:"), "page": None, "source": "text"} for u in URL_RE.findall(full)]:
        if l["url"] not in seen:
            seen.add(l["url"])
            links.append(l)
    words = len(re.findall(r"\w+", full))
    empty_pages = sum(1 for t in texts if not t.strip())
    notes = []
    no_text = doc["kind"] == "pdf" and bool(texts) and sum(len(t.strip()) for t in texts) < 5 * len(texts)
    if no_text:
        notes.append("no text layer: scanned/image-only PDF, needs OCR (Doc Read extracts native text only, no OCR)")
    elif empty_pages:
        notes.append(f"{empty_pages} page(s) had no extractable text (images or blank)")
    if doc.get("pages_note"):
        notes.append(doc["pages_note"])
    if truncated:
        notes.append(f"text truncated at {MAX_CHARS} chars; word_count covers the full extracted text")
    return {"version": VERSION, "stored": False, "source": src, "bytes": len(data), "format": doc["kind"],
            **({"pdf_version": doc["pdf_version"]} if doc.get("pdf_version") else {}),
            "page_count": doc["page_count"], "pages_read": len(texts), "page_limit": MAX_PAGES,
            "pages_limited": doc["page_count"] > len(texts), "pages_returned": len(pages),
            "no_text_layer": no_text, "needs_ocr": no_text, "metadata": doc["meta"],
            "language": _lang(full), "word_count": words, "char_count": len(full), "truncated": truncated,
            "tables_hint": _tables_hint(texts), "links": links[:500], "links_count": len(links),
            "pages": pages, "notes": notes, "ms": int((time.monotonic() - t0) * 1000),
            "method": "deterministic extraction (pypdf for PDF), no AI, no OCR"}
