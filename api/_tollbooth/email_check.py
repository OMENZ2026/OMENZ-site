"""OMENZ Email Check: is this email address real enough to use? (2026-11-22)

Evidence: x402 email-verification services had 91 paying wallets (~4 calls each) in the 11-22 category scan; pairs with
Phone Check for agents handling leads, signups and outreach. Deterministic, public DNS only (Cloudflare DNS-over-HTTPS,
shared with Domain Check). No SMTP probing (unreliable from serverless and intrusive to the mailbox owner); nothing stored.

  UNDELIVERABLE  bad syntax, domain does not exist, or no mail server (no MX and no A fallback)
  RISKY          disposable/throwaway provider, or a domain with no SPF and no DMARC (easy to spoof)
  DELIVERABLE_LIKELY  syntax ok + domain receives mail
Also reports: free webmail vs business domain, role account (info@, sales@...), plus-addressing, normalized form.
"""
import re
import time

import domain_check

VERSION = "0.1.0"
LOCAL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$")
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "10minutemail.com", "10minutemail.net", "tempmail.com", "temp-mail.org",
    "temp-mail.io", "yopmail.com", "yopmail.net", "trashmail.com", "trashmail.de", "getnada.com", "nada.email", "sharklasers.com",
    "dispostable.com", "maildrop.cc", "throwawaymail.com", "fakeinbox.com", "mintemail.com", "mohmal.com", "emailondeck.com",
    "spamgourmet.com", "mailnesia.com", "mytemp.email", "tempail.com", "burnermail.io", "inboxkitten.com", "moakt.com",
    "tempmailo.com", "tmail.ws", "luxusmail.org", "1secmail.com", "1secmail.net", "emailfake.com", "fakemail.net",
    "mailcatch.com", "spambox.us", "dropmail.me", "minuteinbox.com", "tempinbox.com", "discard.email", "mailpoof.com",
    "33mail.com", "anonaddy.me", "trash-mail.com", "wegwerfmail.de", "mvrht.com", "grr.la", "pokemail.net",
}
FREE = {"gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com",
        "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.de", "mail.com", "zoho.com", "yandex.com", "yandex.ru",
        "qq.com", "163.com", "126.com", "naver.com", "hey.com", "fastmail.com", "tutanota.com", "pm.me"}
ROLES = {"info", "admin", "support", "sales", "contact", "hello", "office", "help", "billing", "noreply", "no-reply", "webmaster",
         "postmaster", "abuse", "marketing", "team", "jobs", "careers", "hr", "accounts", "service", "enquiries", "orders"}


def check(email):
    out = {"service": "OMENZ Email Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "smtp_probe": False, "stored": False}
    e = str(email or "").strip()
    if not e or len(e) > 254 or e.count("@") != 1:
        return {**out, "verdict": "UNDELIVERABLE", "input": e[:80], "reasons": ["not a single address of the form name@domain"]}
    local, dom = e.rsplit("@", 1)
    dom = dom.lower().rstrip(".")
    if not LOCAL_RE.match(local) or local.startswith(".") or local.endswith(".") or ".." in local:
        return {**out, "verdict": "UNDELIVERABLE", "input": e, "reasons": ["invalid characters or dots in the part before @"]}
    if not domain_check.DOMAIN_RE.match(dom):
        return {**out, "verdict": "UNDELIVERABLE", "input": e, "reasons": ["invalid domain after @"]}
    base = domain_check._registrable(dom)
    lp = local.lower()
    res = {**out, "input": e, "normalized": f"{lp.split('+', 1)[0]}@{dom}", "domain": dom,
           "free_provider": base in FREE or dom in FREE, "disposable": base in DISPOSABLE or dom in DISPOSABLE,
           "role_account": lp.split("+", 1)[0] in ROLES, "plus_addressing": "+" in lp}
    mx = domain_check._dns(dom, "MX")
    a = domain_check._dns(dom, "A") if not mx else None
    txt = domain_check._dns(base, "TXT") or []
    dmarc = domain_check._dns("_dmarc." + base, "TXT") or []
    spf = next((t for t in txt if t.lower().startswith("v=spf1")), None)
    dm = next((t for t in dmarc if t.lower().startswith("v=dmarc1")), None)
    res["mail"] = {"mx": (mx or [])[:5], "a_fallback": bool(a), "spf": bool(spf), "dmarc": bool(dm)}
    reasons, risks = [], []
    if mx is None and a is None:
        reasons.append("DNS lookup unavailable right now")
        verdict = "UNKNOWN"
    elif not mx and not a:
        reasons.append(f"{dom} has no mail server (no MX, no A record): mail will bounce")
        verdict = "UNDELIVERABLE"
    else:
        if res["disposable"]:
            risks.append("disposable/throwaway email provider: the person can vanish; do not treat as a real lead or identity")
        if not spf and not dm and not res["free_provider"]:
            risks.append("domain has no SPF and no DMARC: mail claiming to come from it is easy to spoof")
        if not mx:
            risks.append("no MX record (relies on A-record fallback): delivery may fail")
        verdict = "RISKY" if risks else "DELIVERABLE_LIKELY"
    notes = []
    if res["role_account"]:
        notes.append("role account (shared inbox), not a specific person")
    if res["free_provider"]:
        notes.append("free webmail address, not a company domain")
    res.update(verdict=verdict, reasons=reasons, risks=risks, notes=notes,
               limits="Checks syntax and the domain's mail setup; it cannot confirm the specific inbox exists (no SMTP probe by design).")
    return res
