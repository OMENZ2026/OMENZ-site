"""OMENZ Local Facts v0.2: what a local business's OWN website says right now, for AI agents.
Founder "yes run it" 2026-11-12 (agent-pulse brief: local business truth is the thinnest active niche).

Precision first: a field is returned only when the site backs it clearly; otherwise it is null with a reason.
"Unknown" is a valid answer; a confident wrong answer is not. Every value carries where it came from.

Returns: name, phone, address, hours (structured, or verbatim text), notices (holiday hours / temporary closures /
"closed on ...", quoted word for word), menu_link, consistency flags (structured data vs page disagreements),
pages_read, checked_at. Built on business_facts 0.1.1 (frozen extraction) + conflicts v0.0.6 (frozen).

Deterministic, no AI calls, public pages only, honest crawler UA; bot protection is reported, never bypassed.
"""
import re
import time
import urllib.parse

import business_facts as bf
from checker import visible_text

VERSION = "0.2.1"
NOTICE = re.compile(
    r"[^.!?\n|*]{0,70}\b(temporar(?:y|ily) closed|closed (?:for|on|until|through|today|tomorrow|this|all day)|"
    r"(?:holiday|special|seasonal|winter|summer|thanksgiving|christmas) hours|we(?:'| wi)ll be closed|"
    r"will be closed|we are closed|permanently closed|reopen(?:ing|s)? (?:on|in|soon)|hours may vary|"
    r"closed (?:thanksgiving|christmas|new year'?s?|easter|memorial day|labor day|july 4|independence day))"
    r"[^.!?\n|*]{0,70}[.!?]?", re.I)
MENU_HREF = re.compile(r"href=[\"']([^\"'#]*menu[^\"'#]*)[\"']", re.I)


def _f(value, confidence, sources, **extra):
    return {"value": value, "confidence": confidence, "sources": sources, **extra}


def _unknown(reason):
    return {"value": None, "reason": reason}


