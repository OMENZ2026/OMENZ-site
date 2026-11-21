"""OMENZ AI Agent Swap Meet (founder 2026-11-15: "I want to be the creator of the first AI AGENT SWAP MEET like the
Slauson swap meet"). A free, walkable market of paid agent services, with OMENZ trust checks at the booths.

Honest framing: Coinbase's Agentic.Market and a few directories already list x402 services. The Swap Meet's angle is
culture + trust: aisles you can walk, booths checked live before you pay, and anyone can bring a booth.
- aisles(): 7 aisles x top booths by listed 30-day calls (public Bazaar listing data). Browsing is free.
- search(q): top 12 booths for what you need.
- bring_booth(url, method): seller brings an x402 endpoint; OMENZ checks it live (real 402 + readable price) before it
  joins NEW ARRIVALS. Nothing is paid; only public endpoint facts are stored. 200 submissions/day.
Deep data stays paid on purpose: full ranked lists, reliability scores, payout-wallet checks, seller lead lists
(/v1/market/*). The Swap Meet is the storefront; the paid market tools are the appraisers.
"""
import math
import time

import market
import x402_probe

AISLES = [
    ("inference", "AI & Inference", {"llm", "gpt", "claude", "inference", "model", "chat", "completion", "completions", "embedding", "embeddings", "openai", "anthropic", "gemini", "prompt"}),
    ("data", "Data & Facts", {"weather", "company", "enrichment", "lookup", "address", "geocode", "facts", "dataset", "records", "stats", "sports", "news"}),
    ("media", "Media & Creative", {"image", "images", "video", "audio", "music", "voice", "tts", "speech", "generate", "art", "photo", "transcribe"}),
    ("search", "Search & Web", {"search", "scrape", "crawl", "web", "browse", "serp", "extract", "page", "website", "url"}),
    ("social", "Social", {"twitter", "tweet", "tweets", "farcaster", "social", "reddit", "telegram", "discord", "profile", "followers"}),
    ("infra", "Infrastructure", {"rpc", "storage", "wallet", "locker", "queue", "receipt", "verify", "ledger", "auth", "email", "sms", "proxy"}),
    ("trading", "Markets & Tokens", {"token", "tokens", "price", "swap", "defi", "dex", "pool", "pools", "trading", "solana", "ethereum", "crypto", "nft"}),
]
SUBMIT_CAP = 200
_cache = {"at": 0, "aisles": None}


def _kv(method, key, body=None):
    from locker import _kv as kv
    return kv(method, key, body)


def _booth(r):
    calls = r[5] or 0
    return {"booth": market._host(r[0]), "url": r[0], "method": r[2], "price_usd": r[3], "what": (r[1] or "")[:160],
            "networks": (r[4] or [])[:3], "foot_traffic": "busy" if calls >= 1000 else "steady" if calls >= 50 else "quiet",
            "appraise": f"/api/tollbooth/v1/market/reliability?url={r[0]}"}


def aisles(per=8):
    if _cache["aisles"] and time.time() - _cache["at"] < 3600:
        return _cache["aisles"]
    ix = market._index()
    out, seen = [], set()  # each booth appears in one aisle only
    for key, name, words in AISLES:
        picked = []
        ranked = sorted(((ix["rows"][i][5] or 0, i) for i, ts in enumerate(ix["toks"]) if ts & words), reverse=True)
        for _, i in ranked:
            r = ix["rows"][i]
            h = market._host(r[0])
            if h in seen or not r[3]:
                continue
            seen.add(h)
            picked.append(_booth(r))
            if len(picked) >= per:
                break
        out.append({"aisle": key, "name": name, "booths": picked})
    res = {"market": "OMENZ AI Agent Swap Meet", "index_generated_at": ix["generated_at"], "booths_in_market": ix["n"],
           "aisles": out, "house_booth": {"booth": "www.omenz.org", "what": "38 agent tools: preflight, spend gate, receipts, lockers, market data and more",
                                           "catalog": "/api/tollbooth", "try_free": "/api/tollbooth/ayne/v1", "track_record": "/api/tollbooth/v1/track-record"},
           "note": "Booths come from the public x402 Bazaar listings. Foot traffic = listed 30-day calls. Appraise a booth before paying (OMENZ reliability, $0.002)."}
    _cache.update(at=time.time(), aisles=res)
    return res


