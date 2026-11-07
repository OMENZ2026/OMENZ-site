"""Business Facts (local build, not published): website URL in, clean business facts out, as JSON for AI agents.

    python products/agent_ready_checker/business_facts.py https://example.com

Founder approval 2026-10-16 ("approve the build"): local build + frozen holdout only.
Publishing/pricing on Apify needs a separate founder yes (sug-apify-business-facts-tool-20261016).

What it returns for one website (public pages only, same pages the checkers read):
  name, phones, emails, address, hours, social links, geo
Each fact carries its sources (schema = the site's own structured business data; tel_link / mailto;
page_text) and a confidence: high = structured data and visible page agree, or 2+ independent sources;
medium = one clear source; low = text-pattern guess.
  consistency: the frozen v0.0.6 check (conflicts_v006, unchanged), labelled UNVERIFIED. It reports where
  the structured data and the page disagree; it never decides which value is right.

Deterministic, stdlib only, no AI calls. Known limits: content loaded by JavaScript is not seen;
multi-location brands may return a headquarters or one location; sites behind bot protection
(Cloudflare, Sucuri, ...) are reported as blocked, never bypassed: the tool identifies itself honestly.

0.1.1 (founder OK 2026-10-17, "A fix and retest"): address forms "813 Rue Bienville", "471-479 Castro St",
"Aurora Ave. N.", "City, ST" without ZIP; title fallback splits "::" and drops ", City, ST"; placeholder
names ("Your Site Title") are flagged as a site defect; bot-protection blocks are labelled; cp1252 pages decode.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import checker
import conflicts_v006 as c6
from checker import extract_jsonld, visible_text
from conflicts_prototype import PHONE_RE, EMAIL_RE, HOURS_RE, _norm_phone

VERSION = "0.1.1-local"
UA = "Mozilla/5.0 (compatible; OMENZ-BusinessFacts/{}; +https://omenz.org)".format(VERSION)
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
BOT_WALLS = re.compile(r"cloudflare|sucuri|cloudproxy|akamai|imperva|incapsula|ddos-guard|perimeterx|datadome", re.I)
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())
SUFFIX = (r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way|Ln|Lane|Ct|Court|Pl|Place|Hwy|Highway|"
          r"Pkwy|Parkway|Sq|Square|Ter|Terrace|Cir|Circle|Trl|Trail)")
# a range like 471-479, but never the tail of a phone number (365-1700, 352.6206)
NUM = r"(?<![\d$).-])(?<!\$\s)\b(?!\d{3}\s?[-–.]\s?\d{4}\b)\d{1,6}(?:[-–]\d{1,6})?"
STREET_SUFFIXED = re.compile(NUM + r"\s+(?:[NSEW]\.?\s+)?(?:\d+(?:st|nd|rd|th)|[A-Za-z][A-Za-z.'-]*)"
                             r"(?:\s+[A-Za-z0-9.'-]+){0,3}?\s+" + SUFFIX + r"\b\.?(?:\s+(?:N|S|E|W|NE|NW|SE|SW)\b\.?)?",
                             re.I)
STREET_PREFIXED = re.compile(NUM + r"\s+(?:Rue|Calle|Via|Avenida|Camino|Avenue of the)\s+[A-Z][A-Za-z.'-]+"
                             r"(?:\s+[A-Z][A-Za-z.'-]+){0,2}")
CITY_TAIL = re.compile(r"^\s*(?:\([^)]{0,40}\)\s*)?[,\s#A-Za-z0-9.-]{0,25}?,?\s*([A-Z][A-Za-z .'-]{1,30}?),?\s+"
                       r"([A-Z]{2})\b\.?,?(?:\s+(\d{5})(?:-\d{4})?)?(?![A-Za-z])")
PLACEHOLDER_NAME = re.compile(r"^(your (site|business|company|store) (title|name)|my (site|website|store|blog)|site title|"
                              r"untitled|new site|business name|company name|home page|squarespace|wix|shopify)$", re.I)
SOCIAL = re.compile(r"https?://(?:www\.)?(facebook\.com|instagram\.com|x\.com|twitter\.com|linkedin\.com|"
                    r"yelp\.com|tiktok\.com|youtube\.com|pinterest\.com)/[^\s\"'<>]+", re.I)
CITY_STATE_ZIP = re.compile(r"^[,\s#A-Za-z0-9.-]{0,25}?,?\s*([A-Z][A-Za-z .'-]{1,30}),?\s+([A-Z]{2})\.?,?\s+(\d{5})(?:-\d{4})?")
BAD_EMAIL = re.compile(r"\.(png|jpe?g|gif|svg|webp)$|@(sentry|example|domain|email)\.|wixpress|^u00", re.I)
TITLE_SPLIT = re.compile(r"\s*::\s*|\s+[|–—:-]\s+|\s+·\s+")
GENERIC_TITLE = re.compile(r"^(home|homepage|welcome|index|official site|official website)$", re.I)
CITY_ST_END = re.compile(r",\s*[A-Z][A-Za-z .'-]{1,30},\s*[A-Z]{2}$")


def _decode(body, charset):
    text = body.decode(charset, "replace")
    if "�" in text and charset.lower().replace("-", "") == "utf8":
        alt = body.decode("cp1252", "replace")
        if alt.count("�") < text.count("�"):
            return alt
    return text


def _fetch(url):
    """Same contract as checker._fetch; honest crawler UA plus normal headers; labels bot-protection blocks."""
    req = urllib.request.Request(url, headers=HEADERS)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=checker.TIMEOUT) as r:
            body = r.read(checker.MAX_BYTES)
            return {"ok": True, "status": r.status, "url": r.geturl(), "ms": int((time.time() - t0) * 1000),
                    "text": _decode(body, r.headers.get_content_charset() or "utf-8"),
                    "ctype": r.headers.get("Content-Type", "")}
    except urllib.error.HTTPError as e:
        server = " ".join(filter(None, [e.headers.get("Server"), e.headers.get("X-Sucuri-ID") and "sucuri",
                                        e.headers.get("cf-ray") and "cloudflare"]))
        wall = BOT_WALLS.search(server or "")
        return {"ok": False, "status": e.code, "url": url, "ms": int((time.time() - t0) * 1000), "text": "", "ctype": "",
                "blocked_by": wall.group(0).lower() if wall and e.code in (307, 403, 429, 503) else None}
    except Exception as e:
        return {"ok": False, "status": None, "url": url, "error": type(e).__name__, "text": "", "ctype": ""}


def _memo_fetch():
    cache, real = {}, _fetch

    def f(url):
        if url not in cache:
            cache[url] = real(url)
        return cache[url]
    return f


def _add(store, key, value, source):
    e = store.setdefault(key, {"value": value, "sources": []})
    if source not in e["sources"]:
        e["sources"].append(source)


def _conf(sources, schema_confirmed=False):
    kinds = {s.split(":")[0] for s in sources}
    if schema_confirmed or len(kinds) >= 2:
        return "high"
    return "medium" if kinds & {"schema", "tel_link", "mailto"} else "low"


def _name_from_title(page):
    og = re.search(r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']+)", page, re.I) or \
         re.search(r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']og:site_name", page, re.I)
    if og and not PLACEHOLDER_NAME.match(c6._clean(og.group(1))):
        return c6._clean(og.group(1)), "page_meta:og_site_name"
    t = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    if t:
        parts = [CITY_ST_END.sub("", p.strip()) for p in TITLE_SPLIT.split(c6._clean(t.group(1))) if p.strip()]
        parts = [p for p in parts if p and not GENERIC_TITLE.match(p) and not PLACEHOLDER_NAME.match(p) and len(p) <= 60]
        if parts:
            # brand is usually the shortest segment (titles look like "Page - Brand" or "Brand | tagline")
            return min(parts, key=len), "page_title"
    return None, None


def _placeholders(page):
    """Placeholder names a site builder left in the site's own name data (a real defect agents will repeat)."""
    found = set()
    for m in re.finditer(r"<title[^>]*>(.*?)</title>|property=[\"']og:(?:site_name|title)[\"'][^>]+content=[\"']([^\"']+)",
                         page, re.S | re.I):
        v = c6._clean(m.group(1) or m.group(2))
        if PLACEHOLDER_NAME.match(v):
            found.add(v)
    for it in extract_jsonld(page):
        if isinstance(it.get("name"), str) and PLACEHOLDER_NAME.match(c6._clean(it["name"])):
            found.add(c6._clean(it["name"]))
    return sorted(found)


