"""OMENZ Agent data hygiene: the small checks that keep agents from re-buying, over-carrying or misusing data.

- terms(url)             API Terms Extractor / Data-License Checker: terms/license page -> clauses by category with quotes
                         + plain flags (no commercial use, attribution required, trains on your data, rate limits...).
- freshness(url, kind)   Source Freshness / Result TTL: the source's own Last-Modified/ETag/Cache-Control + a reuse window
                         by data kind -> reuse_until, "refetch?" answer.
- dedupe(...)            Duplicate-Work Detector: fingerprint a task (normalized) inside a private namespace; HIT returns the
                         earlier result pointer so nobody pays to redo it; MISS can register this run.
- diet(packet, ...)      Context Diet: shrink a packet (drop empties, dedupe lists, cut long strings to head + sha256 pointer,
                         keep required fields) + bytes/tokens saved.
Deterministic, no AI calls.
"""
import hashlib
import hmac
import json
import re
import time
import urllib.request

import business_facts as bf
from checker import visible_text
from locker import LockerError, _kv

VERSION = "0.1.0"
CLAUSES = {
    "commercial_use": r"commercial(?:ly)? use|for commercial purposes|non-?commercial|personal use only",
    "attribution": r"attribut\w+|credit (?:the|us)|must (?:cite|credit)|powered by",
    "rate_limits": r"rate.?limit\w*|requests? per (?:second|minute|hour|day)|quota|throttl\w*|\b\d+\s?(?:rpm|rps|req/s)\b",
    "data_retention": r"retain\w*|retention|delete\w* (?:after|within)|stored for|keep (?:your|the) data",
    "training": r"train\w* (?:on|our|models?|ai)|machine learning|improve (?:our|the) (?:models?|services?)",
    "prohibited": r"prohibit\w*|you (?:may|shall|must) not|not permitted|forbidden|restricted from|scrap\w*|reverse engineer",
    "resale": r"resell\w*|resale|redistribut\w*|sublicens\w*",
    "refunds": r"refund\w*|money back|non-?refundable",
    "liability": r"liabilit\w*|as is|warrant\w*|indemnif\w*",
    "termination": r"terminat\w*|suspend\w*",
    "license": r"\b(?:mit|apache 2\.0|bsd|gpl|cc[- ]by(?:[- ]sa|[- ]nc|[- ]nd)*|creative commons|public domain|cc0)\b",
}
FLAGS = [("no_commercial_use", r"non-?commercial|personal use only|not for commercial"),
         ("attribution_required", r"(?:must|shall|required to) (?:attribute|credit|cite)|attribution (?:is )?required|cc[- ]by"),
         ("may_train_on_your_data", r"(?:use|may use) (?:your|customer) (?:data|content|inputs?) to (?:train|improve)"),
         ("no_resale", r"(?:may|shall) not (?:resell|redistribute|sublicense)|no resale"),
         ("no_scraping", r"(?:may|shall) not (?:scrape|crawl)|scraping is prohibited|automated (?:access|collection) is prohibited"),
         ("non_refundable", r"non-?refundable|no refunds")]
TTL = {"price": 3600, "quote": 300, "hours": 86400, "weather": 1800, "news": 900, "stock": 60, "crypto": 60,
       "business_facts": 7 * 86400, "terms": 7 * 86400, "docs": 7 * 86400, "filing": 10 * 365 * 86400, "profile": 30 * 86400,
       "search": 86400, "generic": 86400}


def _sents(text):
    return [s.strip() for s in re.split(r"(?<![A-Z]\.)(?<=[.!?;])\s+|\n+|\s{3,}", text) if 25 <= len(s.strip()) <= 600]


