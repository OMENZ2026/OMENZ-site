"""AYNE: the OMENZ agent Playzone (founder 2026-11-14: "AYNE go, cap 2000 requests/day").

Agents explore every OMENZ tool for free, with no prescribed outcome, at /api/tollbooth/ayne/v1/<route>.
- LIVE in AYNE: tools that only compute on the agent's own input, or keep the agent's own state (Locker, PO Box,
  Ledger, Workforce queue, Failure, Dedupe, Passport, Contracts...). The real code runs, size/TTL limited, marked ayne.
- SAMPLE in AYNE: tools that would hand out OMENZ data or fetch the web for the caller (facts, market, checks, finance
  probes): a labeled sample response showing exactly what the paid route returns, plus the paid URL.
- Unknown routes: 404 + logged as a GAP signal (the strongest one: what agents reach for that we don't sell).
Caps: 2000 requests/day total, 300/day per visitor (visitor = daily one-way hash; IPs never stored).
Observation log (Apify events dataset, key="ayne"): route, method, live|sample|gap|capped, status, top-level field NAMES
(never values), visitor hash, UA class. Read at KETCHUP by scripts/needs_report.py.
"""
import hashlib
import json
import os
import time
import urllib.request

DAILY_CAP, VISITOR_CAP = 2000, 300
MAX_BODY = 8 * 1024
LIVE = {
    "POST /secret-scan", "POST /spend-gate", "POST /cost-estimate", "POST /context-diet", "POST /finance/forecast",
    "POST /contract/build", "POST /contract/accept", "POST /evidence/bundle", "POST /passport/issue", "POST /passport/check",
    "POST /locker/put", "GET /locker/get", "POST /pobox/create", "POST /pobox/drop", "GET /pobox/inbox", "POST /handoff/pack",
    "POST /ledger/create", "POST /ledger/append", "GET /ledger/get", "POST /failure/put", "POST /dedupe",
    "POST /queue/create", "POST /queue/enqueue", "POST /queue/claim", "POST /queue/heartbeat", "POST /queue/complete",
    "POST /queue/fail", "POST /queue/escalate", "POST /queue/resolve", "POST /queue/bid", "POST /queue/award", "GET /queue/status",
}
_fx = None
_count = {"day": None, "total": 0, "v": {}}


def fixtures():
    global _fx
    if _fx is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ayne_fixtures.json"), encoding="utf-8") as f:
            _fx = json.load(f)
    return _fx


def _kv(method, key, body=None):
    from locker import _kv as kv
    return kv(method, key, body)


def visitor(ip, ua):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return hashlib.sha256(f"ayne|{ip}|{(ua or '')[:200]}|{day}|{os.environ.get('APIFY_LOG_TOKEN', '')[:8]}".encode()).hexdigest()[:16]


def take(vis):
    """Count one request against the caps. Shared counter in KV (approximate under bursts; local copy as fallback)."""
    day = time.strftime("%Y%m%d", time.gmtime())
    key = "ayne_day_" + day
    try:
        rec = _kv("GET", key) or {"total": 0, "v": {}}
    except Exception:
        rec = None
    if rec is None:  # storage down: fall back to this instance's own count
        if _count["day"] != day:
            _count.update(day=day, total=0, v={})
        rec = _count
    if rec["total"] >= DAILY_CAP:
        return False, "daily", rec["total"]
    if rec["v"].get(vis, 0) >= VISITOR_CAP:
        return False, "visitor", rec["v"][vis]
    rec["total"] += 1
    rec["v"][vis] = rec["v"].get(vis, 0) + 1
    if rec is not _count:
        try:
            _kv("PUT", key, rec)
        except Exception:
            pass
    return True, None, rec["total"]


def log(ev):
    tok = os.environ.get("APIFY_LOG_TOKEN", "")
    if not tok:
        return
    try:
        req = urllib.request.Request("https://api.apify.com/v2/datasets/uO9teiO37CevrQOUy/items", data=json.dumps(ev).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception as e:
        print("ayne-log-failed", e)


def field_names(raw):
    try:
        d = json.loads(raw or b"{}")
    except Exception:
        return []
    return sorted(d.keys())[:30] if isinstance(d, dict) else ["<list>"]


def index(paid_routes, base):
    live = sorted(LIVE)
    sample = sorted(k.replace(base + "/v1", "", 1) for k in paid_routes if k.replace(base + "/v1", "", 1) not in LIVE)
    return {"service": "AYNE, the OMENZ agent Playzone", "price": "free", "caps": {"per_day_total": DAILY_CAP, "per_visitor_per_day": VISITOR_CAP},
            "how": f"Call any route at {base}/ayne/v1/<route> exactly as you would the paid route (same method, params, body). "
                   "No payment, no account, no expectations: try things, chain tools, see what's missing.",
            "live_routes": live, "sample_routes": sample,
            "notes": ["LIVE = the real tool runs on your own input or keeps your own sandbox state (small limits, 1-day lockers).",
                      "SAMPLE = a labeled example of what the paid route returns (OMENZ data and web checks stay paid).",
                      "Anything you try that we don't have is noted as a gap. Tell us directly: POST " + base + "/v1/needs."],
            "paid_versions": base, "privacy": "We record which routes and field names agents use, never field values or IPs."}


def internal_secret():
    """Shared secret for trusted internal AYNE calls (the MCP server), derived from the deployment's storage secret."""
    return hashlib.sha256(("ayne-internal|" + os.environ.get("APIFY_LOG_TOKEN", "")).encode()).hexdigest()[:32]
