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
    evm = [(o.get("pay_to") or "").lower() for o in (q.get("options") or []) if str(o.get("pay_to") or "").lower().startswith("0x") and len(o.get("pay_to")) == 42]
    pt = (evm[0] if evm else None) or next((x for x in (r[8] if r and r[8] else []) if str(x).startswith("0x")), None)
    if pt:
        try:
            pi = payer_independence(pt)
            out["payer_independence"] = pi
            if pi["distinct_payers"] and pi["suspect_share"] is not None and pi["suspect_share"] >= 0.5:
                # informational, no score change: services that pay out by design (sends, refunds, rewards) overlap heavily too
                reasons.append(f"+0 NOTE: {pi['cycling_suspects']} of {pi['distinct_payers']} recent payers also received USDC from the payee: "
                               "normal for payout/send/refund services, a red flag for anything else")
            elif pi["distinct_payers"]:
                reasons.append(f"+0 {pi['independent_payers']} of {pi['distinct_payers']} payers in the last {pi['window_days']} days look independent")
        except Exception as e:
            out["payer_independence"] = {"error": f"unavailable ({type(e).__name__})"}
    grade = "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
    return {**out, "score": min(100, score), "grade": grade, "reasons": reasons,
            "limits": "Usage comes from the public Bazaar index (weekly); we can't see whether paid responses were correct. "
                      "Pair with Claim->Evidence / Acceptance checks on what you receive."}


def payer_independence(pay_to, days=2):
    """Who really pays this seller? (suggested by @flowexecutor on Threads, 11-17; built 11-21)
    Public Base data only: USDC transfers INTO pay_to vs transfers OUT of pay_to in the same window.
    A payer that also RECEIVED USDC from pay_to (or is pay_to) looks like the seller's own wallets cycling."""
    import wallet
    a = wallet._check(pay_to)
    head = int(wallet._rpc("eth_blockNumber", []), 16)
    start = head - int(days * 86400 / wallet.block_s())
    inc = wallet.logs_range({"address": wallet.USDC, "topics": [wallet.TRANSFER, None, wallet._topic(a)]}, start, head)
    out = wallet.logs_range({"address": wallet.USDC, "topics": [wallet.TRANSFER, wallet._topic(a)]}, start, head)
    payers = {("0x" + lg["topics"][1][-40:]).lower() for lg in inc}
    funded = {("0x" + lg["topics"][2][-40:]).lower() for lg in out}
    suspects = sorted((payers & funded) | ({a.lower()} & payers))
    indep = len(payers) - len(suspects)
    return {"window_days": days, "payments_in": len(inc), "distinct_payers": len(payers), "independent_payers": indep,
            "cycling_suspects": len(suspects), "suspect_share": round(len(suspects) / len(payers), 3) if payers else None,
            "method": "payer also received USDC from the payee in the window (or is the payee) = possible self-cycling",
            "read_with_care": "services that pay out by design (send, transfer, refund, reward, faucet) overlap heavily without any cycling"}


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


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = (len(sorted_vals) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo), 6)


