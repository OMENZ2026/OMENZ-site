"""Uptime Watch (2026-11-15). Scout: "uptime monitor" = top under-served x402 niche (4 sellers, 44 payers/30d, median $0.01).
An agent registers an endpoint it depends on; OMENZ checks it daily (Vercel cron) and on every report read (if the last check
is >1h old), keeping a 30-day history: HTTP status, latency, x402 price + payTo (catches price drift / swapped payout wallets).

- watch(url, method, days)   -> watch_id + watch_key (shown once). $0.01 for up to 30 days.
- report(id, key)            -> uptime %, median latency, incidents, price/payTo changes, recent checks. $0.001.
- run_due(limit)             -> cron: check every active watch not checked in the last 20h.
Never pays the watched endpoint. Public https URLs only (x402_probe enforces).
"""
import hashlib
import hmac
import secrets
import time

import re

import x402_probe
from locker import LockerError, _kv

MAX_DAYS = 30
INDEX = "uptime_index"


def _kh(k):
    return hashlib.sha256(("omenz-uptime|" + k).encode()).hexdigest()


def _check(rec):
    q = x402_probe.quote(rec["url"], rec["method"])
    opt = (q.get("options") or [{}])[0]
    c = {"at": int(time.time()), "status": q.get("http_status"), "state": q.get("status"), "latency_ms": q.get("latency_ms"),
         "price_usd": q.get("cheapest_usd"), "pay_to": (opt.get("pay_to") or "").lower() or None}
    c["up"] = c["status"] is not None and (c["status"] == 402 or 200 <= int(c["status"]) < 400)
    res = q.get("resource")
    desc = (res.get("description") if isinstance(res, dict) else None) or ""
    if desc and not rec.get("desc"):
        rec["desc"] = desc[:300]
    rec["checks"] = (rec["checks"] + [c])[-200:]
    rec["last"] = c["at"]
    return c


def watch(url, method="GET", days=30):
    url = str(url or "").strip()
    if not url.startswith("https://"):
        raise LockerError(422, "url must be a public https endpoint")
    method = str(method or "GET").upper()
    if method not in ("GET", "POST", "HEAD"):
        raise LockerError(422, "method must be GET, POST or HEAD")
    try:
        days = max(1, min(int(days or MAX_DAYS), MAX_DAYS))
    except (TypeError, ValueError):
        raise LockerError(422, "days must be an integer 1-30")
    wid, key = "uw_" + secrets.token_hex(10), secrets.token_urlsafe(24)
    now = int(time.time())
    rec = {"url": url, "method": method, "key_hash": _kh(key), "created": now, "expires": now + days * 86400, "checks": [], "last": 0}
    first = _check(rec)
    _kv("PUT", wid, rec)
    try:
        idx = _kv("GET", INDEX) or {"ids": []}
        idx["ids"] = [i for i in idx["ids"] if i != wid][-4999:] + [wid]
        _kv("PUT", INDEX, idx)
    except Exception:
        pass
    return {"watch_id": wid, "watch_key": key, "url": url, "method": method, "expires_at": rec["expires"], "first_check": first,
            "report": "GET /api/tollbooth/v1/uptime/report?id=<watch_id> with header X-Watch-Key ($0.001)",
            "note": "watch_key is shown once. Checked daily, plus on each report if the last check is over an hour old."}


def _load(wid, key):
    if not (wid or "").startswith("uw_") or not key:
        raise LockerError(401, "id and X-Watch-Key header required")
    rec = _kv("GET", wid)
    if rec is None:
        raise LockerError(404, "no such watch")
    if not hmac.compare_digest(rec["key_hash"], _kh(key)):
        raise LockerError(403, "wrong watch key")
    return rec


def substitutes(rec, n=3):
    """Maintenance shop (2026-11-16): best live alternatives for a watched endpoint, from the ~35K x402 market index."""
    import market
    host = (re.match(r"https?://([^/]+)", rec["url"]) or [None, ""])[1]
    q = rec.get("desc") or rec["url"].rsplit("/", 1)[-1].replace("-", " ")
    try:
        r = market.find(q[:120], exclude=[host], limit=n, live_check=n)
    except Exception as e:
        return {"error": "market index unavailable", "detail": str(e)[:80]}
    return [{"url": x.get("url"), "what": (x.get("description") or "")[:100], "price_usd": x.get("price_usd"), "payers_30d": x.get("payers_30d") or x.get("unique_payers"),
             "live": x.get("live")} for x in (r.get("results") or [])[:n]]


def report(wid, key, subs=False):
    rec = _load(wid, key)
    if rec["expires"] > time.time() and time.time() - rec.get("last", 0) > 3600:
        _check(rec)
        _kv("PUT", wid, rec)
    cs = rec["checks"]
    up = [c for c in cs if c["up"]]
    lat = sorted(c["latency_ms"] for c in cs if c.get("latency_ms") is not None)
    incidents, prices, payees = [], [], []
    for a, b in zip(cs, cs[1:]):
        if a["up"] and not b["up"]:
            incidents.append({"down_at": b["at"], "status": b["status"], "state": b["state"]})
        if a.get("price_usd") is not None and b.get("price_usd") is not None and a["price_usd"] != b["price_usd"]:
            prices.append({"at": b["at"], "from": a["price_usd"], "to": b["price_usd"]})
        if a.get("pay_to") and b.get("pay_to") and a["pay_to"] != b["pay_to"]:
            payees.append({"at": b["at"], "from": a["pay_to"], "to": b["pay_to"], "warning": "payout wallet changed: verify before paying"})
    return {"watch_id": wid, "url": rec["url"], "method": rec["method"], "checks": len(cs),
            "uptime_pct": round(100 * len(up) / len(cs), 2) if cs else None,
            "median_latency_ms": lat[len(lat) // 2] if lat else None, "incidents": incidents[-20:], "price_changes": prices[-20:],
            "payto_changes": payees[-20:], "current": cs[-1] if cs else None, "recent": cs[-10:][::-1],
            "active": rec["expires"] > time.time(), "expires_at": rec["expires"],
            **({"substitutes": substitutes(rec)} if (subs or (cs and not cs[-1]["up"])) else {})}


def run_due(limit=60):
    idx = _kv("GET", INDEX) or {"ids": []}
    now, done, keep = time.time(), 0, []
    for wid in idx["ids"]:
        rec = _kv("GET", wid)
        if not rec or rec["expires"] < now:
            continue
        keep.append(wid)
        if done < limit and now - rec.get("last", 0) > 20 * 3600:
            try:
                _check(rec)
                _kv("PUT", wid, rec)
                done += 1
            except Exception:
                pass
    if len(keep) != len(idx["ids"]):
        _kv("PUT", INDEX, {"ids": keep})
    return {"checked": done, "active_watches": len(keep)}
