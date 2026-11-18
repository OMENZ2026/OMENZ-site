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
    fits.sort(key=lambda r: r["latency_ms"])
    up = sum(1 for r in res if r["status"] == "up")
    return {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False,
            "request": {"network": want_net, "scheme": want_scheme, "x402_version": want_ver},
            "recommended": {k: fits[0][k] for k in ("name", "url", "latency_ms")} if fits and (want_net or want_scheme or want_ver) else None,
            "fallbacks": [{k: f[k] for k in ("name", "url", "latency_ms")} for f in fits[1:4]] if (want_net or want_scheme or want_ver) else [],
            "up": up, "checked": len(res), "facilitators": sorted(res, key=lambda r: (r["status"] != "up", r.get("latency_ms") or 9e9)),
            "note": "Live probe of each facilitator's public GET /supported (claims, not settlement proof). Pair with pay/verify to prove a settlement."}
