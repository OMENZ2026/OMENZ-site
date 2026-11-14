"""OMENZ Branch Resolver: which location page of a multi-location business matches the place you mean?

Born from our own scar (Local Facts holdout #1, 2026-11-12): a chain's homepage gave another branch's phone.
Input: the business's website + a location hint (city, ZIP and/or street). Output: the branch page that matches,
with its phone/address/hours from Local Facts, or "ambiguous"/"not_found" with the candidates. Never guesses.

Deterministic, no AI calls, public pages only, honest crawler UA (shared with Local Facts).
"""
import re
import time
import urllib.parse

import business_facts as bf
import local_facts
from checker import visible_text

VERSION = "0.1.0"
INDEX_HINT = re.compile(r"/(locations?|stores?|store-locator|find-(?:a-|us|location|store)[\w-]*|restaurants?|branches|offices|"
                        r"our-locations|visit(?:-us)?|clinics?|studios?|shops?)(?:/|$|\.html?|\?)", re.I)
ANCHOR = re.compile(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
STOP = {"the", "and", "of", "st", "street", "ave", "avenue", "blvd", "rd", "road", "dr", "suite", "ste", "location",
        "locations", "store", "ca", "ny", "tx", "fl", "usa", "us", "n", "s", "e", "w", "north", "south", "east", "west"}
MAX_INDEX, MAX_PAGES = 2, 6


def _site(u):
    return ".".join((urllib.parse.urlparse(u).hostname or "").lower().split(".")[-2:])


def _toks(s):
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP and len(t) > 1]


def _links(page, base, context=False):
    out = []
    page = page or ""
    for m in ANCHOR.finditer(page):
        href = urllib.parse.urljoin(base, m.group(1).strip())
        if not href.startswith("http") or _site(href) != _site(base):
            continue
        text = " ".join(TAG.sub(" ", m.group(2)).split())[:120]
        if context:  # address text printed next to the link on a location list
            near = page[max(0, m.start() - 600):m.end() + 600]
            near = re.sub(r"<(script|style).*?</>", " ", near, flags=re.S | re.I)
            text = text + " || " + " ".join(TAG.sub(" ", near).split())[:500]
        out.append((href.split("#")[0], text))
    return out


def _query(city, zip_code, street):
    return {"city": _toks(city), "zip": re.findall(r"\b\d{5}\b", zip_code or ""), "street": _toks(street)}


def _score_text(q, text):
    t = " " + " ".join(_toks(text)) + " "
    s, hit = 0, []
    if q["zip"] and any(z in t for z in q["zip"]):
        s += 5; hit.append("zip")
    if q["city"] and " " + " ".join(q["city"]) + " " in t:
        s += 3; hit.append("city")
    if q["street"]:
        n = sum(1 for w in q["street"] if f" {w} " in t)
        if n >= max(1, len(q["street"]) - 1):
            s += 4; hit.append("street")
    return s, hit


