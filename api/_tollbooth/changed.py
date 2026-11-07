"""Changed? (local build, not published): has this page MATERIALLY changed since my last fetch?

    python products/agent_ready_checker/changed.py https://example.com [previous_fingerprint]

Founder approval 2026-10-23 ("approve the Changed? build"): local build + baseline snapshot + frozen time-separated
holdout. Publishing/pricing needs a separate founder yes (sug-apify-changed-tollbooth-20261020).

Stateless: the caller keeps the `fingerprint` we return and passes it back next time; we store nothing.
State:
  NEW        no previous fingerprint given (baseline taken)
  UNCHANGED  same destination, same normalized content and metadata (or the server answered 304)
  CHANGED    change_type: content | metadata | destination (same site, different final page)
             change_size: share of text blocks added or removed (0-1)
  REDIRECTED now ends on a different site than before
  GONE       dead (DNS / 404 / 410), parked/for sale, or taken over by spam
  BLOCKED    bot protection or rate limit: we can't see it, so we don't guess
  UNKNOWN    timeout / server error / TLS failure: try again later; never reported as UNCHANGED

The value is the normalization: timestamps, "x minutes ago", copyright years, open/closed-now badges, counters and
script/style churn are ignored, so a dynamic-but-same page reports UNCHANGED. Prices, menus, hours text, addresses
and new/removed paragraphs are NOT normalized away. When unsure, it leans to CHANGED (a false UNCHANGED is the
expensive mistake). Deterministic, stdlib only, no AI calls, 1 request (often a 304).
"""
import base64
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import business_facts as bf
import conflicts_v006 as c6
import site_check as sc
from checker import visible_text

VERSION = "0.1.1-local"
# 0.1.1 (founder OK 2026-10-27): (1) a JavaScript shell (almost no readable text) is UNKNOWN / needs a browser,
# never compared (Reddit false UNCHANGED in the 0.1.0 holdout); (2) clock times are KEPT on opening-hours lines
# (days, hours, open/close, brunch/lunch/dinner, or a time range) and stripped only as timestamps.
HOURS_CTX = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun|daily|weekdays?|weekends?|hours|open|opens|close|closes|closed|"
                       r"brunch|lunch|dinner|breakfast|happy hour|kitchen)\b|"
                       r"\d{1,2}(:\d{2})?\s*([ap]\.?m\.?)?\s*(-|–|to)\s*\d{1,2}(:\d{2})?\s*[ap]\.?m\.?", re.I)
TIMESTAMP_CTX = re.compile(r"\b(updated|posted|published|edited|modified|as of|last)\b", re.I)
SHELL_TEXT_MAX = 200
MONTHS = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DAYS = r"(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?"
NOISE = [
    re.compile(r"(©|&copy;|\(c\)|copyright)\s*(\d{4}\s*[-–]\s*)?\d{4}", re.I),                    # © 2019-2026
    re.compile(r"\b\d{4}-\d{2}-\d{2}([t ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(z|[+-]\d{2}:?\d{2})?)?\b", re.I),  # ISO dates
    re.compile(r"\b" + DAYS + r",?\s+" + MONTHS + r"\s+\d{1,2}(,?\s+\d{4})?", re.I),              # Thu, Oct 23, 2026
    re.compile(r"\b" + MONTHS + r"\s+\d{1,2},?\s+\d{4}(\s+(at\s+)?\d{1,2}:\d{2}\s*([ap]\.?m\.?)?)?", re.I),  # Oct 23, 2026
    re.compile(r"\b\d{1,2}\s+" + MONTHS + r"\s+\d{4}\b", re.I),                                    # 23 Oct 2026
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),                                                     # 10/23/2026
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*([ap]\.?m\.?)?\s*([a-z]{2,4}t\b)?", re.I),              # 4:05 pm PDT
    re.compile(r"\b(\d+|an?|one)\s+(second|sec|minute|min|hour|hr|day|week|month|year)s?\s+ago\b", re.I),
    re.compile(r"\b(just now|yesterday|today|tonight|updated\s+\w+\s+ago)\b", re.I),
    re.compile(r"\b(open now|closed now|opens? (at|in)\s+\S+|closes? (at|in)\s+\S+|open 24 hours)\b", re.I),
    re.compile(r"\b\d[\d,.]*\s*k?\s+(views?|likes?|comments?|shares?|people (are )?(viewing|watching)|in cart|sold|"
               r"stars?( today| this week)?|points?|votes?|upvotes?|forks?|followers?|subscribers?|downloads?|reviews?|ratings?)\b", re.I),
    re.compile(r"\b(loading|please wait)\.{0,3}", re.I),
]
CLOCK = NOISE[6]  # the clock-time pattern
assert CLOCK.pattern.startswith(r"\b\d{1,2}:\d{2}")
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|_ga|sessionid|sid$|session)", re.I)


