"""OMENZ Agent Market tools over the x402 Bazaar index (~35k paid endpoints, refreshed weekly by OMENZ).

- find(q, ...)        Capability Finder / Procurement Desk / Quote Comparator / Tool Substitute (exclude=) /
                      Rate-Limit Router (exclude= the throttled one): ranked by relevance, then real usage
                      (30-day calls and unique payers), filtered by max price and network; optional live check of the top picks.
- reliability(url)    Micropayment Reliability Score: listing usage + a live unpaid probe (answers? valid 402? live
                      price == listed? payTo == listed?) -> 0-100 with every reason.
- vendor(url)         Vendor Due-Diligence Pack: reliability + site-check of the vendor's domain + terms digest + card.
Deterministic, no AI calls. Never pays a target.
"""
import gzip
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request

import x402_probe

VERSION = "0.1.0"
STORE = os.environ.get("LOCKER_KV_STORE", "VRiqBigG65b1Aeb1H")
STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "by", "with", "api", "get", "data", "service", "tool",
        "endpoint", "x402", "pay", "per", "call", "request", "my", "i", "need", "want", "agent", "agents", "that", "this"}
_idx = {"at": 0, "data": None}


def _index():
    if _idx["data"] and time.time() - _idx["at"] < 3600:
        return _idx["data"]
    tok = os.environ.get("APIFY_LOG_TOKEN", "")
    req = urllib.request.Request(f"https://api.apify.com/v2/key-value-stores/{STORE}/records/market_index",
                                 headers={"Authorization": "Bearer " + tok})
    raw = urllib.request.urlopen(req, timeout=20).read()
    try:
        d = json.loads(gzip.decompress(raw))
    except OSError:
        d = json.loads(raw)
    rows = d["rows"]
    toks = [set(_toks(r[1] + " " + urllib.parse.urlparse(r[0] or "").path.replace("/", " ").replace("-", " "))) for r in rows]
    df = {}
    for ts in toks:
        for t in ts:
            df[t] = df.get(t, 0) + 1
    _idx.update(at=time.time(), data={"generated_at": d["generated_at"], "rows": rows, "toks": toks, "df": df, "n": len(rows)})
    return _idx["data"]


def _toks(s):
    return [t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP and len(t) > 1]


def _host(u):
    return (urllib.parse.urlparse(u or "").hostname or "").lower()


def _row(r):
    return {"url": r[0], "description": r[1], "method": r[2], "price_usd": r[3], "networks": r[4], "calls_30d": r[5],
            "payers_30d": r[6], "last_called": r[7] or None}


def find(q, max_price_usd=None, network=None, exclude=None, limit=10, live_check=3, min_payers=0):
    out = {"version": VERSION, "query": q, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False}
    qt = list(dict.fromkeys(_toks(q)))
    if not qt:
        return {**out, "error": "describe the capability you need (e.g. 'weather forecast by city', 'company enrichment by domain')"}
    try:
        cap = float(max_price_usd) if max_price_usd not in (None, "") else None
        limit = max(1, min(int(limit or 10), 25))
        live_check = max(0, min(int(live_check or 0), 5))
        min_payers = int(min_payers or 0)
    except (TypeError, ValueError):
        return {**out, "error": "max_price_usd must be a number; limit/live_check/min_payers integers"}
    ix = _index()
    net = (network or "").strip().lower()
    nets = {"base": "eip155:8453", "solana": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "polygon": "eip155:137", "arbitrum": "eip155:42161"}
    want_net = nets.get(net, net) or None
    ex = {_host(e) for e in (exclude if isinstance(exclude, list) else [exclude] if exclude else [])} - {""}
    idf = {t: math.log(1 + ix["n"] / (1 + ix["df"].get(t, 0))) for t in qt}
    scored = []
    for r, ts in zip(ix["rows"], ix["toks"]):
        rel = sum(idf[t] for t in qt if t in ts)
        if rel <= 0:
            continue
        cover = sum(1 for t in qt if t in ts) / len(qt)
        if cover < 0.5:
            continue
        if cap is not None and (r[3] is None or r[3] > cap + 1e-12):
            continue
        if want_net and want_net not in (r[4] or []):
            continue
        if ex and _host(r[0]) in ex:
            continue
        if (r[6] or 0) < min_payers:
            continue
        usage = math.log10(1 + (r[5] or 0)) + 2 * math.log10(1 + (r[6] or 0))
        scored.append((rel / sum(idf.values()) * 10 + usage, cover, r))
    scored.sort(key=lambda x: -x[0])
    seen_hosts, picks = {}, []
    for s, cover, r in scored:  # at most 2 per host so one vendor's 40 routes don't drown the list
        h = _host(r[0])
        if seen_hosts.get(h, 0) >= 2:
            continue
        seen_hosts[h] = seen_hosts.get(h, 0) + 1
        picks.append({**_row(r), "match": round(cover, 2)})
        if len(picks) >= limit:
            break
    for p in picks[:live_check]:
        q2 = x402_probe.quote(p["url"], p["method"])
        p["live"] = {"status": q2["status"], "price_usd": q2.get("cheapest_usd"), "latency_ms": q2.get("latency_ms")}
        if q2.get("cheapest_usd") is not None and p["price_usd"] is not None and abs(q2["cheapest_usd"] - p["price_usd"]) > 1e-9:
            p["live"]["price_drift"] = True
    priced = [p for p in picks if p["price_usd"] is not None]
    return {**out, "index_generated_at": ix["generated_at"], "matches_total": len(scored), "results": picks,
            "cheapest": min(priced, key=lambda p: p["price_usd"])["url"] if priced else None,
            "most_used": max(picks, key=lambda p: p["payers_30d"])["url"] if picks else None,
            "note": "ranked by match, then real 30-day usage; 'live' = unpaid probe just now"}


