"""PROTOTYPE v0.0.6 (local evaluation only): structured-data vs visible-page check for LOCAL businesses.

v0.0.6 changes (from holdout #2 evidence only, founder option C/B 2026-10-15):
  - only location-level entities (LocalBusiness family) are compared; Organization/Corporation entries
    are reported as company-level info, never as conflicts (corporate HQ addresses are normal)
  - (tried and REMOVED before freezing: a 'shown by script' downgrade. Raw-HTML presence also matched
    site-settings JSON such as Squarespace contactPhoneNumber (Agnes), hiding a real finding, and it
    did not catch Hattie B's, whose locations load from elsewhere. Known limit: JavaScript-loaded
    content can't be confirmed without a headless browser.)
  - 24/7 hours (00:00-23:59 / 00:00-00:00) confirmed by "24/7", "24 hours", "open 24"
  - schema times like "8:00 - 5:00" (closing earlier than opening) read as pm closing
  - 0.6 s spacing between requests to the same site (one site rate-limited us with HTTP 429)


Founder approval 2026-10-15: build v0.0.5 narrowed to the part that generalized in the
v0.0.4 holdout (structured data vs what the page actually shows), with HTML-entity
decoding, and drop free-text vs free-text comparisons. v0.0.4 stays frozen in
conflicts_prototype.py. The published Actor and checker.py are unchanged.

Hard flags (state "conflict") come ONLY from the site's own schema.org business data:
  schema_phone_not_shown    schema telephone appears in no visible text and no tel: link
  schema_address_not_shown  schema street number + street name never appear together on the page
  schema_name_is_address    schema "name" field holds a street address
Soft states ("possible") never claim an error:
  schema_name_not_shown     schema name not found in the page text/title (brands vary)
  schema_hours_unconfirmed  schema open/close times not found anywhere in the page text
Everything else is "confirmed", "no_schema" (nothing to check against) or informational.
It never decides which value is right; it reports where each value came from.
"""
import html as _html
import json
import re
import sys
import time
import urllib.parse

GAP_S = 0.6
COMPANY_TYPES = {"Organization", "Corporation", "NGO", "GovernmentOrganization"}

from checker import _fetch, extract_jsonld, visible_text, BUSINESS_TYPES
from conflicts_prototype import PHONE_RE, STREET_RE, LEGAL_SUFFIX, _norm_phone, _candidate_pages

V = "0.0.6-proto"
DIRECTIONS = {"n", "s", "e", "w", "north", "south", "east", "west", "ne", "nw", "se", "sw"}


def _types(it):
    t = it["@type"] if isinstance(it["@type"], list) else [it["@type"]]
    return [x for x in t if isinstance(x, str)]


def _is_business(it):
    return any(t in BUSINESS_TYPES or t.endswith("Business") for t in _types(it))


def _is_company_only(it):
    ts = _types(it)
    return bool(ts) and all(t in COMPANY_TYPES for t in ts)


def _strip_ld(page):
    return re.sub(r"<script[^>]+application/ld\+json[^>]*>.*?</script>", " ", page, flags=re.S | re.I)


def _clean(s):
    return _html.unescape(_html.unescape(str(s or ""))).strip()


def _name_key(n):
    n = LEGAL_SUFFIX.sub("", _clean(n).lower())
    return " ".join(re.sub(r"[^a-z0-9& ]", " ", n).split())


def _street_parts(street):
    m = re.match(r"\s*(\d{1,6})\s+(.*)", _clean(street))
    if not m:
        return None
    words = [w for w in re.sub(r"[^A-Za-z0-9 ]", " ", m.group(2)).lower().split() if w not in DIRECTIONS]
    return (m.group(1), words[0]) if words else None