def lookup(url):
    t0 = time.time()
    cache = {}
    real_memo = bf._memo_fetch

    def capturing_memo():
        fetch = real_memo()

        def f(u):
            r = fetch(u)
            cache[u] = r
            return r
        return f
    bf._memo_fetch = capturing_memo
    try:
        r = bf.facts(url)
    finally:
        bf._memo_fetch = real_memo
    base = {"url": r.get("url"), "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if r.get("error"):
        return {**base, "error": r["error"], "status": r.get("status"), "blocked_by": r.get("blocked_by"), "note": r.get("note")}

    out = dict(base, final_url=r.get("final_url"), has_structured_data=r.get("has_structured_data"),
               business_types=r.get("business_types"))
    site = lambda u: ".".join((urllib.parse.urlparse(u or "").netloc.lower().split(":")[0]).split(".")[-2:])
    if r.get("final_url") and site(r["final_url"]) != site(r.get("url")):
        return {**out, "status": "moved_offsite", "moved_to": urllib.parse.urlparse(r["final_url"]).netloc,
                "note": "This address now sends visitors to a different website (possibly sold, merged or replaced). "
                        "Facts there may belong to another business, so none are returned."}
    in_path = urllib.parse.urlparse(r.get("url") or "").path.lower()
    loc_pages = [u for u in (r.get("pages_read") or []) if re.search(r"/locations?(/|$)", urllib.parse.urlparse(u).path.lower())]
    multi = bool(loc_pages) and not re.search(r"location|/pages/|/store", in_path)
    out["status"] = "multi_location" if multi else "ok"
    # visible text of every page read: a value is returned only if a person on the site would see it
    seen_text = " ".join(" ".join(visible_text((cache.get(u) or {}).get("text") or "").split())
                         for u in (r.get("pages_read") or [])).lower()
    hidden = []
    n = r.get("name")
    if n and any(s.startswith("schema") for s in n["sources"]) and n["value"].lower() in seen_text:
        out["name"] = _f(n["value"], n["confidence"], n["sources"])
    else:
        out["name"] = _unknown("no business name that is both in the site's structured data and visible on the page")
        if n and any(s.startswith("schema") for s in n["sources"]):
            hidden.append({"field": "name", "hidden_value": n["value"]})
    phones = [p for p in r.get("phones", []) if any(s.startswith(("tel_link", "page_text")) for s in p["sources"])]
    for p in r.get("phones", []):
        if p not in phones and any(s.startswith("schema") for s in p["sources"]):
            hidden.append({"field": "phone", "hidden_value": p["value"]})
    out["phone"] = _f(phones[0]["value"], phones[0]["confidence"], phones[0]["sources"]) if phones else         _unknown("no phone shown on the pages read (tap-to-call link or visible text)")
    out["other_phones"] = [p["value"] for p in phones[1:3]]
    a = r.get("address")
    street_seen = bool(a) and a["street"] and a["street"].lower() in seen_text
    if a and a["confidence"] == "high" and street_seen:
        out["address"] = _f({k: a.get(k) for k in ("street", "city", "region", "postal_code", "country")},
                            a["confidence"], a["sources"])
    else:
        out["address"] = _unknown("no address both in the site's structured data and visible on the page")
        for c in [a] + (r.get("address_candidates") or []):
            if c and any(s.startswith("schema") for s in c["sources"]) and c["street"] and c["street"].lower() not in seen_text:
                hidden.append({"field": "address", "hidden_value": c["street"]})
    out["hidden_data"] = {"items": hidden[:5], "note": ("Values in the site's hidden structured data that don't appear on the "
                          "visible page. AI assistants may repeat these; treat them as unconfirmed.") if hidden else None}
    struct = [h for h in r.get("hours", []) if "day" in h]
    text_hours = [h["text"] for h in r.get("hours", []) if "text" in h][:6]
    out["hours"] = {"structured": [{k: h[k] for k in ("day", "opens", "closes")} for h in struct] or None,
                    "as_written": text_hours or None,
                    "note": None if (struct or text_hours) else "no hours found on the pages read"}

    if multi:
        why = "this site lists several locations and the URL given isn't a specific location's page"
        for k in ("phone", "address"):
            if out[k].get("value") is not None:
                out[k] = _unknown(why)
        out["other_phones"] = []
        out["hours"] = {"structured": None, "as_written": None, "note": why}
        out["locations_page"] = loc_pages[0]
    notices, seen = [], set()
    menu = None
    host = urllib.parse.urlparse(r.get("final_url") or url).netloc
    for u in r.get("pages_read") or []:
        page = (cache.get(u) or {}).get("text")
        if not page:
            continue
        text = " ".join(visible_text(page).split())
        for m in NOTICE.finditer(text):
            q = m.group(0).strip()
            k = q.lower()[:80]
            if k not in seen and len(q) > 12:
                seen.add(k)
                notices.append({"quote": q[:320], "page": u})
        if not menu:
            for mm in MENU_HREF.finditer(page):
                link = urllib.parse.urljoin(u, mm.group(1))
                if urllib.parse.urlparse(link).netloc in (host, "") or "menu" in urllib.parse.urlparse(link).netloc:
                    menu = link
                    break
    out["notices"] = notices[:6]
    out["notices_note"] = ("Quoted word for word from the site; check dates in the quote before relying on them."
                           if notices else "no holiday, special-hours or closure notice found on the pages read")
    out["menu_link"] = menu
    out["consistency"] = r.get("consistency")
    out["site_defects"] = r.get("site_defects")
    out["pages_read"] = r.get("pages_read")
    out["limits"] = ("The business's own public pages only. Fields the site doesn't clearly back are null, not guessed. "
                     "JavaScript-loaded content is not seen; multi-location brands may show one location.")
    out["cost"] = {"seconds": round(time.time() - t0, 2)}
    return out


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(lookup(sys.argv[1]), indent=2, ensure_ascii=False))