def resolve(url, city=None, zip_code=None, street=None):
    t0 = time.time()
    base = {"url": url, "version": VERSION, "query": {"city": city, "zip": zip_code, "street": street},
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not (city or zip_code or street):
        return {**base, "status": "error", "error": "give at least one of city, zip, street"}
    if not re.match(r"^https?://", url or "", re.I):
        url = "https://" + (url or "")
    q = _query(city, zip_code, street)
    fetch = bf._memo_fetch()
    home = fetch(url)
    if not home.get("ok"):
        return {**base, "status": "error", "error": home.get("blocked_by") and "blocked_by_bot_protection" or "fetch_failed",
                "http_status": home.get("status")}
    final = home["url"]
    if _site(final) != _site(url):
        return {**base, "status": "moved_offsite", "moved_to": urllib.parse.urlparse(final).netloc,
                "note": "this address now leads to a different website; branches there may belong to another business"}
    pages_read = [final]
    # 1. location index pages linked from the page given (or the page itself)
    idx = [final] if INDEX_HINT.search(urllib.parse.urlparse(final).path) else []
    for href, _ in _links(home["text"], final):
        if INDEX_HINT.search(urllib.parse.urlparse(href).path) and href not in idx:
            idx.append(href)
    cands = {}
    for iu in idx[:MAX_INDEX + (1 if idx and idx[0] == final else 0)]:
        r = home if iu == final else fetch(iu)
        if iu != final:
            pages_read.append(iu)
        if not r.get("ok"):
            continue
        ipath = urllib.parse.urlparse(r["url"]).path.rstrip("/")
        for href, text in _links(r["text"], r["url"], context=True):
            p = urllib.parse.urlparse(href).path.rstrip("/")
            deeper = ipath and p.startswith(ipath + "/") and p != ipath
            if deeper or INDEX_HINT.search(p + "/") and p.count("/") >= 2:
                c = cands.setdefault(href, {"url": href, "labels": set()})
                if text:
                    c["labels"].add(text)
    if not idx or not cands:
        # No branch list we can read. Only call it a single-location site when the page's OWN confirmed address
        # matches the hint (ZIP/street, or the city of that address). A city merely mentioned on the page is not enough
        # (holdout 2026-11-14: Cafe Gratitude, Porto's are multi-location with JS-only lists).
        lf = local_facts.lookup(final)
        a = ((lf or {}).get("address") or {}).get("value") or {}
        ok_status = (lf or {}).get("status") == "ok"
        addr_text = " ".join(str(a.get(k) or "") for k in ("street", "city", "postal_code"))
        s, hit = _score_text(q, addr_text) if a else (0, [])
        mentions_many = bool(re.search(r"(our|all|other|nearby|find (?:a|your)) (locations|stores|restaurants|cafes|shops)",
                                       " ".join(visible_text(home["text"]).split()), re.I))
        good = ok_status and s and not mentions_many
        return {**base, "status": "single_location" if good else "not_found", "branch_url": final if good else None,
                "matched_on": hit if good else [], "facts": _facts(lf) if good else None, "candidates": [],
                "pages_read": pages_read,
                "note": None if good else ("no readable location list, and the site's own confirmed address doesn't match "
                                           "that place (location lists loaded by JavaScript aren't seen)"),
                "cost": {"seconds": round(time.time() - t0, 2)}}
    # 2. score candidates on link text + URL slug
    scored = []
    for c in cands.values():
        s, hit = _score_text(q, " ".join(c["labels"]) + " " + urllib.parse.urlparse(c["url"]).path.replace("-", " ").replace("/", " "))
        scored.append([s, hit, c])
    scored.sort(key=lambda x: -x[0])
    # 3. confirm on the pages themselves (top few; or a sample when slugs say nothing)
    top = [x for x in scored if x[0] > 0][:MAX_PAGES] or scored[:MAX_PAGES]
    confirmed = []
    for x in top:
        r = fetch(x[2]["url"])
        pages_read.append(x[2]["url"])
        if not r.get("ok"):
            continue
        s, hit = _score_text(q, " ".join(visible_text(r["text"]).split()))
        if s:
            # the branch's own identity (URL slug, <title>, first heading) outranks a mention elsewhere on the page
            own = urllib.parse.urlparse(x[2]["url"]).path.replace("-", " ").replace("/", " ") + " " +                 " ".join(TAG.sub(" ", " ".join(re.findall(r"<(?:title|h1)[^>]*>(.*?)</(?:title|h1)>", r["text"], re.I | re.S))).split())
            s2, hit2 = _score_text(q, own)
            confirmed.append((s + s2, sorted(set(hit) | {h + "_in_title_or_url" for h in hit2}), x[2]["url"]))
    confirmed.sort(key=lambda x: -x[0])
    cand_list = [{"url": x[2]["url"], "label": sorted(x[2]["labels"])[:1] or None, "slug_score": x[0]} for x in scored[:8]]
    out = {**base, "branches_listed": len(cands), "candidates": cand_list, "pages_read": pages_read}
    if not confirmed:
        return {**out, "status": "not_found", "branch_url": None, "facts": None,
                "note": "no listed branch page mentions that place", "cost": {"seconds": round(time.time() - t0, 2)}}
    best = confirmed[0]
    if len(confirmed) > 1 and confirmed[1][0] == best[0] and set(confirmed[1][1]) == set(best[1]):
        return {**out, "status": "ambiguous", "branch_url": None, "facts": None,
                "matches": [{"url": c[2], "matched_on": c[1]} for c in confirmed[:4]],
                "note": "several branch pages match equally; add a ZIP or street", "cost": {"seconds": round(time.time() - t0, 2)}}
    lf = local_facts.lookup(best[2])
    return {**out, "status": "resolved", "branch_url": best[2], "matched_on": best[1],
            "confidence": "high" if ("zip" in best[1] or "street" in best[1]) else "medium",
            "facts": _facts(lf), "cost": {"seconds": round(time.time() - t0, 2)}}


def _facts(lf):
    if not lf or lf.get("error"):
        return {"error": (lf or {}).get("error")}
    return {k: lf.get(k) for k in ("name", "phone", "address", "hours", "notices", "status")}


if __name__ == "__main__":
    import json
    import sys
    a = sys.argv[1:] + [None] * 3
    print(json.dumps(resolve(a[0], a[1], a[2], a[3]), indent=2, default=list, ensure_ascii=False))
