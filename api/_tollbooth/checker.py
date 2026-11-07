"""OMENZ Agent-Ready Checker — can AI assistants and agents find, read, and use a business website?

    python products/agent_ready_checker/checker.py https://example.com [--json]

Standalone product (stdlib only, no OMENZ internals) so it can ship as an Apify
Actor / agent-callable tool and power the Agent-Ready Business Audit.
It reads only public pages a crawler would read: the home page, robots.txt,
llms.txt and sitemap.xml. Deterministic — no AI calls, no cost per run.

Output: a score 0-100 plus findings, each with severity, what it means for AI
assistants, and a plain-language fix.
"""
import html as _html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
UA = "OMENZ-AgentReadyChecker/{} (+https://omenz.org)".format(VERSION)
TIMEOUT = 20
MAX_BYTES = 3_000_000

# AI crawlers / assistant fetchers commonly named in robots.txt.
AI_BOTS = {
    "GPTBot": "OpenAI training crawler",
    "OAI-SearchBot": "ChatGPT search",
    "ChatGPT-User": "ChatGPT browsing for a user",
    "ClaudeBot": "Anthropic crawler",
    "Claude-User": "Claude browsing for a user",
    "PerplexityBot": "Perplexity search",
    "Perplexity-User": "Perplexity browsing for a user",
    "Google-Extended": "Google AI (Gemini) use",
    "Applebot-Extended": "Apple AI use",
}
ASSISTANT_FETCHERS = ("OAI-SearchBot", "ChatGPT-User", "Claude-User", "PerplexityBot", "Perplexity-User")
BUSINESS_TYPES = ("LocalBusiness", "Organization", "Restaurant", "Store", "ProfessionalService",
                  "MedicalBusiness", "HealthAndBeautyBusiness", "AutomotiveBusiness", "FoodEstablishment",
                  "HomeAndConstructionBusiness", "LegalService", "FinancialService", "Corporation")