def _listing(url):
    ix = _index()
    u = (url or "").split("?")[0].rstrip("/")
    for r in ix["rows"]:
        if (r[0] or "").split("?")[0].rstrip("/") == u:
            return r, ix["generated_at"]
    return None, ix["generated_at"]


def reliability(url, method=None):
    out = {"version": VERSION, "url": url, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False}
    r, gen = _listing(url)
    method = method or (r[2] if r else "GET")
    reasons, score = [], 0
    if r:
        out["listing"] = {**_row(r), "index_generated_at": gen}
        c, p = r[5] or 0, r[6] or 0
        u = min(40, round(10 * math.log10(1 + p) + 5 * math.log10(1 + c)))
        score += u
        reasons.append(f"+{u} usage: {c} calls / {p} unique payers in 30 days")
    else:
        reasons.append("+0 not in the x402 Bazaar index (no public usage record)")
    q = x402_probe.quote(url, method)
    out["live"] = {"status": q["status"], "http_status": q.get("http_status"), "latency_ms": q.get("latency_ms"), "price_usd": q.get("cheapest_usd")}
    if q["status"] == "quoted":
        score += 30
        reasons.append("+30 answers now with valid x402 payment requirements")
        if q.get("latency_ms", 99999) < 2000:
            score += 10
            reasons.append(f"+10 fast ({q['latency_ms']} ms)")
        if r and r[3] is not None and q.get("cheapest_usd") is not None:
            if abs(q["cheapest_usd"] - r[3]) < 1e-9:
                score += 10
                reasons.append("+10 live price matches the listing")
            else:
                reasons.append(f"+0 price drift: live ${q['cheapest_usd']:g} vs listed ${r[3]:g}")
        if r and r[8]:
            live_pay = {(o.get("pay_to") or "").lower() for o in q.get("options") or []}
            if live_pay & set(r[8]):
                score += 10
                reasons.append("+10 pays the same address as listed")
            else:
                reasons.append("+0 WARNING: live payTo differs from the listing")
    else:
        reasons.append(f"+0 not taking payment right now ({q['status']}: {q.get('reason')})")
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    return {**out, "score": min(100, score), "grade": grade, "reasons": reasons,
            "limits": "Usage comes from the public Bazaar index (weekly); we can't see whether paid responses were correct. "
                      "Pair with Claim->Evidence / Acceptance checks on what you receive."}


def vendor(url, method=None):
    import site_check
    import terms_changed
    rel = reliability(url, method)
    host = _host(url)
    sc = site_check.check("https://" + host) if host else {"status": "invalid_url"}
    terms = None
    for path in ("/terms", "/pricing", "/legal/terms", "/tos"):
        t = terms_changed.check(f"https://{host}{path}")
        if t.get("state") == "NEW" and t.get("material_lines", 0) >= 3:
            terms = {"url": t["final_url"], "material_lines": t["material_lines"], "last_updated_stated": t.get("last_updated_stated"),
                     "sample": t.get("sample", [])[:6], "fingerprint": t["fingerprint"]}
            break
    flags = []
    if sc.get("status") not in ("live",):
        flags.append(f"vendor domain status: {sc.get('status')}")
    if not terms:
        flags.append("no readable terms/pricing page found")
    if rel["score"] < 40:
        flags.append(f"low reliability score {rel['score']}")
    return {"version": VERSION, "url": url, "vendor_host": host, "checked_at": rel["checked_at"], "reliability": rel,
            "domain": {k: sc.get(k) for k in ("status", "final_url", "title", "phone", "notes", "next_action")},
            "terms": terms, "flags": flags, "verdict": "OK" if not flags else "REVIEW"}
