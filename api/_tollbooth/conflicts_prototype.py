"""PROTOTYPE (local evaluation only) — same-site conflicting-facts check.

Founder approval 2026-10-15: local prototype, ~10 test sites, measure incremental
cost, observe false positives / ambiguity / source-authority problems.
NOT wired into the published Apify Actor. Production checker (checker.py) is unchanged.

For one website it reads the home page plus up to MAX_EXTRA same-site pages that look
like contact / about / location / hours pages, extracts business facts from each
source (visible text, tel:/mailto: links, schema.org JSON-LD), and reports per field:

  consistent         same value seen in 2+ sources
  single_source      only one source states it
  conflict           2+ different values, no obvious legitimate reason
  conflict_possible_legitimate   2+ values that are often legitimate (extra phones,
                     multiple locations, name with/without legal suffix)
  schema_not_visible the JSON-LD value never appears in the visible text
  not_found          nothing found

It never picks a winner. Each value lists where it was found.

    python products/agent_ready_checker/conflicts_prototype.py https://example.com
"""
import json
import re
import sys
import time
import urllib.parse

from checker import _fetch, extract_jsonld, visible_text, BUSINESS_TYPES

PROTO_VERSION = "0.0.4-proto"  # 0.0.2: fax separated; street name starts with letter/ordinal. 0.0.3: ignore $prices; co-listed values = likely multi-location. 0.0.4: co-listing requires identical source kinds
MAX_EXTRA = 4
PAGE_HINT = re.compile(r"contact|about|location|locations|hours|visit|find-us|directions|our-office|office", re.I)

PHONE_RE = re.compile(r"(?<![\d.])(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?![\d])")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
STREET_RE = re.compile(
    r"(?<![\d$-])(?<!\$\s)\b(\d{1,6})\s+((?:[NSEW]\.?\s+)?(?:\d+(?:st|nd|rd|th)|[A-Za-z][A-Za-z.'-]*)(?:\s+[A-Za-z0-9.'-]+){0,3}?)\s+"
    r"(St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Way|Ln|Lane|Ct|Court|Pl|Place|Hwy|Highway|Pkwy|Parkway|Sq|Square)\b\.?",
    re.I)
ZIP_RE = re.compile(r"\b(9\d{4}|[0-8]\d{4})(?:-\d{4})?\b")
DAY = r"(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*"
HOURS_RE = re.compile(DAY + r"\.?\s*(?:[-–to]+\s*" + DAY + r"\.?)?\s*[:\-–]?\s*"
                      r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\s*(?:-|–|to)\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)", re.I)
LEGAL_SUFFIX = re.compile(r"\b(inc|llc|l\.l\.c|corp|co|ltd|pc|p\.c|apc|dds|md|dvm|cpa|pllc)\b\.?", re.I)
STREET_ABBR = {"street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr", "lane": "ln",
               "court": "ct", "place": "pl", "highway": "hwy", "parkway": "pkwy", "square": "sq"}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _norm_phone(m):
    return "{}-{}-{}".format(*m.groups())


def _norm_time(t):
    t = t.lower().replace(".", "").replace(" ", "")
    m = re.match(r"(\d{1,2})(?::(\d{2}))?([ap])m", t)
    if not m:
        return t
    h = int(m.group(1)) % 12 + (12 if m.group(3) == "p" else 0)
    return "{:02d}:{}".format(h, m.group(2) or "00")


def _day_idx(d):
    return DAYS.index(d[:3].lower()) if d and d[:3].lower() in DAYS else None


def _street_key(num, name, typ):
    name = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    name = [w for w in name if w not in ("n", "s", "e", "w", "north", "south", "east", "west")]
    typ = STREET_ABBR.get(typ.lower().rstrip("."), typ.lower().rstrip("."))
    return "{} {} {}".format(num, " ".join(name[-2:]), typ)


def _name_key(n):
    n = LEGAL_SUFFIX.sub("", n.lower())
    return " ".join(re.sub(r"[^a-z0-9& ]", " ", n).split())


def _phones_from(page_html, text):
    out = {}
    for m in re.finditer(r"href=[\"']tel:([^\"']+)", page_html, re.I):
        pm = PHONE_RE.search(m.group(1))
        if pm:
            out.setdefault(_norm_phone(pm), set()).add("tel_link")
    for pm in PHONE_RE.finditer(text):
        ctx = text[max(0, pm.start() - 12):pm.start()].lower()
        label = "text_fax" if "fax" in ctx else "text"
        out.setdefault(_norm_phone(pm), set()).add(label)
    return out


