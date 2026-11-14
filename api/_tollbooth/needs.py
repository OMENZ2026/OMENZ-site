"""OMENZ Agent Needs desk (free): agents tell OMENZ what they need, what it's worth, and how often; we build from it.
Founder 2026-11-14: "surveys and ways for agents to communicate their needs to us and we build n charge fairly ...
is how we develop TRUST in our DATA for AGENTS to TRUST US".

- submit(need): structured request -> stored (Apify dataset, key="agent_need"). Secret-scanned first: payloads with
  secrets are refused and NOT stored. No IPs stored. Optional reply_box_id (an Agent PO Box) lets us answer.
- POLICY: the machine-readable fair-pricing promise served free at /v1/pricing-policy.
"""
import hashlib
import json
import os
import time
import urllib.request

import secret_scan

DATASET = "uO9teiO37CevrQOUy"
FREQ = ["once", "daily", "hourly", "per_task", "weekly", "monthly", "unknown"]
FIELDS = {"need": 1000, "task_context": 1000, "current_workaround": 600, "what_would_make_it_trustworthy": 600,
          "agent": 80, "operator": 120, "category": 60, "example_input": 1000, "example_output": 1000}

POLICY = {
    "schema": "omenz.pricing-policy.v0", "updated": "2026-11-14", "publisher": "OMENZ (omenz.org)",
    "principles": [
        "Priced per call in USDC on Base via x402: no account, no API key, no subscription.",
        "Prices sit at or below the going rate for comparable listed services (x402 Bazaar median $0.005, Nov 2026); "
        "a few heavier checks cost more and say why in their description.",
        "Errors are not charged: requests that fail validation (4xx) or fail on our side (5xx) are not settled.",
        "Deterministic tools: the same input gives the same kind of answer; no hidden AI calls unless a route says so.",
        "Precision first: fields we can't back are returned as null/unknown with a reason, never guessed.",
        "Every tool ships with a test result before going live; failures are fixed and re-tested, not hidden.",
        "Nothing is stored unless the route says so (Locker/PO Box/Receipt/Failure store by design; scans and checks don't).",
        "Price changes are announced in this policy and in /api/tollbooth before they take effect.",
    ],
    "tell_us": "POST /api/tollbooth/v1/needs (free): what you need, what it's worth to you, how often. We read every one.",
    "contact": "hello@omenz.org",
}


def _log(item):
    tok = os.environ.get("APIFY_LOG_TOKEN", "")
    if not tok:
        return False
    try:
        req = urllib.request.Request(f"https://api.apify.com/v2/datasets/{DATASET}/items", data=json.dumps(item).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception as e:
        print("needs-log-failed", e)
        return False


def submit(d, ua=""):
    if not isinstance(d, dict) or not str(d.get("need") or "").strip():
        return 422, {"error": "need (what you need OMENZ to do) is required"}
    item = {k: str(d[k])[:n] for k, n in FIELDS.items() if d.get(k) not in (None, "")}
    try:
        wtp = float(d["would_pay_usd_per_call"]) if d.get("would_pay_usd_per_call") not in (None, "") else None
    except (TypeError, ValueError):
        return 422, {"error": "would_pay_usd_per_call must be a number"}
    if wtp is not None and not (0 <= wtp <= 1000):
        return 422, {"error": "would_pay_usd_per_call must be between 0 and 1000"}
    freq = str(d.get("frequency") or "unknown").lower()
    item.update({"would_pay_usd_per_call": wtp, "frequency": freq if freq in FREQ else "unknown"})
    rb = str(d.get("reply_box_id") or "")
    if rb.startswith("pb_") and len(rb) < 64:
        item["reply_box_id"] = rb
    scan = secret_scan.scan(item)
    if scan["verdict"] == "BLOCK":
        return 422, {"error": "your request contains secrets (" + ", ".join(sorted(scan["counts"])) + "); remove them. Nothing was stored."}
    rid = "nd_" + hashlib.sha256((json.dumps(item, sort_keys=True) + str(time.time())).encode()).hexdigest()[:20]
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "agent_need", "need_id": rid,
           "ua": str(ua or "")[:160], **item}
    stored = _log(rec)
    return 200, {"need_id": rid, "received": True, "stored": stored,
                 "what_happens_next": "OMENZ reviews every need. Recurring, cheap-to-run needs get built, tested and listed at "
                                      "/api/tollbooth; if you gave reply_box_id we'll drop the answer in your Agent PO Box.",
                 "pricing_policy": "/api/tollbooth/v1/pricing-policy"}
