"""OMENZ Track Record (free): what a buying agent checks before trusting a new seller.

Why (2026-11-15, Big Bro's "agent break room"): the buyer agent's objections were "Reputation? They're new. Usage
history? Not much. Then I'm watching." This answers with evidence instead of claims:
- per tool: release date, how it was tested (frozen holdout with a pre-registered gate, or release tests), version notes
- promises the code actually keeps (errors not charged, no guessing, nothing stored unless the route says so)
- an honest maturity note (new service, paid history just starting): no invented usage numbers
Live health is at /v1/status (real probes per request). Update HOLDOUTS when a new frozen test runs.

EARNED record (founder "track record go", 2026-11-15): trust from time and interactions. rollup() aggregates real
outside calls per tool per UTC day from the events log (test traffic excluded): calls, quoted (402), paid, completed
(paid + 2xx), server errors, median latency. Kept 365 days in KV "track_earned"; triggered daily by Vercel cron and
at most once an hour on demand. Starts at zero and grows only from real interactions.
"""
import json
import os
import time
import urllib.request

DATASET = "uO9teiO37CevrQOUy"
EARNED_KEY = "track_earned"

RELEASED = {
    "agent-ready": "2026-11-07", "site-check": "2026-11-07", "changed": "2026-11-07", "locker": "2026-11-11",
    "pobox": "2026-11-11", "receipt": "2026-11-11", "handoff": "2026-11-11", "local-facts": "2026-11-12",
}
DEFAULT_RELEASE = "2026-11-14"

HOLDOUTS = {
    "local-facts": {"test": "frozen holdout, v0.2.1, 2026-11-12", "gate": ">=95% of returned fields correct (precision first)",
                    "result": "PASS, ~98% precision; fields it can't back come back null"},
    "changed": {"test": "frozen holdout, v0.1.1, 157 URLs, t0 2026-10-27 -> t1 2026-10-31", "gate": "false UNCHANGED <=2%, accuracy >=90% (pre-registered, not softened)",
                "result": "PASS: 0 of 43 real changes missed; state accuracy 104/107 (97.2%); dynamic-but-same 68/69"},
    "site-check": {"test": "frozen holdout, 2026-10-20", "gate": "usable-vs-not >=95%, exact status >=90%",
                   "result": "PASS: 26/26 usable-vs-not, 25/26 exact status (96%)"},
    "agent-ready": {"test": "frozen holdouts, 2026-10-15", "gate": "pre-registered per version", "result": "passed before release; deterministic scoring, no AI calls"},
}

PROMISES = [
    "Errors are not charged: x402 settles only on success; 4xx/5xx responses are never settled.",
    "Precision first: fields we can't back are null with a reason, never guessed.",
    "Deterministic tools: no hidden AI calls unless a route says so.",
    "Nothing stored unless the route is a storage route (Locker, PO Box, Receipt, Ledger, Failure).",
    "Price changes are announced in /v1/pricing-policy before they take effect.",
    "Try before you buy: every route runs free in AYNE (/api/tollbooth/ayne/v1).",
]


def _kv(method, key, body=None):
    from locker import _kv as kv
    return kv(method, key, body)


def _events(since_ts):
    tok = os.environ.get("APIFY_LOG_TOKEN", "")
    out, off = [], 0
    while off < 80000:  # was 20000: truncated days once traffic passed ~10k/day (fixed 11-20)
        u = (f"https://api.apify.com/v2/datasets/{DATASET}/items?desc=1&limit=1000&offset={off}&clean=1"
             "&fields=key,ts,route,status,paid,latency_ms,ua_class")
        b = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "Bearer " + tok}), timeout=20))
        out += b
        off += len(b)
        if len(b) < 1000 or str(b[-1].get("ts", "")) < since_ts:
            break
    return [e for e in out if str(e.get("ts", "")) >= since_ts]


def _tool(route):
    r = str(route or "")
    return r.split("/v1/", 1)[1].split("/")[0].split("?")[0] if "/v1/" in r else None


