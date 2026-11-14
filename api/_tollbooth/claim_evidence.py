"""OMENZ Claim -> Evidence: does this source actually say what the agent claims it says, and where?

Agents cite sources they never read closely; a citation is only as good as the sentence behind it. Give a claim and a
source URL: we read the page and return the sentence(s) that support it, with a verdict.

Precision rules (deterministic, no AI calls):
- every NUMBER in the claim (amounts, percents, years, counts) must appear in the same sentence, normalized
  (e.g. "$1.2 billion" == "1.2 billion", "41.3%" == "41.3 percent");
- every NAME (capitalized word) in the claim must appear in that sentence;
- most of the remaining content words must appear there too.
SUPPORTED = one sentence meets all three. PARTIAL = names/numbers split across sentences or some missing (quotes shown).
NOT_FOUND = the page doesn't carry it. Negation in the sentence ("not", "denied") is flagged, never silently passed.
"""
import re
import time

import business_facts as bf
from checker import visible_text

VERSION = "0.1.0"
STOP = {"the", "a", "an", "and", "or", "of", "to", "as", "in", "on", "for", "has", "have", "had", "is", "are", "was",
        "were", "with", "its", "by", "that", "this", "from", "at", "be", "been", "will", "it", "his", "her", "their",
        "said", "says", "about", "than", "more", "less", "over", "into", "after", "before", "which", "who", "also"}
NEG = re.compile(r"\b(not|no|never|denied|denies|deny|false|incorrect|rumou?r|unconfirmed|didn't|did not|isn't|wasn't)\b", re.I)
SCALE = {"thousand": "k", "k": "k", "million": "m", "m": "m", "mn": "m", "billion": "b", "bn": "b", "b": "b", "trillion": "t", "t": "t"}


def _nums(s):
    out = set()
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(%|percent|thousand|million|billion|trillion|bn|mn|[kmbt]\b)?", s, re.I):
        n = m.group(1).replace(",", "")
        if n.endswith(".0"):
            n = n[:-2]
        unit = (m.group(2) or "").lower()
        unit = "%" if unit in ("%", "percent") else SCALE.get(unit, "")
        out.add(n + unit)
    return out


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<![A-Z]\.)(?<=[.!?;])\s+|\n+|\s[•|·]\s|\s{3,}", text) if 20 <= len(s.strip()) <= 1200]


def check(claim, url):
    t0 = time.time()
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "claim": (claim or "")[:600], "url": url}
    if not claim or not url:
        return {**out, "verdict": "ERROR", "error": "claim and url are required"}
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    r = bf._fetch(url)
    if not r.get("ok"):
        return {**out, "verdict": "UNREADABLE", "http_status": r.get("status"), "blocked_by": r.get("blocked_by"),
                "note": "couldn't read the source; this is not evidence either way"}
    text = " ".join(re.sub(r"<[^>]{0,400}>", " ", visible_text(r["text"])).split())
    if len(text) < 200:
        return {**out, "verdict": "UNREADABLE", "note": "page has almost no readable text (JavaScript-only?)", "final_url": r["url"]}
    nums = _nums(claim)
    names = {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", claim)[1:]} | \
            {w.lower() for w in re.findall(r"\b[A-Z]{2,}\b", claim)}
    first = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", claim)[:1]
    if first and first[0].lower() not in STOP:
        names.add(first[0].lower())
    words = {w for w in re.findall(r"[a-z][a-z'-]{2,}", claim.lower()) if w not in STOP} - names
    best, scored = None, []
    host = (r.get("url") or url).lower()
    self_names = {n for n in names if n in host}  # the source's own name needn't be repeated next to each fact
    sents = _sentences(text)
    for i, s in enumerate(sents):
        sl = s.lower()
        ctx = (sents[i - 1].lower() + " " + sl) if i else sl  # names may sit in the sentence just before ("Harvey C. Jones ... Jones has")
        sn = _nums(s)
        n_ok = nums <= sn
        nm_ok = all(re.search(r"\b" + re.escape(n) + r"\b", ctx) for n in names - self_names)
        w_share = sum(1 for w in words if w[:5] in sl) / max(1, len(words))
        score = (2 if n_ok and nums else 0) + (2 if nm_ok and names else 0) + w_share * 2 + \
            0.5 * len(nums & sn) + 0.5 * sum(1 for n in names if n in sl)
        if score > 0.6:
            scored.append((score, n_ok, nm_ok, w_share, s))
    scored.sort(key=lambda x: -x[0])
    anchors = [n for n in names - self_names] + [w[:5] for w in words]

    def near(s):
        # every claim number must sit next to the claim's own words (Apify holdout: "$999" belonged to another plan)
        if not nums:
            return True
        sl = s.lower()
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(%|percent|thousand|million|billion|trillion|bn|mn|[kmbt]\b)?", s, re.I):
            pass
        for n in nums:
            ok = False
            for m in re.finditer(r"\d[\d,]*(?:\.\d+)?\s*(?:%|percent|thousand|million|billion|trillion|bn|mn|[kmbt]\b)?", s, re.I):
                if n not in _nums(m.group(0)):
                    continue
                win = sl[max(0, m.start() - 120):m.end() + 60]
                key_names = [n for n in names - self_names if not re.fullmatch(r"[\d.]+", n)]
                if key_names:  # a distinctive name (plan, product, person) must sit next to the number
                    good = any(re.search(r"\b" + re.escape(n) + r"\b", win) for n in key_names)
                else:
                    good = sum(1 for a in anchors if a in win) >= max(1, min(2, len(anchors)))
                if good:
                    ok = True
                    break
            if not ok:
                return False
        return True

    for sc, n_ok, nm_ok, w_share, s in scored:
        if n_ok and nm_ok and w_share >= 0.5 and near(s):
            best = (sc, s)
            break
    base = {**out, "final_url": r["url"], "checked_numbers": sorted(nums), "checked_names": sorted(names),
            "cost": {"seconds": round(time.time() - t0, 2)}}
    if best:
        neg = NEG.search(best[1])
        return {**base, "verdict": "SUPPORTED" if not neg else "CHECK_NEGATION", "quote": best[1][:800],
                "note": None if not neg else f"the matching sentence contains '{neg.group(0)}': read it; it may deny the claim"}
    if scored:
        top = [s for *_, s in scored[:3]]
        missing_nums = sorted(nums - set().union(*[_nums(s) for s in top])) if nums else []
        missing_names = sorted(n for n in names if not any(n in s.lower() for s in top))
        return {**base, "verdict": "PARTIAL", "closest": [q[:500] for q in top], "missing_numbers": missing_nums,
                "missing_names": missing_names,
                "note": "no single sentence carries the claim's numbers, names and wording together; read the closest sentences"}
    return {**base, "verdict": "NOT_FOUND", "note": "the page doesn't contain the claim's numbers/names/wording"}