def _text_addresses(text):
    """(street, city, region, zip_or_None) from visible text; a city/state must follow the street."""
    out = []
    for rx in (STREET_SUFFIXED, STREET_PREFIXED):
        for m in rx.finditer(text):
            street = " ".join(m.group(0).split())
            tail = CITY_TAIL.match(text[m.end():m.end() + 90])
            if not tail or tail.group(2) not in US_STATES:
                continue  # without city + valid state right after, too many false street matches
            out.append((street, tail.group(1).strip(), tail.group(2), tail.group(3)))
    return out


def facts(url):
    t0 = time.time()
    fetch = _memo_fetch()
    c6._fetch = fetch  # share fetches with the frozen v0.0.6 check (no change to its rules)
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    consistency = c6.check(url)
    if consistency.get("error"):
        home = fetch(url)
        if home.get("blocked_by"):
            return {"url": url, "version": VERSION, "error": "blocked_by_bot_protection", "status": home.get("status"),
                    "blocked_by": home["blocked_by"],
                    "note": "The site's bot protection refused an honestly identified automated reader. AI agents that "
                            "identify themselves are likely refused too. Not bypassed."}
        if home.get("status") == 429:
            return {"url": url, "version": VERSION, "error": "rate_limited", "status": 429,
                    "note": "The site asked automated readers to slow down. Try again later."}
        return {"url": url, "version": VERSION, "error": consistency["error"], "status": consistency.get("status")}
    pages = []
    for u in consistency["pages_read"]:
        r = fetch(u)
        if r.get("ok"):
            pages.append((urllib.parse.urlparse(r["url"]).path or "/", r["text"]))

    names, phones, emails, addrs, hours, social, geo = {}, {}, {}, {}, {}, set(), None
    schema_types, placeholders = set(), set()
    for label, page in pages:
        text = c6._clean(visible_text(page))
        placeholders.update(_placeholders(page))
        for it in extract_jsonld(page):
            if not c6._is_business(it):
                continue
            schema_types.update(c6._types(it))
            src = "schema:" + label
            if it.get("name") and not c6._is_company_only(it) and not PLACEHOLDER_NAME.match(c6._clean(it["name"])):
                _add(names, c6._name_key(it["name"]), c6._clean(it["name"]), src)
            if it.get("telephone"):
                pm = PHONE_RE.search(c6._clean(it["telephone"]))
                if pm:
                    _add(phones, _norm_phone(pm), _norm_phone(pm), src)
            if it.get("email"):
                em = c6._clean(it["email"]).replace("mailto:", "").lower()
                _add(emails, em, em, src)
            a = it.get("address")
            a = a[0] if isinstance(a, list) and a else a
            if isinstance(a, dict) and a.get("streetAddress") and not c6._is_company_only(it):
                rec = {k: c6._clean(a.get(v)) or None for k, v in (("street", "streetAddress"), ("city", "addressLocality"),
                       ("region", "addressRegion"), ("postal_code", "postalCode"), ("country", "addressCountry"))}
                if isinstance(a.get("addressCountry"), dict):
                    rec["country"] = c6._clean(a["addressCountry"].get("name"))
                _add(addrs, (c6._street_parts(rec["street"]) or (rec["street"].lower(),)), rec, src)
            for o, c in c6._schema_hours_pairs(it):
                _add(hours, ("schema", o, c), {"opens": o, "closes": c}, src)
            spec = it.get("openingHoursSpecification")
            if isinstance(spec, list):
                for s in spec:
                    days = s.get("dayOfWeek")
                    days = days if isinstance(days, list) else [days]
                    for d in days:
                        if d and s.get("opens"):
                            k = ("schema_day", str(d).rsplit("/", 1)[-1], s["opens"][:5], (s.get("closes") or "")[:5])
                            _add(hours, k, {"day": k[1], "opens": k[2], "closes": k[3]}, src)
            g = it.get("geo")
            if isinstance(g, dict) and g.get("latitude") and not geo:
                geo = {"latitude": g.get("latitude"), "longitude": g.get("longitude"), "source": src}
            same = it.get("sameAs")
            for s in (same if isinstance(same, list) else [same] if same else []):
                if isinstance(s, str) and s.startswith("http"):
                    social.add(s.rstrip("/"))
        # visible page
        for m in re.finditer(r"href=[\"']tel:([^\"']+)", page, re.I):
            pm = PHONE_RE.search(m.group(1))
            if pm:
                _add(phones, _norm_phone(pm), _norm_phone(pm), "tel_link:" + label)
        for m in PHONE_RE.finditer(text):
            before = text[max(0, m.start() - 12):m.start()].lower()
            if "fax" in before:
                continue
            _add(phones, _norm_phone(m), _norm_phone(m), "page_text:" + label)
        for m in re.finditer(r"href=[\"']mailto:([^\"'?]+)", page, re.I):
            em = urllib.parse.unquote(m.group(1)).strip().lower()
            if EMAIL_RE.fullmatch(em) and not BAD_EMAIL.search(em):
                _add(emails, em, em, "mailto:" + label)
        for m in EMAIL_RE.finditer(text):
            em = m.group(0).lower().rstrip(".")
            if not BAD_EMAIL.search(em):
                _add(emails, em, em, "page_text:" + label)
        for street, city, region, zipc in _text_addresses(text):
            key = c6._street_parts(street) or (street.lower(),)
            rec = {"street": street, "city": city, "region": region, "postal_code": zipc, "country": None}
            if key in addrs and not addrs[key]["value"]["postal_code"] and zipc:
                addrs[key]["value"] = rec  # prefer the fuller form of the same street
            _add(addrs, key, rec, "page_text:" + label)
        for m in HOURS_RE.finditer(text):
            _add(hours, ("text", " ".join(m.group(0).split())), {"text": " ".join(m.group(0).split())}, "page_text:" + label)
        for m in SOCIAL.finditer(page):
            u = m.group(0).rstrip("/\\")
            if not re.search(r"/(sharer|share|intent|plugins|dialog|tr\?)", u):
                social.add(u)

    cons = consistency.get("checks", {})
    confirmed = {f: {x.get("value") for x in cons.get(f, []) if x.get("state") == "confirmed"} for f in cons}

    def ranked(store, field, key_of=lambda k: k):
        out = []
        for k, e in store.items():
            sc = any(s.startswith("schema") for s in e["sources"])
            out.append({"value": e["value"], "sources": sorted(e["sources"]),
                        "confidence": _conf(e["sources"], sc and key_of(k) in confirmed.get(field, set()))})
        order = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda x: (order[x["confidence"]], -len(x["sources"])))
        return out

    name_list = ranked(names, "name", lambda k: names[k]["value"])
    if not name_list and pages:
        n, src = _name_from_title(pages[0][1])
        if n:
            name_list = [{"value": n, "sources": [src], "confidence": "low"}]
    phone_list = ranked(phones, "phone")
    addr_list = []
    for k, e in addrs.items():
        sc = any(s.startswith("schema") for s in e["sources"])
        addr_list.append({**e["value"], "sources": sorted(e["sources"]),
                          "confidence": _conf(e["sources"], sc and e["value"]["street"] in confirmed.get("address", set()))})
    addr_list.sort(key=lambda x: ({"high": 0, "medium": 1, "low": 2}[x["confidence"]], not x["postal_code"],
                                  -len(x["sources"])))
    hours_list = [{**e["value"], "sources": sorted(e["sources"])} for e in hours.values()]

    return {
        "url": url, "final_url": consistency.get("final_url"), "version": VERSION,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "has_structured_data": bool(consistency.get("schema_business_entities")),
        "business_types": sorted(schema_types),
        "name": name_list[0] if name_list else None,
        "name_candidates": name_list[1:4],
        "phones": phone_list[:5],
        "emails": ranked(emails, "email")[:5],
        "address": addr_list[0] if addr_list else None,
        "address_candidates": addr_list[1:4],
        "hours": hours_list[:14],
        "social_links": sorted(social)[:10],
        "geo": geo,
        "site_defects": [{"type": "placeholder_name", "value": p,
                          "note": "Site builder placeholder left in the site's own name data; agents may repeat it."}
                         for p in sorted(placeholders)],
        "consistency": {"status": "UNVERIFIED - automated check; confirm against the live site before acting",
                        "summary": consistency.get("summary"), "flags": consistency.get("flags"),
                        "engine": consistency.get("version")},
        "pages_read": consistency.get("pages_read"),
        "limits": "Public pages only; JavaScript-loaded content is not seen; multi-location brands may show one location or HQ.",
        "cost": {"requests": consistency.get("cost", {}).get("requests"), "seconds": round(time.time() - t0, 2)},
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(facts(sys.argv[1]), indent=2, ensure_ascii=False))
