"""OMENZ Link Check: where does this link really go, and is it safe to follow or pay? (2026-11-22)

Evidence (11-22 category scan): URL unshorten/redirect services 132 paying wallets, TLS-certificate checks 164.
Follows the redirect chain hop by hop (max 10, GET-free: HEAD with GET fallback, no cookies), then checks the final
host's TLS certificate (issuer, days to expiry, hostname match) and the final domain's age (RDAP via Domain Check).

  DANGER   cert invalid/expired/hostname mismatch, redirect loop, or final domain registered < 30 days ago
  CAUTION  lands on a different registered domain than the link shows, passes through a URL shortener, plain http,
           cert expiring < 14 days, > 4 redirects, or final page errors (4xx/5xx)
  UNREACHABLE  destination did not load (down or blocking) and nothing worse was found
  OK       none of the above
Never submits forms, never runs scripts, never pays.
"""
import datetime as dt
import socket
import ssl
import time
import urllib.parse
import urllib.request

import domain_check

VERSION = "0.2.0"
SHORTENERS = {"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at",
              "t.ly", "rb.gy", "tiny.cc", "lnkd.in", "s.id", "bl.ink", "short.io", "trib.al", "dlvr.it", "amzn.to", "youtu.be"}


def _ctx():
    try:
        import certifi  # ships with httpx; full CA bundle incl. intermediates' roots
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_LAST_HEADERS = {}
SEC_HEADERS = {"strict-transport-security": "HSTS (forces https)", "content-security-policy": "CSP (limits injected scripts)",
               "x-frame-options": "clickjacking protection", "x-content-type-options": "MIME-sniffing protection",
               "referrer-policy": "referrer policy"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _public(host):
    """SSRF guard: every address the host resolves to must be public internet."""
    import ipaddress
    try:
        addrs = {i[4][0] for i in socket.getaddrinfo(host, None)}
    except Exception:
        return None
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _hop(url, opener):
    host = urllib.parse.urlparse(url).hostname or ""
    pub = _public(host)
    if pub is False:
        return None, "error:BlockedPrivateAddress"
    if pub is None:
        return None, "error:DNSNotFound"
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0 (compatible; OMENZ-LinkCheck/0.1)"})
        try:
            r = opener.open(req, timeout=8)
            _LAST_HEADERS[url] = {k.lower(): v for k, v in r.headers.items()}
            return r.status, r.headers.get("Location")
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (405, 403, 501):
                continue
            return e.code, e.headers.get("Location")
        except Exception as e:
            return None, f"error:{type(e).__name__}"
    return None, None


def _cert(host, port=443):
    ctx = _ctx()
    try:
        with socket.create_connection((host, port), timeout=6) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                c = s.getpeercert()
        exp = dt.datetime.strptime(c["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
        issuer = dict(x[0] for x in c.get("issuer", ())).get("organizationName")
        return {"valid": True, "issuer": issuer, "expires": exp.strftime("%Y-%m-%d"),
                "days_left": (exp - dt.datetime.now(dt.timezone.utc)).days}
    except ssl.SSLCertVerificationError as e:
        return {"valid": False, "error": str(e.verify_message or e)[:120]}
    except Exception as e:
        return {"valid": None, "error": type(e).__name__}


def check(url):
    out = {"service": "OMENZ Link Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "never_submits_or_pays": True}
    u = str(url or "").strip()
    if u and "://" not in u:
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or len(u) > 2000 or " " in u or not domain_check.DOMAIN_RE.match(p.hostname.lower()):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["send an http(s) URL"]}
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=_ctx()))
    chain, seen, cur, loop = [], set(), u, False
    for _ in range(10):
        if cur in seen:
            loop = True
            break
        seen.add(cur)
        status, loc = _hop(cur, opener)
        chain.append({"url": cur[:300], "status": status})
        if status in (301, 302, 303, 307, 308) and loc and not str(loc).startswith("error:"):
            cur = urllib.parse.urljoin(cur, loc)
            continue
        if loc and str(loc).startswith("error:"):
            chain[-1]["error"] = loc[6:]
        break
    final = cur
    fp = urllib.parse.urlparse(final)
    start_dom, final_dom = domain_check._registrable(p.hostname.lower()), domain_check._registrable((fp.hostname or "").lower())
    danger, caution, passed = [], [], []
    if loop:
        danger.append("redirect loop")
    last = chain[-1]
    load_failed = bool(last.get("error"))
    if last.get("error") == "BlockedPrivateAddress":
        danger.append("link points to a private/internal network address: refused")
    elif load_failed:
        caution.append(f"destination did not load ({last['error']})")
    elif last["status"] and last["status"] >= 400:
        caution.append(f"final page answers {last['status']}")
    elif last["status"]:
        passed.append(f"final page answers {last['status']}")
    hops = len(chain) - 1
    if hops > 4:
        caution.append(f"{hops} redirects before the destination")
    if any(domain_check._registrable(urllib.parse.urlparse(h["url"]).hostname or "") in SHORTENERS or (urllib.parse.urlparse(h["url"]).hostname or "") in SHORTENERS for h in chain):
        caution.append("passes through a URL shortener (hides the real destination)")
    if final_dom and final_dom != start_dom:
        caution.append(f"lands on a different site ({final_dom}) than the link shows ({start_dom})")
    cert = None
    if fp.scheme == "http":
        caution.append("final page is plain http (no encryption)")
    elif fp.hostname and not load_failed or (fp.hostname and last.get("error") not in ("BlockedPrivateAddress", "DNSNotFound")):
        cert = _cert(fp.hostname, fp.port or 443)
        if cert.get("valid") is False:
            danger.append(f"TLS certificate invalid: {cert.get('error')}")
        elif cert.get("valid"):
            if cert["days_left"] < 0:
                danger.append("TLS certificate expired")
            elif cert["days_left"] < 14:
                caution.append(f"TLS certificate expires in {cert['days_left']} days")
            else:
                passed.append(f"valid TLS certificate ({cert.get('issuer')}, {cert['days_left']} days left)")
    age = None
    if final_dom:
        rd, _ = domain_check._json(f"https://rdap.org/domain/{final_dom}", timeout=5)
        reg = next((e.get("eventDate") for e in (rd or {}).get("events") or [] if e.get("eventAction") == "registration"), None)
        if reg:
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(reg.replace("Z", "+00:00"))).days
            if age < 30:
                danger.append(f"destination domain {final_dom} was registered only {age} days ago")
            else:
                passed.append(f"destination domain {age} days old")
    if load_failed and danger:  # the TLS/age reason already explains the failure
        caution = [c for c in caution if not c.startswith("destination did not load")]
    hdr = _LAST_HEADERS.pop(final, None)
    _LAST_HEADERS.clear()
    sec = None
    if hdr is not None and not load_failed:
        present = [v for k, v in SEC_HEADERS.items() if k in hdr or (k == "x-frame-options" and "frame-ancestors" in hdr.get("content-security-policy", ""))]
        missing = [v for k, v in SEC_HEADERS.items() if v not in present]
        sec = {"present": present, "missing": missing, "score": f"{len(present)}/{len(SEC_HEADERS)}", "server": hdr.get("server")}
        if fp.scheme == "https" and "strict-transport-security" not in hdr and not danger:
            passed.append("note: no HSTS header (browsers may be downgraded to http on first visit)")
    verdict = "DANGER" if danger else "UNREACHABLE" if load_failed else "CAUTION" if caution else "OK"
    return {**out, "input": u, "final_url": final[:500], "redirects": hops, "chain": chain, "final_domain": final_dom,
            "final_domain_age_days": age, "tls": cert, "security_headers": sec, "verdict": verdict, "danger": danger, "caution": caution, "passed": passed,
            "limits": "Checks the route and the destination's setup, not page content. A legitimate-looking page can still be a scam.",
            "next": {"OK": "safe to follow", "CAUTION": "check the cautions before clicking, signing in or paying",
                     "DANGER": "do not follow, sign in or pay", "UNREACHABLE": "destination is down or blocking checks; retry later before trusting it"}[verdict]}