def terms(url):
    if not re.match(r"^https?://", url or "", re.I):
        url = "https://" + (url or "")
    r = bf._fetch(url)
    out = {"version": VERSION, "url": url, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not r.get("ok"):
        return {**out, "status": "unreadable", "http_status": r.get("status"), "blocked_by": r.get("blocked_by")}
    text = " ".join(re.sub(r"<[^>]{0,400}>", " ", visible_text(r["text"])).split())
    sents = _sents(text)
    clauses = {}
    for k, rx in CLAUSES.items():
        hits = [s for s in sents if re.search(rx, s, re.I)][:3]
        if hits:
            clauses[k] = hits
    low = text.lower()
    flags = [name for name, rx in FLAGS if re.search(rx, low)]
    upd = re.search(r"\b(?:last (?:updated|modified|revised)|effective(?: date| as of)?)\s*[:\-]?\s*([A-Z][a-z]+\.? \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2})", text)
    return {**out, "status": "ok" if clauses else "no_terms_found", "final_url": r["url"], "last_updated_stated": upd.group(1) if upd else None,
            "flags": flags, "clauses": clauses, "categories_found": sorted(clauses),
            "note": "Quotes are the page's own words; flags are pattern-based. Not legal advice. Read the quotes before relying on a flag."}


def freshness(url, kind="generic"):
    if not re.match(r"^https?://", url or "", re.I):
        url = "https://" + (url or "")
    kind = (kind or "generic").lower()
    base_ttl = TTL.get(kind, TTL["generic"])
    out = {"version": VERSION, "url": url, "kind": kind if kind in TTL else "generic", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": bf.UA if hasattr(bf, "UA") else "OMENZ-freshness/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            h = {k.lower(): v for k, v in resp.headers.items()}
            status = resp.status
    except urllib.error.HTTPError as e:
        h, status = {k.lower(): v for k, v in (e.headers or {}).items()}, e.code
    except Exception as e:
        return {**out, "status": "unreachable", "error": type(e).__name__, "reuse_seconds": 0, "refetch": True}
    max_age = None
    m = re.search(r"max-age=(\d+)", h.get("cache-control", ""))
    if m:
        max_age = int(m.group(1))
    cc = h.get("cache-control", "")
    no_store = "no-store" in cc
    # max-age is the CDN's revalidation hint, not how long the facts stay true: keep both, and only no-store kills reuse
    ttl = 0 if no_store else base_ttl
    revalidate = 0 if ("no-cache" in cc and max_age is None) else max_age
    lm = h.get("last-modified")
    lm_ts = None
    if lm:
        try:
            lm_ts = int(time.mktime(time.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT")) - time.timezone)
        except ValueError:
            lm_ts = None
    return {**out, "status": "ok" if status < 400 else "http_error", "http_status": status, "last_modified": lm,
            "age_of_content_seconds": int(time.time()) - lm_ts if lm_ts else None, "etag": h.get("etag"),
            "cache_control": h.get("cache-control"), "reuse_seconds": ttl, "reuse_until": int(time.time()) + ttl,
            "revalidate_after_seconds": revalidate,
            "how_to_revalidate": "send If-None-Match with the etag (or If-Modified-Since): a 304 means your copy is still current" if (h.get("etag") or lm) else None,
            "basis": (f"source says no-store: don't reuse" if no_store else f"{kind} data: reasonable reuse {base_ttl}s") +
                     (f"; the source asks caches to recheck after {max_age}s" if max_age is not None else "")}


def _norm(task):
    if isinstance(task, str):
        return " ".join(task.lower().split())
    if isinstance(task, dict):
        return {str(k).lower(): _norm(v) for k, v in sorted(task.items()) if v not in (None, "", [], {})}
    if isinstance(task, list):
        return [_norm(x) for x in task]
    return task


def dedupe(namespace_key, task, result_pointer=None, ttl_hours=168):
    if not namespace_key or len(str(namespace_key)) < 16:
        raise LockerError(422, "namespace_key (your private string, 16+ chars) required: only agents with it share fingerprints")
    if task in (None, "", {}, []):
        raise LockerError(422, "task required (the request you're about to run)")
    ns = "dd_" + hashlib.sha256(("omenz-dedupe|" + str(namespace_key)).encode()).hexdigest()[:32]
    fp = hashlib.sha256(json.dumps(_norm(task), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    rec = _kv("GET", ns) or {"items": {}}
    now = int(time.time())
    rec["items"] = {k: v for k, v in rec["items"].items() if v["until"] > now}
    hit = rec["items"].get(fp)
    if hit:
        return {"verdict": "HIT", "fingerprint": fp, "result_pointer": hit["pointer"], "done_at": hit["at"], "reuse_until": hit["until"],
                "note": "already done in this namespace: reuse the pointer instead of paying again"}
    out = {"verdict": "MISS", "fingerprint": fp, "registered": False}
    if result_pointer:
        try:
            hrs = max(1, min(int(ttl_hours or 168), 24 * 90))
        except (TypeError, ValueError):
            raise LockerError(422, "ttl_hours must be an integer")
        if len(rec["items"]) >= 2000:
            oldest = sorted(rec["items"].items(), key=lambda kv: kv[1]["at"])[:200]
            for k, _ in oldest:
                rec["items"].pop(k, None)
        rec["items"][fp] = {"pointer": str(result_pointer)[:300], "at": now, "until": now + hrs * 3600}
        _kv("PUT", ns, rec)
        out.update(registered=True, reuse_until=now + hrs * 3600)
    return out


def diet(packet, required=None, max_string_chars=400, max_list_items=50):
    if not isinstance(packet, (dict, list)):
        raise LockerError(422, "packet must be a JSON object or list")
    try:
        msc = max(40, min(int(max_string_chars or 400), 20000))
        mli = max(1, min(int(max_list_items or 50), 1000))
    except (TypeError, ValueError):
        raise LockerError(422, "max_string_chars / max_list_items must be integers")
    req = set(required or [])
    cut = []

    def slim(v, path, keep):
        if isinstance(v, dict):
            o = {}
            for k, x in v.items():
                p = f"{path}.{k}"
                kp = keep or k in req
                y = slim(x, p, kp)
                if y in (None, "", [], {}) and not kp:
                    continue
                o[k] = y
            return o
        if isinstance(v, list):
            seen, o = set(), []
            for i, x in enumerate(v):
                key = json.dumps(x, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                o.append(slim(x, f"{path}[{i}]", keep))
            if len(o) > mli and not keep:
                cut.append({"path": path, "dropped_items": len(o) - mli})
                o = o[:mli] + [{"_omitted_items": len(o) - mli}]
            return o
        if isinstance(v, str) and len(v) > msc and not keep:
            h = hashlib.sha256(v.encode()).hexdigest()[:16]
            cut.append({"path": path, "chars": len(v), "sha256_16": h})
            return v[:msc] + f"… [cut {len(v) - msc} chars, sha256:{h}]"
        return v

    before = len(json.dumps(packet, ensure_ascii=False).encode())
    slimmed = slim(packet, "$", False)
    after = len(json.dumps(slimmed, ensure_ascii=False).encode())
    missing = [f for f in req if not (isinstance(slimmed, dict) and f in slimmed)]
    return {"packet": slimmed, "bytes_before": before, "bytes_after": after, "saved_share": round(1 - after / before, 3) if before else 0,
            "approx_tokens_saved": max(0, (before - after) // 4), "cuts": cut[:50], "required_missing": missing,
            "note": "cut strings keep their first part + a sha256 so the full text can be fetched from your own store if needed"}
