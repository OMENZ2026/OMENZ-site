"""OMENZ Event Check: did this company actually FILE it, or is it just going around?

Born from our own scar (2026-11-14): we called the Nvidia CEO resignation "unconfirmed" from a stale search summary
while the 8-K had been on file for two days. Agents trading, reporting or deciding on corporate news need the issuer's
own filing, not the loudest post.

Input: ticker (or company name) + claim text (+ days window). We map the claim to the 8-K item(s) a US public company
must file for that kind of event, pull the company's recent filings from SEC EDGAR, and look for the matching item,
then quote the filing text that matches the claim's key words.
Verdicts: FILED (a matching 8-K item exists and its text matches) | FILED_RELATED (matching item, text match weak) |
NO_FILING_YET (no matching item in the window; not proof the claim is false) | NOT_A_FILING_EVENT | NOT_FOUND.
Deterministic, no AI calls. SEC fair-access: identified UA, few requests.
"""
import json
import re
import time
import urllib.request

VERSION = "0.1.0"
UA = {"User-Agent": "OMENZ Event Check hello@omenz.org", "Accept-Encoding": "identity"}
# claim words -> (8-K items, label)
KINDS = [
    (r"\b(resign\w*|step(?:s|ped|ping)? down|retir\w*|fired|ousted|depart\w*|appoint\w*|named (?:as )?(?:interim |new )?(?:ceo|cfo|chair\w*|president)|"
     r"interim ceo|new ceo|successor|leaves? (?:the )?(?:company|board)|terminat\w* (?:as|of) (?:ceo|cfo))", ["5.02"], "officer/director change"),
    (r"\b(acquir\w*|acquisition|merg\w*|buyout|takeover|to buy|deal to purchase)\b", ["1.01", "2.01", "8.01"], "acquisition/merger"),
    (r"\b(earnings|quarterly results|revenue of|reported (?:revenue|results)|guidance|q[1-4] results)\b", ["2.02", "7.01"], "results/guidance"),
    (r"\b(bankrupt\w*|chapter 11|chapter 7|insolven\w*)\b", ["1.03"], "bankruptcy"),
    (r"\b(delist\w*|nasdaq notice|nyse notice|non-?compliance with listing)\b", ["3.01"], "listing standards"),
    (r"\b(restat\w*|non-reliance|accounting error)\b", ["4.02"], "restatement"),
    (r"\b(cyber\w*|hack\w*|breach|ransomware|security incident)\b", ["1.05", "8.01"], "cybersecurity incident"),
    (r"\b(layoffs?|job cuts|restructur\w*|severance|workforce reduction)\b", ["2.05", "8.01"], "restructuring/layoffs"),
    (r"\b(auditor|accountant) (?:resign\w*|dismiss\w*|change\w*)", ["4.01"], "auditor change"),
    (r"\b(dividend|buyback|repurchase|stock split)\b", ["8.01", "7.01"], "capital return"),
]
VERB_FAMILY = {"officer/director change": r"resign\w*|step\w* down|retir\w*|depart\w*|terminat\w*|appoint\w*|interim|successor|named|elect\w*",
               "acquisition/merger": r"acqui\w*|merg\w*|purchase\w*|definitive agreement",
               "results/guidance": r"results|revenue|earnings|quarter\w*|guidance",
               "bankruptcy": r"chapter 11|chapter 7|bankrupt\w*|petition",
               "restatement": r"restat\w*|non-reliance|should no longer be relied",
               "cybersecurity incident": r"cyber\w*|incident|unauthori[sz]ed|breach",
               "restructuring/layoffs": r"restructur\w*|reduction|layoff\w*|severance",
               "listing standards": r"delist\w*|listing|deficiency|nasdaq|nyse",
               "auditor change": r"auditor|accountant|dismiss\w*",
               "capital return": r"dividend|repurchase|buyback|split"}
ALIAS = {"ceo": "chief executive officer", "cfo": "chief financial officer", "coo": "chief operating officer",
         "cto": "chief technology officer", "chairman": "chair", "board": "board of directors", "jensen": "jen-hsun"}
STOP = {"the", "a", "an", "and", "of", "to", "as", "in", "on", "for", "has", "have", "is", "was", "with", "its", "by",
        "that", "from", "at", "be", "will", "it", "his", "her", "their", "inc", "corp", "corporation", "company"}
_tickers = None