def _time_forms(t):
    """'17:00' -> regex alternatives matching 5pm, 5:00 pm, 5:00PM, 17:00."""
    m = re.match(r"(\d{1,2}):?(\d{2})?", str(t))
    if not m:
        return None
    h, mi = int(m.group(1)), m.group(2) or "00"
    h12 = h % 12 or 12
    ap = "p" if h >= 12 else "a"
    alts = [r"\b{}:{}\b".format(h, mi), r"\b{}\s*:?\s*{}?\s*{}\.?\s*m\b".format(h12, mi if mi != "00" else "(?:00)", ap)]
    if mi == "00":
        alts.append(r"\b{}\s*{}\.?\s*m\b".format(h12, ap))
    return "(?:" + "|".join(alts) + ")"


def _schema_hours_pairs(b):
    pairs = set()
    specs = b.get("openingHoursSpecification")
    specs = specs if isinstance(specs, list) else ([specs] if isinstance(specs, dict) else [])
    for s in specs:
        if s.get("opens") and s.get("closes"):
            pairs.add((str(s["opens"])[:5], str(s["closes"])[:5]))
    oh = b.get("openingHours")
    for e in (oh if isinstance(oh, list) else [oh] if oh else []):
        m = re.search(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", str(e))
        if m:
            pairs.add((m.group(1), m.group(2)))
    return pairs


def check(url):
    t0 = time.time()
    stats = {"requests": 0, "bytes": 0}
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    home = _fetch(url)
    stats["requests"] += 1
    stats["bytes"] += len(home.get("text") or "")
    if not home["ok"]:
        return {"url": url, "version": V, "error": "unreachable", "status": home.get("status") or home.get("error"), "cost": stats}
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(home["url"]))
    pages = [("home", home["url"], home["text"])]
    for u in _candidate_pages(home["text"], origin):
        time.sleep(GAP_S)
        r = _fetch(u)
        stats["requests"] += 1
        stats["bytes"] += len(r.get("text") or "")
        if r["ok"]:
            pages.append((urllib.parse.urlparse(u).path or "/", r["url"], r["text"]))

    text_all, shown_phones, schema, raw_other, company = "", {}, [], "", []
    for label, _u, page in pages:
        t = _clean(visible_text(page))
        text_all += " \n " + t
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
        if title:
            text_all += " \n " + _clean(title.group(1))
        for m in PHONE_RE.finditer(t):
            shown_phones.setdefault(_norm_phone(m), set()).add(label + ":text")
        for m in re.finditer(r"href=[\"']tel:([^\"']+)", page, re.I):
            pm = PHONE_RE.search(m.group(1))
            if pm:
                shown_phones.setdefault(_norm_phone(pm), set()).add(label + ":tel_link")
        raw_other += " " + _strip_ld(page)
        for it in extract_jsonld(page):
            if _is_business(it):
                if _is_company_only(it):
                    company.append((label, it))
                else:
                    schema.append((label, it))
    low = text_all.lower()
    raw_low = _clean(raw_other).lower()
    raw_digits = re.sub(r"\D", "", raw_other)

    flags, checks = [], {"phone": [], "address": [], "name": [], "hours": []}

    def flag(sev, code, field, value, where, note):
        flags.append({"severity": sev, "code": code, "field": field, "schema_value": value,
                      "schema_found_on": sorted(where), "note": note})

    seen = {}
    for label, b in schema:
        if b.get("telephone"):
            pm = PHONE_RE.search(_clean(b["telephone"]))
            if pm:
                seen.setdefault(("phone", _norm_phone(pm)), set()).add(label)
        addr = b.get("address")
        addr = addr[0] if isinstance(addr, list) and addr else addr
        if isinstance(addr, dict) and addr.get("streetAddress"):
            seen.setdefault(("address", _clean(addr["streetAddress"])), set()).add(label)
        if b.get("name"):
            seen.setdefault(("name", _clean(b["name"])), set()).add(label)
        for p in _schema_hours_pairs(b):
            seen.setdefault(("hours", p), set()).add(label)

    for (field, val), where in seen.items():
        if field == "phone":
            if val in shown_phones:
                checks["phone"].append({"value": val, "state": "confirmed", "shown_on": sorted(shown_phones[val])})
            else:
                flag("conflict", "schema_phone_not_shown", "phone", val, where,
                     "The business data tells AI assistants to call {}, but that number appears nowhere on the pages read. "
                     "Numbers shown instead: {}.".format(val, ", ".join(sorted(shown_phones)) or "none"))
                checks["phone"].append({"value": val, "state": "conflict"})
        elif field == "address":
            parts = _street_parts(val)
            if not parts:
                checks["address"].append({"value": val, "state": "unparseable"})
                continue
            num, word = parts
            ok = re.search(r"\b{}\b[^\n]{{0,30}}?\b{}".format(re.escape(num), re.escape(word)), low)
            pat = r"\b{}\b[^\n]{{0,30}}?\b{}".format(re.escape(num), re.escape(word))
            if ok:
                checks["address"].append({"value": val, "state": "confirmed"})
            else:
                flag("conflict", "schema_address_not_shown", "address", val, where,
                     "The business data gives the address '{}', but it does not appear on the pages read.".format(val))
                checks["address"].append({"value": val, "state": "conflict"})
        elif field == "name":
            if STREET_RE.match(val) or re.match(r"^\d{1,6}\s+\w+", val):
                flag("conflict", "schema_name_is_address", "name", val, where,
                     "The business data's name field holds what looks like a street address, not the business name.")
                checks["name"].append({"value": val, "state": "conflict"})
            else:
                key = _name_key(val)
                core = [w for w in key.split() if len(w) > 2][:3]
                if key and (key in _name_key(text_all) or (core and all(w in low for w in core))):
                    checks["name"].append({"value": val, "state": "confirmed"})
                else:
                    flag("possible", "schema_name_not_shown", "name", val, where,
                         "The business-data name doesn't appear on the page (brand names can legitimately differ).")
                    checks["name"].append({"value": val, "state": "possible"})
        elif field == "hours":
            o, c = val
            if o.startswith("00:00") and c[:5] in ("23:59", "00:00", "24:00"):
                if re.search(r"24\s*/\s*7|24 hours|open 24|24-hour", low):
                    checks["hours"].append({"value": "24/7", "state": "confirmed"})
                else:
                    flag("possible", "schema_hours_unconfirmed", "hours", "24/7", where, "Business data says open 24/7; the page text doesn't say so. Verify.")
                    checks["hours"].append({"value": "24/7", "state": "possible"})
                continue
            try:
                oh, ch = int(o.split(":")[0]), int(c.split(":")[0])
                if ch < oh and ch < 12:
                    c = "{:02d}:{}".format(ch + 12, (c.split(":") + ["00"])[1][:2])
            except ValueError:
                pass
            fo, fc = _time_forms(o), _time_forms(c)
            if fo and fc and re.search(fo, low) and re.search(fc, low):
                checks["hours"].append({"value": "{}-{}".format(o, c), "state": "confirmed"})
            else:
                flag("possible", "schema_hours_unconfirmed", "hours", "{}-{}".format(o, c), where,
                     "These business-data hours were not found in the page text; verify them.")
                checks["hours"].append({"value": "{}-{}".format(o, c), "state": "possible"})

    summary = {f: ("no_schema" if not v else "conflict" if any(x["state"] == "conflict" for x in v)
                   else "possible" if any(x["state"] == "possible" for x in v) else "confirmed")
               for f, v in checks.items()}
    stats["seconds"] = round(time.time() - t0, 2)
    return {"url": url, "final_url": home["url"], "version": V, "pages_read": [p[1] for p in pages],
            "schema_business_entities": len(schema), "summary": summary, "flags": flags, "checks": checks,
            "info": {"phones_shown": {k: sorted(v) for k, v in shown_phones.items()},
                     "company_level_entities": [{"page": l, "type": _types(it), "name": _clean(it.get("name")),
                                                 "address": (it.get("address") or {}).get("streetAddress") if isinstance(it.get("address"), dict) else None}
                                                for l, it in company][:5]},
            "cost": stats}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(check(sys.argv[1]), indent=2, ensure_ascii=False))
