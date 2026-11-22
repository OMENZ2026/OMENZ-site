"""OMENZ Lead Check: is this lead (email + phone + website) real enough to spend time on? (2026-11-22)

Bundle of Email Check + Phone Check + Domain Check in one call, cheaper than the three separately, plus cross-checks
that only make sense together: does the email domain match the company website, is the website domain brand-new,
is the phone fictional or premium-rate. Deterministic, public DNS/RDAP + offline phone data; nothing stored.

  FAKE_OR_UNUSABLE  email undeliverable, phone invalid/fictional, or website not registered / not resolving
  WEAK              disposable email, premium-rate/VoIP phone, website < 30 days old, or nothing checkable given
  GOOD_LEAD         everything given checks out
"""
import time

import domain_check
import email_check
import phone_check

VERSION = "0.1.0"


def check(req):
    req = req or {}
    out = {"service": "OMENZ Lead Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stored": False}
    email, phone, site = (str(req.get(k) or "").strip() for k in ("email", "phone", "website"))
    if not (email or phone or site):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["send at least one of email, phone, website (country helps for local phone formats)"]}
    fake, weak, good, parts = [], [], [], {}
    if email:
        e = email_check.check(email)
        parts["email"] = e
        if e["verdict"] == "UNDELIVERABLE":
            fake.append("email: " + "; ".join(e.get("reasons") or ["undeliverable"]))
        elif e["verdict"] == "RISKY":
            weak += [f"email: {r}" for r in e.get("risks") or []]
        elif e["verdict"] == "DELIVERABLE_LIKELY":
            good.append("email domain receives mail")
    if phone:
        p = phone_check.check(phone, req.get("country"))
        parts["phone"] = p
        if p["verdict"] in ("INVALID", "FICTIONAL", "POSSIBLE_BUT_INVALID", "BAD_INPUT"):
            why = p.get("warnings") or p.get("reasons") or []
            why = [w for w in why if "555-01XX" in w] or why if p["verdict"] == "FICTIONAL" else why
            fake.append(f"phone: {p['verdict'].lower().replace('_', ' ')}" + (f" ({why[0]})" if why else ""))
            if p.get("type") == "premium_rate":
                weak.append("phone: premium-rate number")
        else:
            if p.get("type") in ("premium_rate", "voip"):
                weak.append(f"phone: {p['type'].replace('_', '-')} number")
            good.append(f"phone valid ({p.get('type')}, {p.get('region')})")
    site_dom = None
    if site:
        d = domain_check.check(site)
        parts["website"] = {k: d.get(k) for k in ("verdict", "domain", "registered_domain", "registration", "red_flags", "caution")}
        site_dom = d.get("registered_domain") or d.get("domain")
        if d["verdict"] == "BAD_INPUT":
            fake.append("website: not a valid domain or URL")
        elif d["verdict"] == "RED_FLAGS":
            reds = d.get("red_flags") or []
            if any("registered only" in r for r in reds) and not any("not registered" in r or "does not resolve" in r for r in reds):
                weak += [f"website: {r}" for r in reds]
            else:
                fake += [f"website: {r}" for r in reds]
        else:
            age = (d.get("registration") or {}).get("age_days")
            good.append(f"website domain established" + (f" ({age // 365}y)" if age else ""))
    cross = {}
    if email and site_dom and parts.get("email", {}).get("domain"):
        e_dom = domain_check._registrable(parts["email"]["domain"])
        cross["email_matches_website"] = e_dom == site_dom
        if e_dom == site_dom:
            good.append("email is on the company's own domain")
        elif parts["email"].get("free_provider"):
            cross["note"] = "free webmail address for a business with its own website (common for very small businesses; weaker signal)"
        else:
            weak.append(f"email domain {e_dom} does not match website {site_dom}")
    verdict = "FAKE_OR_UNUSABLE" if fake else "WEAK" if weak else "GOOD_LEAD"
    return {**out, "verdict": verdict, "fake": fake, "weak": weak, "good": good, "cross_checks": cross, "parts": parts,
            "limits": "Checks that the contact details are real and consistent, not that the person wants to buy. No SMTP probe, no calls made.",
            "next": {"GOOD_LEAD": "worth a real touch", "WEAK": "read the weak signals before spending time", "FAKE_OR_UNUSABLE": "drop or fix this lead"}[verdict]}
