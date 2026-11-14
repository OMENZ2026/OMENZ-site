"""OMENZ Agent Capability Card: a standard, machine-readable card of what a paid agent service can do, what it
charges, what it needs, and how to call it.

Born from our own scar: 23 working paid routes, 0 outside calls, because agents couldn't find or understand them.
- own_card(routes): OMENZ's card, served free (distribution for us).
- card(url): build a card for ANY x402 service: a service index (JSON with routes/resources) or a single endpoint
  (we read its 402 payment requirements + Bazaar discovery extension; never pay).
Schema omenz.capability-card.v0. Deterministic, no AI calls.
"""
import base64
import hashlib
import json
import time

import x402_probe

VERSION = "0.1.0"
SCHEMA = "omenz.capability-card.v0"


def _digest(endpoints):
    return hashlib.sha256(json.dumps(endpoints, sort_keys=True).encode()).hexdigest()[:16]


def own_card(routes, base_url, policy_path, needs_path):
    eps = []
    for k, v in routes.items():
        method, path = k.split(" ", 1)
        ext = (v.get("extensions") or {}).get("bazaar", {}).get("info", {})
        eps.append({"method": method, "url": base_url + path, "price": v["accepts"]["price"], "network": v["accepts"]["network"],
                    "description": v.get("description"), "input_example": (ext.get("input") or {}).get("body") or
                    (ext.get("input") or {}).get("queryParams")})
    return {"schema": SCHEMA, "service": "OMENZ x402 tollbooth", "publisher": "OMENZ", "homepage": "https://omenz.org",
            "contact": "hello@omenz.org", "payment": {"protocol": "x402 v2", "asset": "USDC", "networks": sorted({e["network"] for e in eps}),
            "account_needed": False}, "pricing_policy": base_url + policy_path,
            "tell_us_what_you_need": base_url + needs_path, "endpoints": eps, "endpoint_count": len(eps),
            "digest": _digest(eps), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _ext_from_402(resp):
    h = resp["headers"].get("payment-required")
    if not h:
        try:
            return json.loads(resp["body"].decode("utf-8", "replace"))
        except Exception:
            return {}
    try:
        return json.loads(base64.b64decode(h + "=" * (-len(h) % 4)))
    except Exception:
        return {}


def card(url, method="GET"):
    out = {"schema": SCHEMA, "version": VERSION, "source_url": url, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "paid": False, "built_by": "OMENZ capability-card (third-party view: verify with the publisher)"}
    try:
        u = x402_probe._public_url(url)
    except x402_probe.Refused as e:
        return {**out, "status": "error", "error": str(e)}
    r = x402_probe._request(u, method)
    if r["status"] is None:
        return {**out, "status": "unreachable", "error": r["error"]}
    eps = []
    if r["status"] == 402:
        d = _ext_from_402(r)
        info = ((d.get("extensions") or {}).get("bazaar") or {}).get("info") or {}
        q = x402_probe.quote(url, method)
        res = d.get("resource")
        eps.append({"method": method.upper(), "url": (res.get("url") if isinstance(res, dict) else res) or u,
                    "description": (res.get("description") if isinstance(res, dict) else None) or
                    ((d.get("accepts") or [{}])[0].get("description")),
                    "price_usd": q.get("cheapest_usd"), "options": q.get("options"), "input_example": info.get("input"),
                    "output_example": info.get("output"), "live": True, "latency_ms": r["latency_ms"]})
        kind = "single_endpoint"
    elif r["status"] < 300:
        try:
            d = json.loads(r["body"].decode("utf-8", "replace"))
        except Exception:
            return {**out, "status": "not_a_service", "note": "page answered without a 402 or a JSON service index"}
        routes = d.get("routes") or d.get("resources") or d.get("items") or {}
        if isinstance(routes, dict):
            for k, v in list(routes.items())[:200]:
                m, _, p = k.partition(" ")
                eps.append({"method": m if p else "GET", "path": p or k, "price": (v or {}).get("price") if isinstance(v, dict) else None,
                            "description": (v or {}).get("description") if isinstance(v, dict) else None})
        elif isinstance(routes, list):
            for v in routes[:200]:
                if isinstance(v, dict):
                    eps.append({"url": v.get("resource") or v.get("url"), "description": v.get("description"),
                                "price_atomic": ((v.get("accepts") or [{}])[0]).get("amount")})
        if not eps:
            return {**out, "status": "not_a_service", "note": "JSON answered but lists no routes/resources"}
        kind = "service_index"
        out.update({"service": d.get("service") or d.get("name"), "network": d.get("network"), "about": d.get("about")})
    else:
        return {**out, "status": "no_card", "http_status": r["status"], "note": "no x402 requirements or service index here"}
    return {**out, "status": "ok", "kind": kind, "endpoints": eps, "endpoint_count": len(eps), "digest": _digest(eps)}
