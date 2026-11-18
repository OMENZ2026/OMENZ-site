"""OMENZ Facilitator Status + Router: which x402 facilitators are answering right now, what they settle, how fast.

Every x402 payment depends on a facilitator to verify and settle it. If the seller's facilitator is down, the sale fails
even though buyer and seller are both fine. This probes facilitators' public GET /supported (no payment, no key, no
settlement), parses the networks/schemes/x402 versions they claim, and recommends the fastest live one for the
network + scheme you need. Provider-neutral. Deterministic, no AI calls.
"""
import concurrent.futures
import json
import time
import urllib.request

import x402_probe

VERSION = "0.1.0"
KNOWN = {
    "x402.org (reference, testnet)": "https://x402.org/facilitator",
    "PayAI": "https://facilitator.payai.network",
    "x402.rs": "https://facilitator.x402.rs",
    "Coinbase CDP": "https://api.cdp.coinbase.com/platform/v2/x402",
    "Daydreams": "https://facilitator.daydreams.systems",
    "Dexter": "https://x402.dexter.cash",
    "Mogami": "https://facilitator.mogami.tech",
    "OpenX402": "https://facilitator.openx402.ai",
    "Corbits": "https://facilitator.corbits.dev",
    "thirdweb": "https://facilitator.thirdweb.com",
}
ALIASES = {"base": "eip155:8453", "base-sepolia": "eip155:84532", "ethereum": "eip155:1", "polygon": "eip155:137",
           "arbitrum": "eip155:42161", "optimism": "eip155:10", "avalanche": "eip155:43114",
           "solana": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "solana-devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"}


def _net(n):
    n = str(n or "").strip()
    return ALIASES.get(n.lower(), n.lower() if n.lower().startswith("eip155:") else n)


def _probe(name, base):
    out = {"name": name, "url": base, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    t0 = time.time()
    try:
        u = x402_probe._public_url(base.rstrip("/") + "/supported")
        req = urllib.request.Request(u, headers={"User-Agent": x402_probe.UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read(256 * 1024)
            code = r.status
    except urllib.error.HTTPError as e:
        code, body = e.code, b""
    except x402_probe.Refused as e:
        return {**out, "status": "refused", "reason": str(e)}
    except Exception as e:
        return {**out, "status": "down", "reason": type(e).__name__, "latency_ms": int((time.time() - t0) * 1000)}
    out["latency_ms"] = int((time.time() - t0) * 1000)
    out["http_status"] = code
    if code in (401, 403):
        return {**out, "status": "auth_required", "reason": "answers, but /supported needs an API key"}
    if code != 200:
        return {**out, "status": "down" if code >= 500 or code == 404 else "degraded", "reason": f"HTTP {code}"}
    try:
        d = json.loads(body)
    except Exception:
        return {**out, "status": "degraded", "reason": "/supported is not JSON"}
    kinds = []
    for k in (d.get("kinds") or [])[:400]:
        if isinstance(k, dict):
            kinds.append({"network": _net(k.get("network")), "scheme": k.get("scheme"), "x402_version": k.get("x402Version")})
    nets = sorted({k["network"] for k in kinds if k["network"]})
    return {**out, "status": "up" if kinds else "degraded", "kinds": len(kinds), "networks": nets,
            "schemes": sorted({k["scheme"] for k in kinds if k["scheme"]}), "x402_versions": sorted({k["x402_version"] for k in kinds if k["x402_version"]}),
            "_kinds": kinds, **({} if kinds else {"reason": "/supported lists no payment kinds"})}


def status(network=None, scheme=None, x402_version=None, extra_url=None):
    targets = dict(KNOWN)
    if extra_url:
        targets["(yours)"] = str(extra_url).strip()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as ex:
        res = list(ex.map(lambda kv: _probe(*kv), targets.items()))
    want_net, want_scheme = _net(network) if network else None, (scheme or "").strip().lower() or None
    try:
        want_ver = int(x402_version) if x402_version not in (None, "") else None
    except (TypeError, ValueError):
        want_ver = None
    fits = []
    for r in res:
        ks = r.pop("_kinds", [])
        if r["status"] != "up":
            continue
        m = [k for k in ks if (not want_net or k["network"] == want_net) and (not want_scheme or k["scheme"] == want_scheme)
             and (not want_ver or k["x402_version"] == want_ver)]
        r["fits_request"] = bool(m) if (want_net or want_scheme or want_ver) else None
        if m:
            fits.append(r)
    known_only = [r for r in res if r["name"] != "(yours)"]
    h = _record(known_only)
    hs = history_summary(h)
    for r in res:
        if r["name"] in hs:
            r["history"] = hs[r["name"]]
    # rank by live latency, but prefer facilitators with a better 7-day record when both are up
    fits.sort(key=lambda r: (-round((((r.get("history") or {}).get("uptime_7d")) or 0) / 0.05), r["latency_ms"]))
    up = sum(1 for r in res if r["status"] == "up")
    return {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False,
            "request": {"network": want_net, "scheme": want_scheme, "x402_version": want_ver},
            "recommended": {k: fits[0][k] for k in ("name", "url", "latency_ms")} if fits and (want_net or want_scheme or want_ver) else None,
            "fallbacks": [{k: f[k] for k in ("name", "url", "latency_ms")} for f in fits[1:4]] if (want_net or want_scheme or want_ver) else [],
            "up": up, "checked": len(res), "facilitators": sorted(res, key=lambda r: (r["status"] != "up", r.get("latency_ms") or 9e9)),
            "note": "Live probe of each facilitator's public GET /supported (claims, not settlement proof), plus OMENZ's own probe history (uptime_7d/30d). Pair with pay/verify to prove a settlement."}


# ---------------------------------------------------------------- history (the record accrues even without traffic)
HIST_KEY, HIST_MIN_GAP_S, HIST_MAX = "fac_history", 600, 1500


def _kv(method, key, body=None):
    from locker import _kv as kv
    return kv(method, key, body)


def _record(res, force=False):
    try:
        h = _kv("GET", HIST_KEY) or {"last": 0, "rows": {}}
        now = int(time.time())
        if not force and now - h.get("last", 0) < HIST_MIN_GAP_S:
            return h
        for r in res:
            rows = h["rows"].setdefault(r["name"], [])
            rows.append([now, r["status"], r.get("latency_ms")])
            h["rows"][r["name"]] = rows[-HIST_MAX:]
        h["last"] = now
        _kv("PUT", HIST_KEY, h)
        return h
    except Exception:
        return None


def _uptime(rows, days):
    cut = time.time() - days * 86400
    w = [r for r in rows if r[0] >= cut]
    if not w:
        return None, 0
    return round(sum(1 for r in w if r[1] == "up") / len(w), 3), len(w)


def history_summary(h):
    out = {}
    for name, rows in ((h or {}).get("rows") or {}).items():
        u7, n7 = _uptime(rows, 7)
        u30, n30 = _uptime(rows, 30)
        lat = sorted(r[2] for r in rows[-50:] if r[1] == "up" and r[2] is not None)
        out[name] = {"uptime_7d": u7, "checks_7d": n7, "uptime_30d": u30, "checks_30d": n30,
                     "median_latency_ms": lat[len(lat) // 2] if lat else None, "since": rows[0][0] if rows else None}
    return out


def snapshot():
    """Cron entry: probe all known facilitators and record the result (no throttle)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(KNOWN)) as ex:
        res = list(ex.map(lambda kv: _probe(*kv), KNOWN.items()))
    for r in res:
        r.pop("_kinds", None)
    _record(res, force=True)
    return {"recorded": len(res), "up": sum(1 for r in res if r["status"] == "up")}
