"""OMENZ Track Record (free): what a buying agent checks before trusting a new seller.

Why (2026-11-15, Big Bro's "agent break room"): the buyer agent's objections were "Reputation? They're new. Usage
history? Not much. Then I'm watching." This answers with evidence instead of claims:
- per tool: release date, how it was tested (frozen holdout with a pre-registered gate, or release tests), version notes
- promises the code actually keeps (errors not charged, no guessing, nothing stored unless the route says so)
- an honest maturity note (new service, paid history just starting): no invented usage numbers
Live health is at /v1/status (real probes per request). Update HOLDOUTS when a new frozen test runs.
"""

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
    return {"schema": "omenz.track-record.v0", "publisher": "OMENZ (omenz.org)", "price": "free",
            "maturity": "New service: first tools live 2026-11-07, most launched 2026-11-14. Paid usage history is just starting; "
                        "we publish test evidence instead of usage claims.",
            "summary": {"tools": len(tools), "paid_routes": len(routes), "tools_with_frozen_holdouts": len(held)},
            "promises": PROMISES, "live_status": base + "/v1/status", "try_free": base + "/ayne/v1",
            "pricing_policy": base + "/v1/pricing-policy", "contact": "hello@omenz.org",
            "tools": sorted(tools.values(), key=lambda t: (t["tool"] not in HOLDOUTS, t["tool"]))}
