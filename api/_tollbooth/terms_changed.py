"""OMENZ Terms Changed?: did an API's pricing / limits / terms page change in a way that MATTERS?

Agents that depend on paid tools need to know when prices, rate limits, quotas, commercial-use rules or
prohibitions move, not when a footer or a date changes. We keep only "material" lines (money, numbers with
units, limit/permission/prohibition language) and diff those.

Stateless: we return a `fingerprint` token (compressed material lines). Pass it back as previous= next time and
get the exact lines added/removed. We store nothing. Deterministic, no AI calls, one request.
"""
import base64
import hashlib
import re
import time
import zlib

import business_facts as bf
from checker import visible_text

VERSION = "0.1.0"
MONEY = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:usd|usdc|eur|cents?)\b)", re.I)
UNIT = re.compile(r"\b\d[\d,]*(?:\.\d+)?\s?(?:k|m)?\s?(?:requests?|calls?|req|rpm|rps|tpm|tokens?|credits?|queries|"
                  r"messages?|seats?|users?|gb|mb|tb|minutes?|hours?|days?|months?|%|percent)\b"
                  r"|\bper (?:second|minute|hour|day|month|request|call|user|seat)\b|/\s?(?:mo|month|min|day|sec|hr)\b", re.I)
WORDS = re.compile(r"\b(prohibit\w*|not permitted|may not|must not|shall not|forbidden|restrict\w*|commercial use|"
                   r"non-commercial|attribution|licen[cs]e\w*|rate.?limit\w*|quota|throttl\w*|overage|refund\w*|"
                   r"terminat\w*|suspend\w*|liabilit\w*|indemnif\w*|warrant\w*|free tier|pricing|price[sd]?|fees?|"
                   r"billing|billed|charge[sd]?|subscription|trial|cancel\w*|resell\w*|scrap\w*|train(?:ing)? (?:on|data)|"
                   r"retention|retain\w*|data (?:use|usage|sharing))\b", re.I)
UPDATED = re.compile(r"\b(?:last (?:updated|modified|revised)|effective(?: date| as of)?)\s*[:\-]?\s*([A-Z][a-z]+\.? \d{1,2},? \d{4}|"
                     r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})", re.I)
MAX_LINES = 120


def _lines(page):
    text = visible_text(page)
    parts = re.split(r"(?<=[.!?])\s+|\n+|\s{2,}|\s[|•·]\s", text)
    out, seen = [], set()
    for p in parts:
        p = " ".join(p.split())
        if not (12 <= len(p) <= 400):
            continue
        if not (MONEY.search(p) or UNIT.search(p) or WORDS.search(p)):
            continue
        k = p.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= MAX_LINES:
            break
    return out


def _encode(lines, updated):
    blob = zlib.compress(("\n".join([updated or ""] + lines)).encode("utf-8"), 9)
    return "tc1." + base64.urlsafe_b64encode(blob).decode().rstrip("=")


def _decode(tok):
    if not tok or not tok.startswith("tc1."):
        return None
    b = tok[4:]
    try:
        raw = zlib.decompress(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))).decode("utf-8").split("\n")
    except Exception:
        return None
    return raw[0] or None, [l for l in raw[1:] if l]


def check(url, previous=None):
    t0 = time.time()
    if not re.match(r"^https?://", url or "", re.I):
        url = "https://" + (url or "")
    out = {"url": url, "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    prev = _decode(previous) if previous else None
    if previous and prev is None:
        return {**out, "state": "ERROR", "error": "previous must be a fingerprint returned by this service (tc1.…)"}
    r = bf._fetch(url)
    if not r.get("ok"):
        state = "BLOCKED" if r.get("blocked_by") or r.get("status") == 429 else \
            "GONE" if r.get("status") in (404, 410) else "UNKNOWN"
        return {**out, "state": state, "http_status": r.get("status"), "blocked_by": r.get("blocked_by"),
                "note": "couldn't read the page; never reported as UNCHANGED"}
    lines = _lines(r["text"])
    m = UPDATED.search(" ".join(visible_text(r["text"]).split()))
    updated = m.group(1) if m else None
    fp = _encode(lines, updated)
    base = {**out, "final_url": r["url"], "material_lines": len(lines), "last_updated_stated": updated,
            "fingerprint": fp, "digest": hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16],
            "cost": {"seconds": round(time.time() - t0, 2)}}
    if len(lines) < 3 and len(visible_text(r["text"])) < 400:
        base["note"] = "very little readable text (page may load its content with JavaScript)"
    if prev is None:
        return {**base, "state": "NEW", "sample": lines[:12]}
    p_updated, p_lines = prev
    old, new = set(p_lines), set(lines)
    added = [l for l in lines if l not in old]
    removed = [l for l in p_lines if l not in new]
    money_moved = any(MONEY.search(l) for l in added + removed)
    if not added and not removed:
        return {**base, "state": "UNCHANGED", "stated_date_changed": updated != p_updated,
                "note": "no material line changed" + ("; only the stated 'last updated' date moved" if updated != p_updated else "")}
    kinds = sorted({k for l in added + removed for k, rx in (("money", MONEY), ("limits", UNIT), ("terms", WORDS)) if rx.search(l)})
    return {**base, "state": "CHANGED", "kinds": kinds, "money_changed": money_moved, "added": added[:40],
            "removed": removed[:40], "stated_date_changed": updated != p_updated,
            "previous_last_updated": p_updated}