KEY_FIELDS = ("name", "address", "telephone", "openingHours", "openingHoursSpecification", "url", "geo", "priceRange", "sameAs")
BOOKING_HINTS = re.compile(r"\b(book(ing)?|appointment|schedule|reserve|reservation|order online|get a quote|request a quote)\b|"
                           r"calendly\.com|squareup\.com/appointments|booksy|vagaro|opentable|resy|toasttab|acuityscheduling", re.I)


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,text/plain,*/*"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(MAX_BYTES)
            charset = r.headers.get_content_charset() or "utf-8"
            return {"ok": True, "status": r.status, "url": r.geturl(), "ms": int((time.time() - t0) * 1000),
                    "text": body.decode(charset, "replace"), "ctype": r.headers.get("Content-Type", "")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "url": url, "ms": int((time.time() - t0) * 1000), "text": "", "ctype": ""}
    except Exception as e:
        return {"ok": False, "status": None, "url": url, "error": type(e).__name__, "text": "", "ctype": ""}


def parse_robots(text):
    """Return {agent_lower: [(allow|disallow, path)]}."""
    groups, current, last_was_agent = {}, [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if not last_was_agent:
                current = []
            current.append(v.lower())
            groups.setdefault(v.lower(), [])
            last_was_agent = True
        elif k in ("allow", "disallow"):
            for a in current:
                groups.setdefault(a, []).append((k, v))
            last_was_agent = False
        else:
            last_was_agent = False
    return groups


def bot_blocked_from_root(groups, bot):
    rules = groups.get(bot.lower())
    if rules is None:
        rules = groups.get("*", [])
    allows = [p for k, p in rules if k == "allow" and p in ("/", "/*")]
    blocks = [p for k, p in rules if k == "disallow" and p in ("/", "/*")]
    return bool(blocks) and not allows


def extract_jsonld(page):
    items = []
    for m in re.finditer(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(_html.unescape(m.group(1).strip()))
        except Exception:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                if "@graph" in d:
                    stack.extend(d["@graph"] if isinstance(d["@graph"], list) else [d["@graph"]])
                if "@type" in d:
                    items.append(d)
    return items


def visible_text(page):
    t = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def check(url):
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url))
    findings, score = [], 100

    def add(sev, code, what, fix, penalty):
        nonlocal score
        findings.append({"severity": sev, "code": code, "what_it_means": what, "fix": fix})
        score -= penalty

    home = _fetch(url)
    if not home["ok"]:
        add("critical", "site_unreachable", "AI assistants could not load the home page (status {}).".format(home.get("status") or home.get("error")),
            "Make sure the site loads publicly without a login or block page.", 60)
        return {"url": url, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checker_version": VERSION,
                "score": max(score, 0), "findings": findings, "facts": {}}
    page = home["text"]
    final = home["url"]
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(final))  # after redirects
    if not final.lower().startswith("https://"):
        add("high", "no_https", "The site isn't served over HTTPS; some assistants trust or show it less.", "Turn on HTTPS (most hosts offer it free).", 10)

    robots = _fetch(origin + "/robots.txt")
    groups = parse_robots(robots["text"]) if robots["ok"] else {}
    blocked = [b for b in AI_BOTS if bot_blocked_from_root(groups, b)]
    blocked_assistants = [b for b in blocked if b in ASSISTANT_FETCHERS]
    if blocked_assistants:
        add("critical", "assistants_blocked", "robots.txt blocks AI assistants that look things up for customers: {}.".format(", ".join(blocked_assistants)),
            "Allow these assistant user-agents in robots.txt (you can still block training-only crawlers like GPTBot if you prefer).", 30)
    elif blocked:
        add("info", "training_crawlers_blocked", "robots.txt blocks some AI training crawlers ({}), but not assistant lookups.".format(", ".join(blocked)),
            "No action needed unless you want your content used for AI training.", 0)

    items = extract_jsonld(page)
    types = sorted({t for it in items for t in (it["@type"] if isinstance(it["@type"], list) else [it["@type"]]) if isinstance(t, str)})
    biz = [it for it in items if any(t in BUSINESS_TYPES or t.endswith("Business") for t in (it["@type"] if isinstance(it["@type"], list) else [it["@type"]]) if isinstance(t, str))]
    if not items:
        add("high", "no_structured_data", "No structured data (schema.org JSON-LD) found, so assistants have to guess your name, address, hours and services.",
            "Add a LocalBusiness (or Organization) JSON-LD block with name, address, phone, hours and website.", 20)
    elif not biz:
        add("medium", "no_business_schema", "Structured data exists ({}), but none describes the business itself.".format(", ".join(types[:5])),
            "Add a LocalBusiness or Organization block describing the business.", 12)
    else:
        b = biz[0]
        missing = [f for f in ("name", "address", "telephone", "url") if not b.get(f)]
        if not (b.get("openingHours") or b.get("openingHoursSpecification")):
            missing.append("opening hours")
        if missing:
            add("medium", "business_schema_incomplete", "Business data is missing: {}.".format(", ".join(missing)),
                "Fill in the missing fields so assistants can answer 'are they open / where / how do I reach them'.", 4 * len(missing))

    llms = _fetch(origin + "/llms.txt")
    has_llms = llms["ok"] and len(llms["text"].strip()) > 20 and "<html" not in llms["text"][:500].lower()
    if not has_llms:
        add("low", "no_llms_txt", "No /llms.txt summary for AI tools (an emerging convention, not a requirement).",
            "Optionally add /llms.txt: a short plain-text summary of who you are, what you offer, and key links.", 3)

    sitemap = _fetch(origin + "/sitemap.xml")
    has_sitemap = sitemap["ok"] and ("<urlset" in sitemap["text"] or "<sitemapindex" in sitemap["text"])
    has_sitemap = has_sitemap or bool(re.search(r"(?im)^sitemap:", robots["text"] or ""))
    if not has_sitemap:
        add("low", "no_sitemap", "No sitemap found, so crawlers may miss pages.", "Publish /sitemap.xml and reference it in robots.txt.", 3)

    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    desc = re.search(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']", page, re.S | re.I) or \
        re.search(r"<meta[^>]+content=[\"'](.*?)[\"'][^>]+name=[\"']description[\"']", page, re.S | re.I)
    if not title or not title.group(1).strip():
        add("medium", "no_title", "The page has no title for assistants to quote.", "Add a clear page title with business name and what you do.", 6)
    if not desc or not desc.group(1).strip():
        add("medium", "no_meta_description", "No meta description, so assistants have no short summary to quote.", "Add a one-sentence description: what you do, for whom, and where.", 5)

    text = visible_text(page)
    if len(text) < 400:
        add("high", "little_readable_text", "Very little readable text on the home page ({} characters); content may load only with JavaScript, which many AI fetchers don't run.".format(len(text)),
            "Make sure key info (services, location, hours, contact) appears as plain text in the page HTML.", 15)
    has_phone = bool(re.search(r"href=[\"']tel:", page, re.I))
    has_email = bool(re.search(r"href=[\"']mailto:", page, re.I))
    if not (has_phone or has_email):
        add("medium", "no_contact_links", "No clickable phone or email found on the home page.", "Add a tel: and/or mailto: link so assistants can tell customers how to reach you.", 6)
    has_booking = bool(BOOKING_HINTS.search(page))
    if not has_booking:
        add("low", "no_booking_path", "No visible way to book, order, or request a quote from the home page.", "Add a clear booking/order/quote link if customers can act online.", 4)

    return {
        "url": url, "final_url": final, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "checker_version": VERSION,
        "score": max(0, min(100, score)),
        "findings": sorted(findings, key=lambda f: ["critical", "high", "medium", "low", "info"].index(f["severity"])),
        "facts": {"https": final.lower().startswith("https://"), "load_ms": home.get("ms"), "robots_found": robots["ok"],
                  "ai_bots_blocked": blocked, "schema_types": types[:12], "business_schema": bool(biz), "llms_txt": has_llms,
                  "sitemap": bool(has_sitemap), "title": (_html.unescape(title.group(1)).strip()[:120] if title else None),
                  "readable_chars": len(text), "phone_link": has_phone, "email_link": has_email, "booking_path": has_booking},
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    r = check(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print("{}  score {}/100".format(r["url"], r["score"]))
        for f in r["findings"]:
            print(" [{}] {} -> {}".format(f["severity"], f["what_it_means"], f["fix"]))