def _hours_from(text):
    """{day_index: (open, close)} from patterns like 'Mon - Fri 9:00 am - 5:00 pm'."""
    res = {}
    for m in HOURS_RE.finditer(text):
        d1, d2 = _day_idx(m.group(1)), _day_idx(m.group(2)) if m.group(2) else None
        if d1 is None:
            continue
        rng = range(d1, (d2 if d2 is not None and d2 >= d1 else d1) + 1)
        for d in rng:
            res.setdefault(d, (_norm_time(m.group(3)), _norm_time(m.group(4))))
    return res


def _schema_hours(b):
    res = {}
    for spec in (b.get("openingHoursSpecification") or []) if isinstance(b.get("openingHoursSpecification"), list) else \
            ([b["openingHoursSpecification"]] if isinstance(b.get("openingHoursSpecification"), dict) else []):
        days = spec.get("dayOfWeek") or []
        days = days if isinstance(days, list) else [days]
        for d in days:
            i = _day_idx(str(d).rsplit("/", 1)[-1])
            if i is not None and spec.get("opens") and spec.get("closes"):
                res[i] = (str(spec["opens"])[:5], str(spec["closes"])[:5])
    oh = b.get("openingHours")
    for entry in (oh if isinstance(oh, list) else [oh] if oh else []):
        m = re.match(r"([A-Za-z]{2})(?:-([A-Za-z]{2}))?\s+(\d{2}:\d{2})-(\d{2}:\d{2})", str(entry).strip())
        if m:
            a, z = _day_idx(m.group(1)), _day_idx(m.group(2)) if m.group(2) else None
            if a is not None:
                for d in range(a, (z if z is not None and z >= a else a) + 1):
                    res[d] = (m.group(3), m.group(4))
    return res


def _candidate_pages(home_html, origin):
    seen, out = set(), []
    for m in re.finditer(r"<a[^>]+href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", home_html, re.I | re.S):
        href, label = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        u = urllib.parse.urljoin(origin + "/", href).split("?")[0].rstrip("/")
        if urllib.parse.urlparse(u).netloc.lower().lstrip("www.") != urllib.parse.urlparse(origin).netloc.lower().lstrip("www."):
            continue
        if not (PAGE_HINT.search(href) or PAGE_HINT.search(label)):
            continue
        if u in seen or u.rstrip("/") == origin.rstrip("/"):
            continue
        seen.add(u)
        out.append(u)
    return out[:MAX_EXTRA]


