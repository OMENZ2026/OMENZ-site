"""Lead-list website check (local build, not published): is this business's website alive, still theirs, readable?

    python products/agent_ready_checker/site_check.py https://example.com ["Business Name"]

Founder approval 2026-10-20 ("approve the build"): local build + frozen holdout only.
Publishing/pricing on Apify needs a separate founder yes (sug-apify-lead-list-hygiene-tool-20261019).

One URL in (optionally with the business name from the lead list), one row out:
  status            live | redirected_offsite | parked | hijacked_spam | blocked_by_bot_protection |
                    rate_limited | http_error | dead | invalid_url
  blocked_by        cloudflare / sucuri / ... when status is blocked_by_bot_protection
  js_only           True when the page has almost no readable text without running JavaScript
  placeholder_name  site-builder placeholder left in the site's own name data ("Your Site Title")
  name_found        when a business name is given: does it appear on the page (None if not checked)
  phone             first phone on the site (homepage, then a contact page if the homepage has none)

Deterministic, stdlib only, no AI calls, at most 2 requests per site. Honest crawler UA; bot protection is
reported, never bypassed. Status labels describe what an automated reader gets, not what a person in a
browser would see.

0.1.3 (founder OK 2026-10-23): name check matches the core of long listing names; "reserved for strategic use"-style
holding pages count as parked. Production stays 0.1.0 until a version passes the full gate.

0.1.2 (founder OK 2026-10-23): parked = "X.com for sale", JS redirect to a parking lander, domain-only page,
landing on a domain marketplace; accent folding in the name check (Café). Production stays 0.1.0 until this passes.

0.1.1 (founder build OK 2026-10-20): next_action per site (proceed | use_variant | needs_browser | retry_once |
wait | stop | skip); tls_error status with the reason; when the given URL fails, try the www/bare and http
variants and return working_variant; "Home Page" is no longer flagged as a placeholder. Up to ~5 requests
when the given URL fails.
"""
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import unicodedata
import urllib.request

import business_facts as bf
import conflicts_v006 as c6
from checker import visible_text
from conflicts_prototype import PHONE_RE, _norm_phone

VERSION = "0.1.3-local"
NAME_FILLER = ("the", "and", "inc", "llc", "restaurant", "company", "shop", "store", "co")
PARKING_HOSTS = ("hugedomains.com", "venture.com", "afternic.com", "dan.com", "sedo.com", "atom.com", "undeveloped.com",
                 "bodis.com", "parkingcrew.net", "above.com", "namecheap.com", "domainmarket.com", "brandbucket.com")
JS_LANDER = re.compile(r"location(?:\.href)?\s*=\s*[\"']/?(?:lander|parking|park|sale|forsale)\b", re.I)
NOT_PLACEHOLDER = re.compile(r"^(home ?page)$", re.I)  # generic, not a site-builder leftover (Book Passage)
GOOD = ("live",)
PARKED = re.compile(r"domain (name )?(is|may be) for sale|\b[\w-]+\.(com|net|org|co|us|biz|info) is for sale|"
                    r"\b[\w-]+\.(com|net|org|co|us|biz|info) for sale\b|find your domain name|"
                    r"domain for sale|buy this domain|this domain is parked|parked free|"
                    r"reserved for strategic use|open to (qualified )?inquiries|premium domain|"
                    r"this domain (name )?(is|has been) reserved|"
                    r"domain parking|hugedomains|afternic|sedo(parking)?\.com|dan\.com|parkingcrew|bodis\.com|"
                    r"undeveloped\.com|is available for purchase|inquire about this domain|"
                    r"this (web)?site is (currently )?(under construction|coming soon)|"
                    r"account (has been )?suspended|website (is )?(expired|suspended)|renew (your|this) domain", re.I)
SPAM = re.compile(r"\b(slot ?gacor|slot online|situs slot|judi|togel|bandar|maxwin|deposit pulsa|casino online|"
                  r"poker online|sbobet|pragmatic play|viagra|cialis|porn|xxx|escort|bokep|sabung ayam|"
                  r"replica watches|payday loans?)\b", re.I)
CONTACT_HREFS = [re.compile(r"<a[^>]+href=[\"']([^\"'#]*{}[^\"'#]*)[\"']".format(w), re.I)
                 for w in ("contact", "visit", "location", "about")]