def search(q, limit=12):
    ix = market._index()
    qt = list(dict.fromkeys(market._toks(q)))
    if not qt:
        return {"error": "say what you're looking for (e.g. 'weather by city', 'image generation', 'token price')"}
    scored = []
    for r, ts in zip(ix["rows"], ix["toks"]):
        hit = sum(1 for t in qt if t in ts)
        if hit and r[3]:
            idf = sum(math.log(ix["n"] / (1 + ix["df"].get(t, 0))) for t in qt if t in ts)
            scored.append((idf + 0.5 * math.log1p(r[5] or 0), r))
    scored.sort(key=lambda x: -x[0])
    seen, booths = set(), []
    for _, r in scored:
        h = market._host(r[0])
        if h in seen:
            continue
        seen.add(h)
        booths.append(_booth(r))
        if len(booths) >= max(1, min(int(limit or 12), 12)):
            break
    try:
        import concurrent.futures
        import checkout
        def _v(b):
            try:
                sr = checkout.seller_record(b["booth"])
            except Exception:
                return None
            n = sr.get("purchases_closed", 0) + sr.get("seller_reported_sales_verified", 0)
            return {"purchases_checked": sr.get("purchases_closed", 0), "delivery_rate": sr.get("delivery_rate"),
                    "sales_verified": sr.get("seller_reported_sales_verified", 0)} if n else None
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            for b, v in zip(booths, ex.map(_v, booths)):
                b["omenz_verified"] = v
    except Exception:
        pass
    return {"query": q, "booths": booths, "more": "Full ranked results with live checks: GET /api/tollbooth/v1/market/find ($0.002)",
            "buy_safely": "Tell OMENZ the job: POST /api/tollbooth/v1/market/job ($0.01) -> working provider + verified history + a Guard request; then guard -> pay -> checkout/close"}


def bring_booth(d):
    d = d or {}
    url, method = str(d.get("url") or "").strip(), str(d.get("method") or "GET").upper()
    if not url.startswith("https://") or len(url) > 400:
        return 422, {"error": "url must be an https x402 endpoint"}
    if method not in ("GET", "POST"):
        return 422, {"error": "method must be GET or POST"}
    day = "swapmeet_day_" + time.strftime("%Y%m%d", time.gmtime())
    try:
        cnt = _kv("GET", day) or {"n": 0}
    except Exception:
        cnt = {"n": 0}
    if cnt["n"] >= SUBMIT_CAP:
        return 429, {"error": "the Swap Meet gate is closed for today; come back tomorrow"}
    q = x402_probe.quote(url, method)
    if q.get("status") != "quoted":
        return 422, {"accepted": False, "status": q.get("status"), "reason": q.get("reason") or "no x402 price found",
                     "fix": "Your endpoint must answer an unpaid request with HTTP 402 and x402 payment requirements."}
    booth = {"booth": market._host(url), "url": url, "method": method, "price_usd": q.get("cheapest_usd"),
             "what": str(d.get("what") or "")[:160], "networks": sorted({o.get("network") for o in q.get("options", []) if o.get("network")})[:3],
             "checked_at": q.get("checked_at"), "arrived": time.strftime("%Y-%m-%d", time.gmtime())}
    try:
        new = _kv("GET", "swapmeet_new") or {"booths": []}
        new["booths"] = [b for b in new["booths"] if b["url"] != url][-499:] + [booth]
        _kv("PUT", "swapmeet_new", new)
        cnt["n"] += 1
        _kv("PUT", day, cnt)
    except Exception:
        return 503, {"error": "storage unavailable; try again shortly"}
    acc = None
    try:  # 11-21: free Payment-Acceptance Check on the seller's own submitted route (normally $0.05)
        import acceptance
        r = acceptance.check(url, method)
        acc = {"verdict": r.get("verdict"), "problems": r.get("problems", []), "fixes": r.get("fixes", []),
               "note": "Free with your booth. Does your server refuse paying agents? Checked with an unfunded key (no money moves). "
                       "Re-check any time: POST /api/tollbooth/v1/seller/acceptance-check ($0.05)."}
    except Exception:
        acc = {"verdict": "UNAVAILABLE"}
    return 200, {"accepted": True, "booth": booth, "payment_acceptance": acc, "where": "NEW ARRIVALS at https://www.omenz.org/swapmeet/",
                 "tip": "Booths settled through the Coinbase CDP facilitator also show up in Coinbase's Bazaar / Agentic.Market."}


def new_arrivals():
    try:
        new = _kv("GET", "swapmeet_new") or {"booths": []}
    except Exception:
        new = {"booths": []}
    return {"new_arrivals": list(reversed(new["booths"][-50:]))}