def check_conflicts(url):
    t0 = time.time()
    stats = {"requests": 0, "bytes": 0}
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    home = _fetch(url)
    stats["requests"] += 1
    stats["bytes"] += len(home.get("text") or "")
    if not home["ok"]:
        return {"url": url, "error": "home_unreachable", "status": home.get("status") or home.get("error"), "cost": stats}
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(home["url"]))
    pages = [("home", home["url"], home["text"])]
    for u in _candidate_pages(home["text"], origin):
        r = _fetch(u)
        stats["requests"] += 1
        stats["bytes"] += len(r.get("text") or "")
        if r["ok"] and "html" in (r.get("ctype") or "html"):
            pages.append((urllib.parse.urlparse(u).path or "/", r["url"], r["text"]))

    phones, emails, streets, zips, names, hours_by_src = {}, {}, {}, {}, {}, {}
    schema = {}
    all_text = ""

    def put(store, val, src):
        store.setdefault(val, set()).add(src)

    for label, _u, html in pages:
        text = visible_text(html)
        all_text += " " + text
        for ph, kinds in _phones_from(html, text).items():
            for k in kinds:
                put(phones, ph, "{}:{}".format(label, k))
        for em in set(EMAIL_RE.findall(text)) | set(re.findall(r"href=[\"']mailto:([^\"'?]+)", html, re.I)):
            em = em.lower()
            if not em.endswith((".png", ".jpg", ".webp", ".gif")) and "sentry" not in em and "example" not in em:
                put(emails, em, label)
        for m in STREET_RE.finditer(text):
            put(streets, _street_key(m.group(1), m.group(2), m.group(3)), label)
        h = _hours_from(text)
        if h:
            hours_by_src["{}:text".format(label)] = h
        for it in extract_jsonld(html):
            types = it["@type"] if isinstance(it["@type"], list) else [it["@type"]]
            if not any(isinstance(t, str) and (t in BUSINESS_TYPES or t.endswith("Business")) for t in types):
                continue
            src = "{}:jsonld".format(label)
            if it.get("telephone"):
                pm = PHONE_RE.search(str(it["telephone"]))
                if pm:
                    put(phones, _norm_phone(pm), src)
                    schema.setdefault("phone", set()).add(_norm_phone(pm))
            if it.get("name"):
                put(names, _name_key(str(it["name"])), src)
                schema.setdefault("name", set()).add(_name_key(str(it["name"])))
            addr = it.get("address")
            addr = addr[0] if isinstance(addr, list) and addr else addr
            if isinstance(addr, dict):
                sm = STREET_RE.search(str(addr.get("streetAddress") or ""))
                if sm:
                    k = _street_key(sm.group(1), sm.group(2), sm.group(3))
                    put(streets, k, src)
                    schema.setdefault("street", set()).add(k)
                if addr.get("postalCode"):
                    put(zips, str(addr["postalCode"])[:5], src)
            sh = _schema_hours(it)
            if sh:
                hours_by_src[src] = sh
        og = re.search(r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"'](.*?)[\"']", html, re.I)
        if og:
            put(names, _name_key(og.group(1)), "{}:og_site_name".format(label))
    for z in set(ZIP_RE.findall(all_text)):
        put(zips, z, "text")

    fields = {}

    def _pages_of(srcs):
        return {s.split(":")[0] for s in srcs}

    def classify(field, store, legit_if_many=False):
        if not store:
            fields[field] = {"state": "not_found", "values": {}}
            return
        vals = {v: sorted(s) for v, s in store.items()}
        if len(vals) == 1:
            n_src = len(next(iter(vals.values())))
            fields[field] = {"state": "consistent" if n_src > 1 else "single_source", "values": vals}
            return
        # 0.0.3: values that appear side by side on the same 2+ pages are usually multiple
        # locations / lines listed together, not a disagreement
        # compare full source sets (page + kind), so structured data vs visible text never counts as "together"
        src_sets = [set(s) for s in store.values()]
        together = len(_pages_of(src_sets[0])) >= 2 and all(ss == src_sets[0] for ss in src_sets)
        if together:
            fields[field] = {"state": "conflict_possible_legitimate", "values": vals,
                             "reason": "all values listed together on the same pages (likely multiple locations or lines)"}
        else:
            fields[field] = {"state": "conflict_possible_legitimate" if legit_if_many else "conflict", "values": vals}

    # phones: drop numbers seen only as fax for the main comparison
    fax_numbers = {p for p, s in phones.items() if any(x.endswith("text_fax") for x in s)}
    main_phones = {p: s for p, s in phones.items() if p not in fax_numbers}
    classify("phone", main_phones, legit_if_many=len(main_phones) > 2)
    fields["fax"] = {"state": "info", "values": sorted(fax_numbers)}
    classify("email", emails, legit_if_many=True)
    classify("street_address", streets, legit_if_many=len(streets) > 2)
    classify("business_name", names)
    if fields["business_name"]["state"] == "conflict":
        ks = list(fields["business_name"]["values"])
        if all(a in b or b in a for a in ks for b in ks):
            fields["business_name"]["state"] = "conflict_possible_legitimate"

    # hours: compare each day across sources
    hours_conf = {}
    for d in range(7):
        vals = {}
        for src, h in hours_by_src.items():
            if d in h:
                vals.setdefault("{}-{}".format(*h[d]), []).append(src)
        if len(vals) > 1:
            hours_conf[DAYS[d]] = vals
    fields["hours"] = {"state": ("conflict" if hours_conf else ("consistent" if len(hours_by_src) > 1 else
                                 "single_source" if hours_by_src else "not_found")),
                       "sources": sorted(hours_by_src), "conflicting_days": hours_conf}

    # schema value never shown to humans
    schema_not_visible = []
    digits_text = re.sub(r"\D", "", all_text)
    for ph in schema.get("phone", []):
        if ph.replace("-", "") not in digits_text:
            schema_not_visible.append({"field": "phone", "value": ph})
    for st in schema.get("street", []):
        if st.split()[0] not in all_text:
            schema_not_visible.append({"field": "street_address", "value": st})

    stats["seconds"] = round(time.time() - t0, 2)
    return {"url": url, "final_url": home["url"], "proto_version": PROTO_VERSION,
            "pages_read": [p[1] for p in pages], "fields": fields,
            "schema_not_visible": schema_not_visible, "cost": stats}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(check_conflicts(sys.argv[1]), indent=2, ensure_ascii=False))