def _domain(u):
    h = (urllib.parse.urlparse(u).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _site(h):
    parts = h.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def _title(page):
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    return " ".join(c6._clean(m.group(1)).split())[:200] if m else None


def _phone(page):
    for m in re.finditer(r"href=[\"']tel:([^\"']+)", page, re.I):
        pm = PHONE_RE.search(m.group(1))
        if pm:
            return _norm_phone(pm)
    text = c6._clean(visible_text(page))
    for m in PHONE_RE.finditer(text):
        if "fax" not in text[max(0, m.start() - 12):m.start()].lower():
            return _norm_phone(m)
    return None


def _fold(s):
    """Café -> Cafe (0.1.2: El Charro Café false negative)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _name_key(s):
    s = _fold(c6._clean(s)).lower().replace("&", " and ").replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def _parking_signal(raw_url, final_url, page, title, text):
    """Why this looks like a parked/for-sale page, else None (0.1.2 patterns from the 0.1.1 holdout misses)."""
    fh = _domain(final_url)
    if any(fh == h or fh.endswith("." + h) for h in PARKING_HOSTS):
        return "lands on a domain marketplace: " + fh
    if JS_LANDER.search(page) and len(text) < 200:
        return "JavaScript redirect to a parking lander"
    dom = _domain(raw_url)
    rest = re.sub(re.escape(dom), " ", (text or "").lower())
    rest = re.sub(re.escape(dom.split(".")[0]), " ", rest)
    if (title or "").strip().lower() in (dom, "www." + dom) and len(rest.strip(" .-|")) < 15:
        return "page shows only the domain name"
    return None


def _name_found(name, page):
    key = _name_key(name)
    hay = _name_key(visible_text(page) + " " + (_title(page) or ""))
    if not key:
        return None
    if key in hay:
        return True
    words = [w for w in key.split() if len(w) > 2 and w not in NAME_FILLER]
    if not words:
        return None
    hits = [w in hay for w in words]
    # 0.1.3: listing names carry extra words ("Peter Pan Donut & Pastry Shop" vs site "PETER PAN DONUTS"):
    # the core (first two distinctive words) must be there, plus at least 60% of all distinctive words.
    core = all(hits[:2])
    return core and sum(hits) >= 0.6 * len(words)


def _tls_problem(host):
    """Reason string when the HTTPS certificate is the problem, else None (one handshake, no HTTP)."""
    try:
        with socket.create_connection((host, 443), timeout=10) as s:
            with ssl.create_default_context().wrap_socket(s, server_hostname=host):
                return None
    except ssl.SSLCertVerificationError as e:
        msg = (getattr(e, "verify_message", None) or str(e)).lower()
        if "hostname" in msg or "not valid for" in msg:
            return "certificate does not match the hostname"
        if "expired" in msg:
            return "certificate expired"
        if "self" in msg and "signed" in msg:
            return "self-signed certificate"
        return "certificate not trusted"
    except ssl.SSLError:
        return "TLS handshake failed"
    except OSError:
        return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _dead_redirect(url):
    """Host of a redirect target that does not resolve, else None (one request, redirects not followed)."""
    try:
        urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url, headers=bf.HEADERS), timeout=15)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") if 300 <= e.code < 400 else None
        h = urllib.parse.urlparse(urllib.parse.urljoin(url, loc)).hostname if loc else None
        if h:
            try:
                socket.getaddrinfo(h, 443)
            except socket.gaierror:
                return h
    except Exception:
        pass
    return None


def _variants(raw):
    p = urllib.parse.urlparse(raw)
    h = p.hostname or ""
    other = h[4:] if h.startswith("www.") else "www." + h
    seen, out = {raw}, []
    for scheme, host in (("https", other), ("http", h), ("http", other)):
        u = "{}://{}{}".format(scheme, host, p.path or "/")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


NEXT = {"live": "proceed", "parked": "skip", "hijacked_spam": "skip", "redirected_offsite": "skip", "invalid_url": "skip",
        "blocked_by_bot_protection": "stop", "rate_limited": "wait", "tls_error": "stop"}


def _next_action(out):
    s = out["status"]
    if out.get("working_variant"):
        return "use_variant"
    if s == "live":
        return "needs_browser" if out.get("js_only") else "proceed"
    if s == "dead":
        hs = out.get("http_status")
        return "retry_once" if (not hs and any(n.startswith("no response") for n in out["notes"])) else "stop"
    if s == "http_error":
        return "retry_once" if (out.get("http_status") or 0) >= 500 else "stop"
    return NEXT.get(s, "stop")


def check(url, name=None):
    out = _check(url, name)
    if out["status"] not in GOOD and out["status"] not in ("invalid_url", "parked", "hijacked_spam", "redirected_offsite",
                                                           "blocked_by_bot_protection", "rate_limited"):
        raw = out["_raw"]
        for v in _variants(raw):  # e.g. www doesn't resolve but the bare domain works (Hattie's)
            if v.startswith("http://") and urllib.parse.urlparse(v).hostname == urllib.parse.urlparse(raw).hostname \
                    and any("HTTP answered" in n for n in out["notes"]):
                continue
            alt = _check(v, name, try_http=False)
            out["requests"] += alt["requests"]
            if alt["status"] == "live" and alt.get("name_found") is not False:
                out["working_variant"] = alt["final_url"] or v
                out["notes"].append("working variant: " + out["working_variant"])
                break
    out.pop("_raw", None)
    out["next_action"] = _next_action(out)
    return out


def _check(url, name=None, try_http=True):
    t0 = time.time()
    raw = (url or "").strip()
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    host = urllib.parse.urlparse(raw).hostname
    out = {"url": url, "version": VERSION, "status": None, "http_status": None, "final_url": None, "title": None,
           "blocked_by": None, "js_only": None, "placeholder_name": None, "name_given": name, "name_found": None,
           "phone": None, "notes": [], "requests": 0, "working_variant": None, "next_action": None, "_raw": raw}
    if not host or "." not in host or " " in host:
        out["status"] = "invalid_url"
        return _done(out, t0)
    r = bf._fetch(raw)
    out["requests"] += 1
    tls = None
    if not r.get("ok") and r.get("error") and raw.startswith("https://"):
        try:
            socket.getaddrinfo(host, 443)
        except socket.gaierror:
            out["status"], out["notes"] = "dead", ["domain does not resolve (DNS)"]
            return _done(out, t0)
        tls = _tls_problem(host)
        if tls:
            out["notes"].append("HTTPS problem: " + tls)
        else:
            gone = _dead_redirect(raw)
            out["requests"] += 1
            if gone:  # e.g. Camellia Grill: resolves, but redirects to a host that doesn't exist
                out["status"] = "dead"
                out["notes"].append("redirects to {}, which does not resolve (DNS)".format(gone))
                return _done(out, t0)
        if try_http:
            r2 = bf._fetch("http://" + raw[8:])  # some small-business sites still have no working HTTPS
            out["requests"] += 1
            if r2.get("ok") or r2.get("status"):
                r = r2
                out["notes"].append("HTTPS failed; HTTP answered")
    out["http_status"] = r.get("status")
    if not r.get("ok"):
        if tls and not r.get("status"):
            out["status"] = "tls_error"
        elif r.get("blocked_by"):
            out["status"], out["blocked_by"] = "blocked_by_bot_protection", r["blocked_by"]
        elif r.get("status") == 429:
            out["status"] = "rate_limited"
        elif r.get("status"):
            out["status"] = "dead" if r["status"] in (404, 410) else "http_error"
        else:
            out["status"], out["notes"] = "dead", out["notes"] + ["no response ({})".format(r.get("error"))]
        return _done(out, t0)

    page = r["text"]
    out["final_url"] = r["url"]
    out["title"] = _title(page)
    text = c6._clean(visible_text(page))
    sniff = (out["title"] or "") + " " + text[:4000]
    offsite = _site(_domain(r["url"])) != _site(_domain(raw))
    out["placeholder_name"] = ([p for p in bf._placeholders(page) if not NOT_PLACEHOLDER.match(p)] or [None])[0]
    out["js_only"] = len(text) < 200 and bool(re.search(r"<script", page, re.I))
    if SPAM.search(sniff):
        out["status"] = "hijacked_spam"
        out["notes"].append("spam content: '{}'".format(SPAM.search(sniff).group(0)))
    elif PARKED.search(sniff):
        out["status"] = "parked"
        out["notes"].append("parking/for-sale/suspended text: '{}'".format(PARKED.search(sniff).group(0)))
    elif _parking_signal(raw, r["url"], page, out["title"], text):
        out["status"] = "parked"
        out["notes"].append(_parking_signal(raw, r["url"], page, out["title"], text))
    else:
        out["status"] = "live"
    if out["status"] == "live":
        if name and not out["js_only"]:
            out["name_found"] = _name_found(name, page)
            if out["name_found"] is False:
                out["notes"].append("business name not found on the homepage")
        elif out["js_only"]:
            out["notes"].append("page needs JavaScript; content not checked")
        if offsite:
            out["moved_to"] = _domain(r["url"])
            if out["name_found"]:
                out["notes"].append("moved to its own new domain: " + out["moved_to"])
            else:  # a redirect to another domain we can't tie back to the business
                out["status"] = "redirected_offsite"
                out["notes"].append("ends on a different domain: " + out["moved_to"])
        out["phone"] = _phone(page)
        if not out["phone"]:
            for rx in CONTACT_HREFS:
                m = rx.search(page)
                if not m:
                    continue
                cu = urllib.parse.urljoin(r["url"], m.group(1))
                if _site(_domain(cu)) == _site(_domain(r["url"])):
                    r3 = bf._fetch(cu)
                    out["requests"] += 1
                    if r3.get("ok"):
                        out["phone"] = _phone(r3["text"])
                break
    return _done(out, t0)


def _done(out, t0):
    out["seconds"] = round(time.time() - t0, 2)
    out["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(check(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), indent=2, ensure_ascii=False))
