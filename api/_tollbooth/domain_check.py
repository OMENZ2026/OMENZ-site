"""OMENZ Domain Check: who is behind this domain, and should my agent trust it? (2026-11-22)

Evidence: an x402 DNS/WHOIS/RDAP service had 44 paying wallets at ~60 calls each, growing week over week. OMENZ's version
answers the trust question an agent actually has before paying or emailing: how old is the domain, does it really resolve,
can it send/receive mail properly, is it set up like a real business or a throwaway?
Public data only, no keys: RDAP (registration) via rdap.org, DNS via Cloudflare DNS-over-HTTPS.

  RED_FLAGS   not registered / not resolving, or registered < 30 days ago
  CAUTION     < 180 days old, expiring within 30 days, no MX, no SPF or no DMARC, registration hidden status flags
  LOOKS_ESTABLISHED  none of the above
"""
import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request

VERSION = "0.1.0"
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "OMENZ Domain Check", **(headers or {})})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout)), None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, type(e).__name__


def _dns(name, rtype):
    d, err = _json(f"https://cloudflare-dns.com/dns-query?name={urllib.parse.quote(name)}&type={rtype}", {"accept": "application/dns-json"}, 8)
    if d is None:
        return None
    return [a.get("data", "").strip('"') for a in d.get("Answer") or [] if a.get("type") in (1, 2, 5, 15, 16, 28)]


def _norm(domain):
    d = str(domain or "").strip().lower()
    if "://" in d:
        d = urllib.parse.urlparse(d).hostname or ""
    d = d.split("/")[0].split(":")[0].rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    return d


SECOND_LEVEL = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "co.in", "com.br",
                "com.mx", "co.za", "com.cn", "com.tw", "com.hk", "com.sg", "co.kr", "com.ar", "com.tr", "co.il", "com.co"}


def _registrable(host):
    """eTLD+1 (best effort): api.exa.ai -> exa.ai, shop.example.co.uk -> example.co.uk."""
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def check(domain):
    out = {"service": "OMENZ Domain Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    d = _norm(domain)
    if not DOMAIN_RE.match(d):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["send a domain like example.com (a URL is fine too)"]}
    base = _registrable(d)
    out["domain"] = d
    if base != d:
        out["registered_domain"] = base
    red, caution, passed = [], [], []
    rd, rerr = _json(f"https://rdap.org/domain/{base}", timeout=12)
    reg = {}
    if rd is None and rerr == 404:
        red.append("domain is not registered (RDAP 404)")
    elif rd is None:
        caution.append(f"registration record unavailable ({rerr}); some country domains have no public RDAP")
    else:
        ev = {e.get("eventAction"): e.get("eventDate") for e in rd.get("events") or []}
        reg = {"registered": ev.get("registration"), "expires": ev.get("expiration"), "last_changed": ev.get("last changed"),
               "status": rd.get("status") or []}
        for ent in rd.get("entities") or []:
            if "registrar" in (ent.get("roles") or []):
                v = ent.get("vcardArray") or []
                fn = next((x[3] for x in (v[1] if len(v) > 1 else []) if x and x[0] == "fn"), None)
                reg["registrar"] = fn
        now = dt.datetime.now(dt.timezone.utc)
        if reg.get("registered"):
            age = (now - dt.datetime.fromisoformat(reg["registered"].replace("Z", "+00:00"))).days
            reg["age_days"] = age
            if age < 30:
                red.append(f"domain registered only {age} days ago (most scam and phishing domains are this new)")
            elif age < 180:
                caution.append(f"domain is {age} days old (young)")
            else:
                passed.append(f"domain registered {age // 365} years {age % 365} days ago")
        if reg.get("expires"):
            left = (dt.datetime.fromisoformat(reg["expires"].replace("Z", "+00:00")) - now).days
            reg["expires_in_days"] = left
            if left < 30:
                caution.append(f"registration expires in {left} days")
        bad = [s for s in reg["status"] if any(k in s.lower() for k in ("hold", "redemption", "pending delete"))]
        if bad:
            red.append("registry status: " + ", ".join(bad))
    out["registration"] = reg
    a = _dns(d, "A") or []
    aaaa = _dns(d, "AAAA") or []
    mx = _dns(base, "MX")
    txt = _dns(base, "TXT") or []
    dmarc = _dns("_dmarc." + base, "TXT") or []
    ns = _dns(base, "NS") or []
    out["dns"] = {"a": a[:5], "aaaa": aaaa[:3], "mx": (mx or [])[:5], "ns": ns[:5],
                  "spf": next((t for t in txt if t.lower().startswith("v=spf1")), None),
                  "dmarc": next((t for t in dmarc if t.lower().startswith("v=dmarc1")), None)}
    if not a and not aaaa and "not registered" not in " ".join(red):
        red.append(f"{d} does not resolve to any address (no A/AAAA records)" + (f" (the registered domain {base} exists; check the exact host)" if base != d else ""))
    elif a or aaaa:
        passed.append("resolves (A/AAAA records present)")
    unregistered = any("not registered" in r for r in red)
    if unregistered:
        pass  # mail checks are noise for a domain that does not exist
    elif mx is not None and not mx:
        caution.append("no MX records: this domain cannot receive email")
    elif mx:
        passed.append("receives email (MX present)")
    if not unregistered and not out["dns"]["spf"]:
        caution.append("no SPF record: anyone can send email pretending to be this domain")
    if unregistered:
        pass
    elif not out["dns"]["dmarc"]:
        caution.append("no DMARC record: spoofed email from this domain is not rejected")
    elif "p=reject" in out["dns"]["dmarc"].lower() or "p=quarantine" in out["dns"]["dmarc"].lower():
        passed.append("DMARC enforced (spoofed mail rejected/quarantined)")
    verdict = "RED_FLAGS" if red else "CAUTION" if caution else "LOOKS_ESTABLISHED"
    return {**out, "verdict": verdict, "red_flags": red, "caution": caution, "passed": passed,
            "sources": ["rdap.org (registries)", "Cloudflare DNS-over-HTTPS"],
            "limits": "Registration and DNS facts only: an old, well-configured domain can still be compromised. Pair with Authorize before paying.",
            "next": {"LOOKS_ESTABLISHED": "domain looks like an established operation", "CAUTION": "read the cautions before trusting payments or email",
                     "RED_FLAGS": "do not pay or send credentials to this domain"}[verdict]}
