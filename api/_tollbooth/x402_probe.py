"""OMENZ x402 probes: Proof-of-Life, Price Quote and Transaction Preflight for machine-payable endpoints.

Born from our own scar (2026-11-12): before the first real Bazaar listing payments we had to hand-check, per route,
that the endpoint answered, that the quoted price was what we expected, that the money went to the right address on
the right network, and that the total stayed under budget. These routes sell that check to any agent.

Probes are UNPAID requests: we read the endpoint's 402 payment requirements and never sign or pay anything.
Deterministic, no AI calls. Public hosts only (private/loopback addresses are refused).

  alive(url, method)              -> up / paywalled / auth_required / not_found / degraded / down
  quote(url, method)              -> normalized payment options (USD price, network, asset, payTo, scheme)
  preflight(url, method, max_price_usd, expected_pay_to, networks, listed_price_usd) -> GO / STOP + reasons
"""
import base64
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
UA = "OMENZ-x402-probe/0.1 (+https://omenz.org/agents; unpaid probe, never pays)"
TIMEOUT = 12
SLOW_MS = 5000

NETWORKS = {
    "eip155:8453": "base", "base": "base", "eip155:84532": "base-sepolia", "base-sepolia": "base-sepolia",
    "eip155:1": "ethereum", "ethereum": "ethereum", "eip155:137": "polygon", "polygon": "polygon",
    "eip155:42161": "arbitrum", "arbitrum": "arbitrum", "eip155:43114": "avalanche", "avalanche": "avalanche",
    "eip155:10": "optimism", "optimism": "optimism",
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "solana", "solana": "solana",
    "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1": "solana-devnet", "solana-devnet": "solana-devnet",
}
TESTNETS = {"base-sepolia", "solana-devnet"}
# (network, asset address lowercased) -> (symbol, decimals); USD stablecoins only, priced 1:1
ASSETS = {
    ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): ("USDC", 6),
    ("base-sepolia", "0x036cbd53842c5426634e7929541ec2318f3dcf7e"): ("USDC", 6),
    ("ethereum", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): ("USDC", 6),
    ("polygon", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"): ("USDC", 6),
    ("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"): ("USDC", 6),
    ("avalanche", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"): ("USDC", 6),
    ("optimism", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"): ("USDC", 6),
    ("solana", "epjfwdd5aufqssqem2qn1xzybapc8g4wegGkzwytdt1v".lower()): ("USDC", 6),
    ("solana-devnet", "4zmmc9srt5ri5x14gagxhahii3gnpaeerypjgzjdncdu"): ("USDC", 6),
}


class Refused(Exception):
    pass


def _public_url(url):
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    host = p.hostname
    if not host or "." not in host:
        raise Refused("invalid_url")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise Refused("dns_failed")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise Refused("private_address")
    return u


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _request(url, method="GET"):
    """One unpaid request. Returns status, headers, body (<=64 KB), latency, error. Redirects are reported, not followed."""
    method = (method or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"):
        method = "GET"
    data = b"{}" if method in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(_NoRedirect)
    t0 = time.time()
    try:
        r = opener.open(req, timeout=TIMEOUT)
        status, headers, body = r.status, dict(r.headers), r.read(65536)
    except urllib.error.HTTPError as e:
        status, headers = e.code, dict(e.headers or {})
        try:
            body = e.read(65536)
        except Exception:
            body = b""
    except Exception as e:
        return {"status": None, "headers": {}, "body": b"", "latency_ms": int((time.time() - t0) * 1000),
                "error": type(e).__name__ + (": " + str(e)[:120] if str(e) else "")}
    return {"status": status, "headers": {k.lower(): v for k, v in headers.items()}, "body": body,
            "latency_ms": int((time.time() - t0) * 1000), "error": None}


def _requirements(resp):
    """Payment requirements from a 402: x402 v2 'payment-required' header (base64 JSON) or v1 JSON body."""
    h = resp["headers"].get("payment-required")
    if h:
        try:
            d = json.loads(base64.b64decode(h + "=" * (-len(h) % 4)))
            return d.get("x402Version", 2), d.get("accepts") or [], d.get("resource"), "header"
        except Exception:
            pass
    try:
        d = json.loads(resp["body"].decode("utf-8", "replace"))
        if isinstance(d, dict) and isinstance(d.get("accepts"), list):
            return d.get("x402Version", 1), d["accepts"], d.get("resource"), "body"
    except Exception:
        pass
    return None, [], None, None


def _normalize(a):
    net_raw = a.get("network") or ""
    net = NETWORKS.get(net_raw, net_raw or None)
    asset = (a.get("asset") or "")
    known = ASSETS.get((net, asset.lower()))
    atomic = a.get("amount") if a.get("amount") is not None else a.get("maxAmountRequired")
    usd = None
    if known and atomic is not None:
        try:
            usd = int(str(atomic)) / 10 ** known[1]
        except ValueError:
            usd = None
    return {"scheme": a.get("scheme"), "network": net, "network_id": net_raw, "testnet": net in TESTNETS,
            "asset": asset or None, "asset_symbol": known[0] if known else ((a.get("extra") or {}).get("name") or None),
            "asset_known": bool(known), "amount_atomic": str(atomic) if atomic is not None else None,
            "price_usd": usd, "pay_to": a.get("payTo"), "max_timeout_seconds": a.get("maxTimeoutSeconds"),
            "description": (a.get("description") or "")[:300] or None}


def _probe(url, method):
    try:
        u = _public_url(url)
    except Refused as e:
        return None, {"error": str(e)}
    return u, _request(u, method)


def _base(url, method):
    return {"url": url, "method": (method or "GET").upper(), "version": VERSION,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid": False}


def alive(url, method="GET"):
    out = _base(url, method)
    u, r = _probe(url, method)
    if u is None:
        v = {"invalid_url": "invalid", "private_address": "refused"}.get(r["error"], "down")
        return {**out, "verdict": v, "reason": r["error"]}
    out.update({"http_status": r["status"], "latency_ms": r["latency_ms"]})
    s = r["status"]
    if s is None:
        tls = "CERTIFICATE" in (r["error"] or "") or "SSL" in (r["error"] or "")
        return {**out, "verdict": "tls_error" if tls else "down", "reason": r["error"]}
    if s == 402:
        ver, accepts, _, where = _requirements(r)
        if accepts:
            out.update({"verdict": "paywalled", "x402_version": ver, "payment_options": len(accepts), "requirements_in": where,
                        "reason": "answers with valid x402 payment requirements (ready to take payment)"})
        else:
            out.update({"verdict": "degraded", "reason": "returns 402 but no readable x402 payment requirements"})
    elif 200 <= s < 300:
        out.update({"verdict": "up", "reason": "answered without asking for payment"})
    elif 300 <= s < 400:
        out.update({"verdict": "up", "reason": "redirects", "redirect_to": r["headers"].get("location")})
    elif s in (401, 403):
        out.update({"verdict": "auth_required", "reason": "needs credentials (not an x402 paywall)"})
    elif s in (404, 410):
        out.update({"verdict": "not_found", "reason": "endpoint missing at this URL/method"})
    elif s in (405,):
        out.update({"verdict": "wrong_method", "reason": "server is up but this HTTP method isn't accepted",
                    "allow": r["headers"].get("allow")})
    elif s == 429:
        out.update({"verdict": "degraded", "reason": "rate limited right now", "retry_after": r["headers"].get("retry-after")})
    elif s >= 500:
        out.update({"verdict": "down", "reason": f"server error {s}"})
    else:
        out.update({"verdict": "degraded", "reason": f"unexpected status {s}"})
    if out["verdict"] in ("up", "paywalled") and r["latency_ms"] > SLOW_MS:
        out["slow"] = True
        out["reason"] += f"; slow ({r['latency_ms']} ms)"
    return out


def quote(url, method="GET"):
    out = _base(url, method)
    u, r = _probe(url, method)
    if u is None:
        return {**out, "status": "error", "reason": r["error"], "options": []}
    out.update({"http_status": r["status"], "latency_ms": r["latency_ms"]})
    if r["status"] is None:
        return {**out, "status": "unreachable", "reason": r["error"], "options": []}
    if r["status"] != 402:
        return {**out, "status": "no_payment_requested" if r["status"] < 400 else "no_quote",
                "reason": f"HTTP {r['status']}, no x402 payment requirements", "options": []}
    ver, accepts, resource, where = _requirements(r)
    if not accepts:
        return {**out, "status": "malformed", "reason": "402 without readable x402 requirements", "options": []}
    opts = [_normalize(a) for a in accepts[:12] if isinstance(a, dict)]
    priced = [o for o in opts if o["price_usd"] is not None]
    return {**out, "status": "quoted", "x402_version": ver, "requirements_in": where,
            "resource": resource if isinstance(resource, (str, dict)) else None,
            "cheapest_usd": min(o["price_usd"] for o in priced) if priced else None,
            "options": opts,
            "note": None if priced else "no option uses a USD stablecoin we recognize; price shown in atomic units only"}


def preflight(url, method="GET", max_price_usd=None, expected_pay_to=None, networks=None, listed_price_usd=None,
              allow_testnet=False):
    q = quote(url, method)
    out = {**{k: q.get(k) for k in ("url", "method", "version", "checked_at", "paid", "http_status", "latency_ms")}}
    stops, warns = [], []
    if q["status"] == "no_payment_requested":
        return {**out, "verdict": "GO", "chosen": None, "reasons": ["endpoint answered without asking for payment"],
                "warnings": [], "options_checked": 0}
    if q["status"] != "quoted":
        return {**out, "verdict": "STOP", "chosen": None, "reasons": [f"no usable quote: {q.get('reason')}"],
                "warnings": [], "options_checked": 0}
    want_nets = {NETWORKS.get(n, n) for n in (networks or [])}
    pay_to = (expected_pay_to or "").strip().lower() or None
    ok, rejected = [], []
    for o in q["options"]:
        why = []
        if o["scheme"] not in ("exact", "upto"):
            why.append(f"scheme {o['scheme']!r} not understood")
        if want_nets and o["network"] not in want_nets:
            why.append(f"network {o['network']} not in allowed {sorted(want_nets)}")
        if o["testnet"] and not allow_testnet:
            why.append(f"testnet {o['network']}")
        if not o["asset_known"]:
            why.append("asset is not a recognized USD stablecoin")
        if max_price_usd is not None and o["price_usd"] is not None and o["price_usd"] > float(max_price_usd) + 1e-12:
            why.append(f"price ${o['price_usd']:g} over budget ${float(max_price_usd):g}")
        if pay_to and (o["pay_to"] or "").lower() != pay_to:
            why.append(f"pays {o['pay_to']}, not the expected recipient")
        (rejected if why else ok).append((o, why))
    if max_price_usd is None:
        warns.append("no max_price_usd given: budget not checked")
    if not pay_to:
        warns.append("no expected_pay_to given: recipient not checked")
    if q.get("latency_ms", 0) > SLOW_MS:
        warns.append(f"endpoint slow to answer ({q['latency_ms']} ms)")
    if not ok:
        stops = sorted({w for _, why in rejected for w in why})
        return {**out, "verdict": "STOP", "chosen": None, "reasons": stops, "warnings": warns,
                "options_checked": len(q["options"]), "rejected": [{"option": o, "why": why} for o, why in rejected[:6]]}
    chosen = min(ok, key=lambda t: t[0]["price_usd"])[0]
    if listed_price_usd is not None and chosen["price_usd"] is not None:
        lp = float(listed_price_usd)
        if abs(chosen["price_usd"] - lp) > max(1e-9, lp * 0.001):
            warns.append(f"price drift: live ${chosen['price_usd']:g} vs listed ${lp:g}")
    return {**out, "verdict": "GO", "chosen": chosen, "reasons": ["all checks passed for the chosen option"],
            "warnings": warns, "options_checked": len(q["options"])}


if __name__ == "__main__":
    import sys
    fn = {"alive": alive, "quote": quote, "preflight": preflight}[sys.argv[1]]
    print(json.dumps(fn(*sys.argv[2:]), indent=2))