def price_index(q, price_usd=None, url=None, min_payers=0):
    """x402 Price Index / Fair Price Check: the going rate for a capability across listed endpoints."""
    out = {"version": VERSION, "query": q, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    ix = _index()
    if url and not q:
        r, _ = _listing(url)
        if not r:
            return {**out, "error": "url not in the x402 index; give q (the capability) instead"}
        q = r[1]
        price_usd = price_usd if price_usd is not None else r[3]
        out["query"] = q[:160]
    qt = list(dict.fromkeys(_toks(q)))
    if not qt:
        return {**out, "error": "q (capability) required"}
    idf = {t: math.log(1 + ix["n"] / (1 + ix["df"].get(t, 0))) for t in qt}
    need = 0.67 if len(qt) >= 3 else 1.0
    rows = []
    for r, ts in zip(ix["rows"], ix["toks"]):
        if r[3] is None or r[3] <= 0:
            continue
        cover = sum(1 for t in qt if t in ts) / len(qt)
        if cover < need or (r[6] or 0) < int(min_payers or 0):
            continue
        rows.append((r, sum(idf[t] for t in qt if t in ts)))
    if len(rows) < 5:
        return {**out, "comparables": len(rows), "error": "fewer than 5 comparable priced endpoints; widen the query",
                "examples": [_row(r) for r, _ in rows]}
    prices = sorted(r[3] for r, _ in rows)
    used = sorted((r[3], r[6] or 0) for r, _ in rows if (r[6] or 0) > 0)
    wmed = None
    if used:
        tot, acc = sum(w for _, w in used), 0
        for p, w in used:
            acc += w
            if acc >= tot / 2:
                wmed = p
                break
    res = {**out, "index_generated_at": ix["generated_at"], "comparables": len(rows), "sellers": len({_host(r[0]) for r, _ in rows}),
           "min": prices[0], "p25": _pct(prices, 0.25), "median": _pct(prices, 0.5), "p75": _pct(prices, 0.75), "max": prices[-1],
           "usage_weighted_median": wmed, "examples": [_row(r) for r, _ in sorted(rows, key=lambda x: -(x[0][6] or 0))[:5]]}
    if price_usd is not None:
        p = float(price_usd)
        below = sum(1 for x in prices if x < p) / len(prices)
        res["your_price"] = p
        res["percentile"] = round(below * 100)
        res["verdict"] = "HIGH" if p > res["p75"] * 1.5 else "ABOVE_MARKET" if p > res["p75"] else "LOW" if p < res["p25"] else "FAIR"
    return res


def payee(addr):
    """Payee Check: is this pay-to address a known x402 seller, and which services pay out to it?"""
    a = (addr or "").strip().lower()
    out = {"version": VERSION, "address": a, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not re.match(r"^(0x[0-9a-f]{40}|[1-9a-hj-np-z]{32,44})$", a):
        return {**out, "error": "address must be an EVM 0x address or a Solana address"}
    import sanctions
    out["sanctions"] = sanctions.check(a)  # 11-20: OFAC SDN screen on every payee check
    ix = _index()
    hits = [r for r in ix["rows"] if a in (r[8] or [])]
    if not hits:
        return {**out, "verdict": "UNKNOWN", "index_generated_at": ix["generated_at"], "x402_endpoints": 0,
                "note": "No listed x402 service pays out to this address. Not proof of fraud, but confirm out of band before paying an unknown recipient."}
    hosts = {}
    for r in hits:
        h = _host(r[0])
        hosts.setdefault(h, {"host": h, "endpoints": 0, "calls_30d": 0, "payers_30d": 0, "example": r[0]})
        hosts[h]["endpoints"] += 1
        hosts[h]["calls_30d"] += r[5] or 0
        hosts[h]["payers_30d"] = max(hosts[h]["payers_30d"], r[6] or 0)
    hl = sorted(hosts.values(), key=lambda x: -x["calls_30d"])
    many = len(hl) > 3
    return {**out, "verdict": "KNOWN_SELLER" if not many else "SHARED_ADDRESS", "index_generated_at": ix["generated_at"],
            "x402_endpoints": len(hits), "services": hl[:10], "total_calls_30d": sum(h["calls_30d"] for h in hl),
            "note": ("Several unrelated services pay out here (a platform or facilitator wallet): check the endpoint, not just the address."
                     if many else "Address matches the listed payout of these services. Check the endpoint you're paying is one of them.")}


def report():
    """Weekly x402 Market Report: supply side of the agent-payment economy (what's for sale, prices, usage, concentration)."""
    ix = _index()
    rows = ix["rows"]
    priced = sorted(r[3] for r in rows if r[3])
    sellers = {}
    for r in rows:
        h = _host(r[0])
        s = sellers.setdefault(h, {"host": h, "endpoints": 0, "calls_30d": 0, "payers_30d": 0, "networks": set()})
        s["endpoints"] += 1
        s["calls_30d"] += r[5] or 0
        s["payers_30d"] = max(s["payers_30d"], r[6] or 0)
        s["networks"].update(r[4] or [])
    sl = sorted(sellers.values(), key=lambda s: -s["calls_30d"])
    total_calls = sum(s["calls_30d"] for s in sl) or 1
    active = [s for s in sl if s["calls_30d"] > 0]
    nets = {}
    for r in rows:
        for n in r[4] or []:
            nets[n] = nets.get(n, 0) + 1
    def pct(v, q):
        return v[min(len(v) - 1, int(q * len(v)))] if v else None
    return {"version": VERSION, "schema": "omenz.x402-market-report.v0", "index_generated_at": ix["generated_at"],
            "endpoints": len(rows), "sellers": len(sl), "sellers_with_calls_30d": len(active),
            "endpoints_with_calls_30d": sum(1 for r in rows if (r[5] or 0) > 0),
            "calls_30d": sum(r[5] or 0 for r in rows),
            "price_usd": {"p10": pct(priced, .1), "p25": pct(priced, .25), "median": pct(priced, .5), "p75": pct(priced, .75), "p90": pct(priced, .9)},
            "concentration": {"top10_sellers_share_of_calls": round(sum(s["calls_30d"] for s in sl[:10]) / total_calls, 3),
                              "top50_sellers_share_of_calls": round(sum(s["calls_30d"] for s in sl[:50]) / total_calls, 3)},
            "networks": dict(sorted(nets.items(), key=lambda kv: -kv[1])[:8]),
            "top_sellers": [{**{k: s[k] for k in ("host", "endpoints", "calls_30d", "payers_30d")}, "networks": sorted(s["networks"])[:4]} for s in sl[:25]],
            "source": "Coinbase CDP x402 Bazaar discovery index, compiled weekly by OMENZ; usage = listed 30-day calls/unique payers.",
            "limits": "Listed usage, not verified settlement; wash trading is not removed here. Pair with on-chain checks (wallet/spend, market/payee)."}


def sellers_list(q=None, min_payers=1, limit=100):
    """Seller lead list: x402 sellers (by capability) with endpoints, 30-day calls, unique payers, price range, example endpoint."""
    ix = _index()
    qt = list(dict.fromkeys(_toks(q))) if q else []
    agg = {}
    for r, ts in zip(ix["rows"], ix["toks"]):
        if qt and sum(1 for t in qt if t in ts) / len(qt) < 0.67:
            continue
        h = _host(r[0])
        a = agg.setdefault(h, {"host": h, "endpoints": 0, "calls_30d": 0, "payers_30d": 0, "min_price": None, "max_price": None,
                               "example": r[0], "example_desc": (r[1] or "")[:120], "last_called": ""})
        a["endpoints"] += 1
        a["calls_30d"] += r[5] or 0
        a["payers_30d"] = max(a["payers_30d"], r[6] or 0)
        if r[3]:
            a["min_price"] = r[3] if a["min_price"] is None else min(a["min_price"], r[3])
            a["max_price"] = r[3] if a["max_price"] is None else max(a["max_price"], r[3])
        a["last_called"] = max(a["last_called"], r[7] or "")
    out = sorted((a for a in agg.values() if a["payers_30d"] >= int(min_payers or 0)), key=lambda a: -a["calls_30d"])
    return {"version": VERSION, "query": q, "index_generated_at": ix["generated_at"], "sellers": len(out),
            "results": out[:max(1, min(int(limit or 100), 500))],
            "note": "Public listing data (hosts and endpoints sellers published to the x402 Bazaar). No personal data."}


def need_words(q, min_df=20, max_words=6):
    """What an agent was looking for, reduced to COMMON capability words (each appears in >= min_df public x402 listings).
    Addresses, numbers, keys, names and rare words are dropped by construction. Used for the 'what agents look for' report."""
    try:
        ix = _index()
    except Exception:
        return []
    out = []
    for t in dict.fromkeys(_toks(q or "")):
        if t.isdigit() or len(t) < 3 or len(t) > 24:
            continue
        if ix["df"].get(t, 0) >= min_df:
            out.append(t)
        if len(out) >= max_words:
            break
    return out