def rollup(force=False, routes=None):
    rec = _kv("GET", EARNED_KEY) or {"days": {}, "rolled_at": 0}
    if not force and time.time() - rec.get("rolled_at", 0) < 3600:
        return {"rolled": False, "reason": "rolled up less than an hour ago", "days_recorded": len(rec["days"])}
    start = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 2 * 86400))
    days = {}
    for e in _events(start):
        if e.get("key") != "tollbooth" or e.get("ua_class") == "test":
            continue
        tool = _tool(e.get("route"))
        if not tool:
            continue
        d = days.setdefault(str(e["ts"])[:10], {}).setdefault(tool, {"calls": 0, "quoted": 0, "paid": 0, "completed": 0,
                                                                    "server_errors": 0, "lat": []})
        st = e.get("status") or 0
        d["calls"] += 1
        d["quoted"] += st == 402
        d["paid"] += bool(e.get("paid"))
        d["completed"] += bool(e.get("paid")) and 200 <= int(st) < 300
        d["server_errors"] += int(st) >= 500
        if e.get("latency_ms") is not None and int(st) in (200, 402):
            d["lat"].append(int(e["latency_ms"]))
    for day, tools in days.items():
        for t in tools.values():
            lat = sorted(t.pop("lat"))
            t["median_latency_ms"] = lat[len(lat) // 2] if lat else None
        rec["days"][day] = tools
    if routes:
        try:
            rec.setdefault("probes", {})[time.strftime("%Y-%m-%d", time.gmtime())] = self_probe(routes)
            rec["probes"] = dict(sorted(rec["probes"].items())[-365:])
        except Exception as e:
            rec["probe_error"] = str(e)[:160]
    rec["days"] = dict(sorted(rec["days"].items())[-365:])
    rec["rolled_at"] = int(time.time())
    _kv("PUT", EARNED_KEY, rec)
    return {"rolled": True, "days_updated": sorted(days), "days_recorded": len(rec["days"])}


def self_probe(routes, base="https://www.omenz.org"):
    """Daily self-probe (11-20): one UNPAID request per paid route. OK = HTTP 402 with a PAYMENT-REQUIRED header
    (the route is up and selling). Builds an uptime history even on days with no outside traffic."""
    from concurrent.futures import ThreadPoolExecutor
    def one(key):
        method, path = key.split(" ", 1)
        t0 = time.time()
        try:
            req = urllib.request.Request(base + path, method=method, data=(b"{}" if method == "POST" else None),
                                         headers={"Content-Type": "application/json", "User-Agent": "omenz-selfprobe/1"})
            urllib.request.urlopen(req, timeout=12)
            return _tool(path), False, int((time.time() - t0) * 1000), 200
        except urllib.error.HTTPError as e:
            return _tool(path), e.code == 402 and bool(e.headers.get("payment-required")), int((time.time() - t0) * 1000), e.code
        except Exception:
            return _tool(path), False, None, None
    out = {}
    with ThreadPoolExecutor(16) as ex:
        for tool, ok, ms, code in ex.map(one, [k for k in routes if "{" not in k]):
            if not tool:
                continue
            a = out.setdefault(tool, {"probes": 0, "ok": 0, "ms": []})
            a["probes"] += 1
            a["ok"] += ok
            if ms is not None:
                a["ms"].append(ms)
    for a in out.values():
        ms = sorted(a.pop("ms"))
        a["median_ms"] = ms[len(ms) // 2] if ms else None
    return out


def _earned():
    try:
        rec = _kv("GET", EARNED_KEY) or {"days": {}}
    except Exception:
        return {}, None
    cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
    per = {}
    for day, tools in rec["days"].items():
        for tool, t in tools.items():
            a = per.setdefault(tool, {"days_seen": 0, "calls_30d": 0, "quoted_30d": 0, "paid_30d": 0, "completed_30d": 0,
                                      "server_errors_30d": 0, "first_seen": day})
            a["first_seen"] = min(a["first_seen"], day)
            if day >= cut:
                a["days_seen"] += 1
                a["calls_30d"] += t["calls"]
                a["quoted_30d"] += t["quoted"]
                a["paid_30d"] += t["paid"]
                a["completed_30d"] += t["completed"]
                a["server_errors_30d"] += t["server_errors"]
    for a in per.values():
        a["success_rate_30d"] = round(1 - a["server_errors_30d"] / a["calls_30d"], 4) if a["calls_30d"] else None
        a["paid_success_rate_30d"] = round(a["completed_30d"] / a["paid_30d"], 4) if a["paid_30d"] else None
    for day, tools in (rec.get("probes") or {}).items():
        if day < cut:
            continue
        for tool, pr in tools.items():
            a = per.setdefault(tool, {"days_seen": 0, "calls_30d": 0, "quoted_30d": 0, "paid_30d": 0, "completed_30d": 0,
                                      "server_errors_30d": 0, "first_seen": day, "success_rate_30d": None, "paid_success_rate_30d": None})
            a["selfprobe_days_30d"] = a.get("selfprobe_days_30d", 0) + 1
            a["selfprobe_ok_days_30d"] = a.get("selfprobe_ok_days_30d", 0) + (pr["ok"] == pr["probes"])
            a["selfprobe_last_ms"] = pr.get("median_ms")
    return per, {"days_recorded": len(rec["days"]), "selfprobe_days": len(rec.get("probes") or {}), "first_day": min(rec["days"]) if rec["days"] else None,
                 "rolled_at": rec.get("rolled_at")}


def build(routes, base):
    tools = {}
    for key, cfg in routes.items():
        method, path = key.split(" ", 1)
        tool = path.split("/v1/", 1)[1].split("/")[0]
        t = tools.setdefault(tool, {"tool": tool, "routes": [], "released": RELEASED.get(tool, DEFAULT_RELEASE),
                                    "testing": HOLDOUTS.get(tool) or {"test": "release tests at launch (inputs incl. failure cases)",
                                                                     "result": "passed; no frozen holdout yet"}})
        t["routes"].append({"method": method, "path": path, "price": cfg["accepts"]["price"]})
    held = [t for t in tools.values() if t["tool"] in HOLDOUTS]
    earned, meta = _earned()
    for name, t in tools.items():
        t["earned"] = earned.get(name) or {"calls_30d": 0, "note": "no outside calls recorded yet"}
    return {"schema": "omenz.track-record.v0", "publisher": "OMENZ (omenz.org)", "price": "free",
            "maturity": "New service: first tools live 2026-11-07, most launched 2026-11-14. Paid usage history is just starting; "
                        "we publish test evidence instead of usage claims.",
            "summary": {"tools": len(tools), "paid_routes": len(routes), "tools_with_frozen_holdouts": len(held)},
            "earned_record": {**(meta or {}), "what": "Real outside calls per tool per UTC day (test traffic excluded): calls, quoted, paid, "
                              "completed, server errors, success rates. Grows only from real interactions; rolled up daily.",
                              "totals_30d": {k: sum(e.get(k, 0) for e in earned.values()) for k in
                                             ("calls_30d", "quoted_30d", "paid_30d", "completed_30d", "server_errors_30d")}},
            "promises": PROMISES, "live_status": base + "/v1/status", "try_free": base + "/ayne/v1",
            "pricing_policy": base + "/v1/pricing-policy", "contact": "hello@omenz.org",
            "tools": sorted(tools.values(), key=lambda t: (t["tool"] not in HOLDOUTS, t["tool"]))}