def _norm_url(u):
    p = urllib.parse.urlparse(u or "")
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not TRACKING.match(k)]
    host = (p.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return "{}{}{}".format(host, (p.path or "/").rstrip("/") or "/", ("?" + urllib.parse.urlencode(sorted(q))) if q else "")


def _blocks(page):
    """Normalized text blocks: one per block-level element / line, noise removed, short fragments dropped."""
    t = re.sub(r"<(script|style|noscript|template|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<(br|/p|/div|/li|/h\d|/tr|/section|/article|/td|/dd|/dt|/header|/footer|/nav)[^>]*>", "\n", t, flags=re.I)
    t = c6._clean(re.sub(r"<[^>]+>", " ", t))
    out = []
    for line in t.split("\n"):
        line = " ".join(line.split()).lower()
        keep_times = bool(HOURS_CTX.search(line)) and not TIMESTAMP_CTX.search(line)
        for rx in NOISE:
            if rx is CLOCK and keep_times:
                continue  # opening hours are material: "7:00am - 3:00pm" must not vanish
            line = rx.sub(" ", line)
        line = " ".join(line.split())
        if re.fullmatch(r"[\d,.\s+k%-]*", line):  # a block that is only a number is a counter ("8,206"); "$8.20" is kept
            continue
        if len(re.sub(r"[^a-z0-9$]", "", line)) >= 3:
            out.append(line)
    return out


def _meta(page):
    def grab(rx):
        m = re.search(rx, page, re.I | re.S)
        return " ".join(c6._clean(m.group(1)).split()) if m else ""
    parts = [grab(r"<title[^>]*>(.*?)</title>"),
             grab(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']*)"),
             grab(r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']*)")]
    parts = [p for p in parts]
    for rx in NOISE:
        parts = [rx.sub(" ", p) for p in parts]
    return " | ".join(" ".join(p.lower().split()) for p in parts)


def _h(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _block_hashes(blocks):
    return sorted({hashlib.sha1(b.encode("utf-8")).hexdigest()[:8] for b in blocks})


def _encode(fp):
    return base64.urlsafe_b64encode(json.dumps(fp, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode(token):
    if not token:
        return None
    if isinstance(token, dict):
        return token
    try:
        return json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode())
    except Exception:
        return None


def _conditional_fetch(url, prev):
    """Fetch with If-None-Match / If-Modified-Since from the previous fingerprint. Returns (result, was_304)."""
    headers = dict(bf.HEADERS)
    if prev and prev.get("etag"):
        headers["If-None-Match"] = prev["etag"]
    if prev and prev.get("lm"):
        headers["If-Modified-Since"] = prev["lm"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(3_000_000)
            return ({"ok": True, "status": r.status, "url": r.geturl(),
                     "text": bf._decode(body, r.headers.get_content_charset() or "utf-8"),
                     "ctype": r.headers.get("Content-Type", ""), "etag": r.headers.get("ETag"),
                     "lm": r.headers.get("Last-Modified")}, False)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return ({"ok": True, "status": 304, "url": url, "text": "", "ctype": "", "etag": e.headers.get("ETag"),
                     "lm": e.headers.get("Last-Modified")}, True)
        return ({"ok": False, "status": e.code}, False)
    except Exception as e:
        return ({"ok": False, "status": None, "error": type(e).__name__, "detail": str(e)[:120]}, False)


def check(url, previous=None):
    t0 = time.time()
    prev = _decode(previous)
    raw = (url or "").strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    out = {"url": url, "version": VERSION, "state": None, "change_type": None, "change_size": None,
           "content_type": None, "observed_last_modified": None, "final_url": None, "reason": None,
           "fingerprint": None, "requests": 1}
    r, was_304 = _conditional_fetch(raw, prev)
    if not r.get("ok") and (r.get("error") in ("TimeoutError", "timeout") or "timed out" in (r.get("detail") or "")):
        out["state"], out["reason"] = "UNKNOWN", "timed out; try again later"  # fast: no variant search on a timeout
        if prev:
            out["fingerprint"] = _encode(prev)
        return _done(out, t0)
    if not r.get("ok"):
        # classify the failure with the Lead List checker (same honest UA, same labels)
        s = sc.check(raw)
        out["requests"] += s["requests"]
        st = s["status"]
        if st in ("dead", "parked", "hijacked_spam", "invalid_url") and s["next_action"] != "retry_once":
            out["state"], out["reason"] = "GONE", st + ("; " + "; ".join(s["notes"]) if s["notes"] else "")
        elif st in ("blocked_by_bot_protection", "rate_limited"):
            out["state"], out["reason"] = "BLOCKED", st + (" by " + s["blocked_by"] if s.get("blocked_by") else "")
        elif st == "live" and s.get("final_url"):
            r = bf._fetch(s["final_url"])  # conditional request was refused but a plain one works
            out["requests"] += 1
        else:
            out["state"], out["reason"] = "UNKNOWN", st + ("; " + "; ".join(s["notes"]) if s["notes"] else "")
        if out["state"]:
            if prev:
                out["fingerprint"] = _encode(prev)  # keep the last good baseline
            return _done(out, t0)

    if was_304 and prev:
        out.update(state="UNCHANGED", reason="server says not modified (304)", final_url=prev.get("u"),
                   content_type=prev.get("ct"), observed_last_modified=r.get("lm") or prev.get("lm"))
        out["fingerprint"] = _encode(prev)
        return _done(out, t0)

    page = r["text"]
    out["final_url"] = r["url"]
    out["content_type"] = (r.get("ctype") or "").split(";")[0].strip() or None
    out["observed_last_modified"] = r.get("lm")
    title = sc._title(page)
    text = c6._clean(visible_text(page))
    sniff = (title or "") + " " + text[:4000]
    if sc.SPAM.search(sniff) or sc.PARKED.search(sniff) or sc._parking_signal(raw, r["url"], page, title, text):
        why = "spam" if sc.SPAM.search(sniff) else "parked/for sale"
        out["state"], out["reason"] = "GONE", why
        if prev:
            out["fingerprint"] = _encode(prev)
        return _done(out, t0)

    is_html = (out["content_type"] or "text/html").startswith("text/html")
    if is_html and len(text) < SHELL_TEXT_MAX and re.search(r"<script", page, re.I):
        out["state"] = "UNKNOWN"
        out["reason"] = "page needs a browser (JavaScript shell; only %d characters readable), so change can't be judged" % len(text)
        if prev:
            out["fingerprint"] = _encode(prev)  # keep the last good baseline
        return _done(out, t0)

    blocks = _blocks(page)
    fp = {"v": 1, "u": r["url"], "nu": _norm_url(r["url"]), "site": sc._site(sc._domain(r["url"])),
          "c": _h("\n".join(blocks)), "m": _h(_meta(page)), "b": _block_hashes(blocks), "ct": out["content_type"],
          "etag": r.get("etag"), "lm": r.get("lm"), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if len(fp["b"]) > 400:  # keep the token small; sampled blocks still show size of change
        fp["b"] = fp["b"][::max(1, len(fp["b"]) // 400)]
    out["fingerprint"] = _encode(fp)
    if not prev:
        out["state"] = "NEW"
        return _done(out, t0)
    if prev.get("site") and fp["site"] != prev.get("site"):
        out.update(state="REDIRECTED", reason="now ends on {} (was {})".format(fp["site"], prev.get("site")))
        return _done(out, t0)
    a, b = set(prev.get("b") or []), set(fp["b"])
    size = round(len(a ^ b) / max(1, len(a | b)), 3)
    if fp["nu"] != prev.get("nu"):
        out.update(state="CHANGED", change_type="destination", change_size=size,
                   reason="same site, different final page: " + fp["nu"])
    elif fp["c"] != prev.get("c"):
        out.update(state="CHANGED", change_type="content", change_size=size if size > 0 else 0.001)
    elif fp["m"] != prev.get("m"):
        out.update(state="CHANGED", change_type="metadata", change_size=0.0)
    else:
        out["state"] = "UNCHANGED"
    return _done(out, t0)


def _done(out, t0):
    out["seconds"] = round(time.time() - t0, 2)
    out["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), indent=2, ensure_ascii=False))