def _get(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _company(q):
    global _tickers
    if _tickers is None:
        _tickers = list(json.loads(_get("https://www.sec.gov/files/company_tickers.json")).values())
    q = (q or "").strip()
    for t in _tickers:
        if t["ticker"].upper() == q.upper():
            return t
    ql = q.lower()
    hits = [t for t in _tickers if ql and ql in t["title"].lower()]
    hits.sort(key=lambda t: len(t["title"]))
    return hits[0] if hits else None


def _plain(html):
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;|&#160;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"&#8217;|&rsquo;", "'", t)
    t = re.sub(r"&#?\w+;", " ", t)
    return " ".join(t.split())


def check(company, claim, days=30):
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "company_query": company,
           "claim": (claim or "")[:400], "source": "SEC EDGAR"}
    if not company or not claim:
        return {**out, "verdict": "ERROR", "error": "company (ticker or name) and claim are required"}
    try:
        days = max(1, min(int(days or 30), 365))
    except (TypeError, ValueError):
        days = 30
    kinds = [(items, label) for rx, items, label in KINDS if re.search(rx, claim, re.I)]
    if not kinds:
        return {**out, "verdict": "NOT_A_FILING_EVENT", "note": "this kind of claim doesn't require an 8-K; check the company's own "
                "newsroom or other primary sources"}
    items_wanted = sorted({i for items, _ in kinds for i in items})
    try:
        c = _company(company)
    except Exception as e:
        return {**out, "verdict": "ERROR", "error": f"SEC lookup failed ({type(e).__name__}); try again"}
    if not c:
        return {**out, "verdict": "NOT_FOUND", "note": "no SEC registrant matches that ticker/name (non-US or private companies don't file 8-Ks)"}
    cik = str(c["cik_str"]).zfill(10)
    out.update({"company": c["title"], "ticker": c["ticker"], "cik": cik, "event_type": [l for _, l in kinds],
                "items_checked": items_wanted, "window_days": days})
    try:
        sub = json.loads(_get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    except Exception as e:
        return {**out, "verdict": "ERROR", "error": f"SEC filings fetch failed ({type(e).__name__})"}
    r = sub["filings"]["recent"]
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    filings = []
    for i, form in enumerate(r["form"]):
        if r["filingDate"][i] < cutoff:
            break
        if form not in ("8-K", "8-K/A"):
            continue
        its = [x.strip() for x in (r.get("items", [""] * len(r["form"]))[i] or "").split(",") if x.strip()]
        acc = r["accessionNumber"][i]
        doc = r["primaryDocument"][i]
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
        filings.append({"form": form, "filed": r["filingDate"][i], "items": its, "url": url,
                        "description": r.get("primaryDocDescription", [""] * len(r["form"]))[i]})
    match = [f for f in filings if set(f["items"]) & set(items_wanted)]
    out["recent_8k_count"] = len(filings)
    if not match:
        return {**out, "verdict": "NO_FILING_YET", "matching_filings": [], "recent_8ks": filings[:5],
                "note": f"no 8-K with item {', '.join(items_wanted)} in the last {days} days. Companies have 4 business days "
                        "to file, so a very fresh event may not be filed yet; this is not proof the claim is false."}
    words = [w for w in dict.fromkeys(re.findall(r"[a-z][a-z'-]{2,}", claim.lower())) if w not in STOP]
    verbs = VERB_FAMILY.get(kinds[0][1], "")
    co_words = {w.lower() for w in re.findall(r"[A-Za-z]+", c["title"])} | {c["ticker"].lower()}
    names = [w.lower() for w in re.findall(r"\b[A-Z][a-z]{2,}\b", claim)[1:] + re.findall(r"\b[A-Z][a-z]{2,}\b", claim)[:1]]
    roles = [w for w in ("ceo", "cfo", "coo", "cto", "chair", "chairman", "president", "director") if re.search(r"\b" + w + r"\b", claim.lower())]
    keys = [k for k in dict.fromkeys([n for n in names if n not in co_words and n not in STOP] + roles)
            if not (verbs and re.fullmatch(verbs, k))]
    best = None
    for f in match[:3]:
        try:
            text = _plain(_get(f["url"]).decode("utf-8", "replace"))
        except Exception:
            continue
        # only the body of the matching item(s): skip the cover page boilerplate
        sec = ""
        for it in f["items"]:
            if it in items_wanted:
                m = re.search(r"Item\s*" + re.escape(it) + r"\.?(.{0,6000}?)(?=Item\s*\d\.\d\d|SIGNATURES?|$)", text, re.I | re.S)
                if m:
                    sec += " " + m.group(1)
        sec = sec.strip() or text
        sec = re.sub(r"(?i)departure of directors or certain officers;?.{0,200}?compensatory arrangements of certain officers\.?", " ", sec)
        sec = re.sub(r"(?i)^\s*(results of operations and financial condition|entry into a material definitive agreement|other events|"
                     r"regulation fd disclosure)\.?", " ", sec)
        low = sec.lower()
        verb_hit = bool(verbs and re.search(verbs, low))
        content = [w for w in words if not (verbs and re.fullmatch(verbs, w))]
        hit = [w for w in content if w in low or (ALIAS.get(w) and ALIAS[w] in low)]
        score = (len(hit) + (1 if verb_hit else 0)) / max(1, len(content) + (1 if verbs else 0))
        # specifics: every person/role named in the claim must appear in ONE sentence with the event verb
        sents = [x.strip() for x in re.split(r"(?<![A-Z]\.)(?<=[.;])\s+", sec) if len(x) > 30]
        def has(term, sl):
            return term in sl or (ALIAS.get(term) and ALIAS[term] in sl)
        quote, specific = None, False
        for sent in sents:
            sl = sent.lower()
            if keys and all(has(k, sl) for k in keys) and (not verbs or re.search(verbs, sl)):
                quote, specific = sent, True
                break
        if not quote:
            for sent in sents:
                sl = sent.lower()
                if len(sent) >= 60 and any(has(w, sl) for w in hit) and (not verbs or re.search(verbs, sl)):
                    quote = sent
                    break
        cand = {**f, "claim_words_found": hit + (["<event verb>"] if verb_hit else []), "match_share": round(score, 2),
                "quote": (quote or "")[:500] or None, "specifics_confirmed": specific, "specifics_checked": keys}
        if not best or cand["match_share"] > best["match_share"]:
            best = cand
    if not best:
        return {**out, "verdict": "FILED_RELATED", "matching_filings": match[:5],
                "note": "a matching 8-K item exists but its text couldn't be read; open the link"}
    strong = bool(best.get("specifics_confirmed")) or (not best.get("specifics_checked") and best["match_share"] >= 0.5 and best.get("quote"))
    return {**out, "verdict": "FILED" if strong else "FILED_RELATED", "best_filing": best, "matching_filings": match[:5],
            "note": None if strong else "a filing of this type exists, but no single sentence in it states the claim's specifics (names/roles); read the quote before relying on it"}
