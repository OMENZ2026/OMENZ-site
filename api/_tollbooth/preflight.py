"""OMENZ Agent Preflight: can this agent actually finish this job with what it has, BEFORE it starts spending?

Composes our own checks into one READY / BLOCKED answer:
- every paid tool the job needs: answering now? live x402 price? within its per-call max? (x402 probes, never pays)
- the whole job: sum of calls x live prices within the budget?
- the agent's Permission Passport (optional): does it allow each tool's host and the total spend?
Returns what's missing so the agent (or its owner) can fix it before work begins. Deterministic, no AI calls.
"""
import time
import urllib.parse

import passport
import x402_probe

VERSION = "0.1.0"
MAX_TOOLS = 8


def check(job):
    job = job or {}
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False}
    tools = job.get("tools") or []
    if not isinstance(tools, list) or not tools:
        return {**out, "verdict": "ERROR", "errors": ["tools[] required: each {name, url, method?, calls?, max_price_usd?}"]}
    if len(tools) > MAX_TOOLS:
        return {**out, "verdict": "ERROR", "errors": [f"at most {MAX_TOOLS} tools per preflight"]}
    try:
        budget = float(job["budget_usd"]) if job.get("budget_usd") is not None else None
    except (TypeError, ValueError):
        return {**out, "verdict": "ERROR", "errors": ["budget_usd must be a number"]}
    token = job.get("passport_token")
    blockers, warnings, rows, total = [], [], [], 0.0
    for i, t in enumerate(tools):
        t = t if isinstance(t, dict) else {}
        name, url = str(t.get("name") or f"tool {i + 1}")[:80], t.get("url")
        if not isinstance(url, str) or not url:
            blockers.append(f"{name}: no url")
            continue
        try:
            calls = float(t.get("calls") or 1)
            cap = float(t["max_price_usd"]) if t.get("max_price_usd") is not None else None
        except (TypeError, ValueError):
            blockers.append(f"{name}: calls / max_price_usd must be numbers")
            continue
        q = x402_probe.quote(url, t.get("method", "GET"))
        row = {"name": name, "url": url, "status": q.get("status"), "http_status": q.get("http_status"),
               "latency_ms": q.get("latency_ms"), "unit_usd": q.get("cheapest_usd"), "calls": calls}
        if q["status"] == "quoted":
            if q.get("cheapest_usd") is None:
                warnings.append(f"{name}: priced in an asset we don't recognize; cost not counted")
            else:
                row["usd"] = round(q["cheapest_usd"] * calls, 6)
                total += row["usd"]
                if cap is not None and q["cheapest_usd"] > cap + 1e-12:
                    blockers.append(f"{name}: live price ${q['cheapest_usd']:g} is over its max ${cap:g}")
        elif q["status"] == "no_payment_requested":
            row["usd"] = 0.0
        else:
            blockers.append(f"{name}: not usable right now ({q['status']}: {q.get('reason')})")
        if token:
            pc = passport.check(token, {"tool": t.get("passport_tool") or name, "url": url, "amount_usd": 0})
            row["passport"] = pc["decision"]
            if pc["decision"] != "ALLOW":
                blockers.append(f"{name}: passport says DENY ({'; '.join(pc['reasons'])})")
        rows.append(row)
    out.update({"tools": rows, "estimated_total_usd": round(total, 6)})
    if budget is not None:
        out["budget_usd"] = budget
        if total > budget + 1e-12:
            blockers.append(f"estimated ${total:g} is over the budget ${budget:g}")
    else:
        warnings.append("no budget_usd given: total not checked")
    if token:
        p = passport.check(token, {"amount_usd": total})
        if p.get("valid") and p.get("spend_left_usd") is not None and total > p["spend_left_usd"] + 1e-12:
            blockers.append(f"passport spend limit ${p['spend_left_usd']:g} is below the estimated ${total:g}")
        if not p.get("valid"):
            blockers.append("passport invalid or forged")
        elif p.get("seconds_left", 1) <= 0:
            blockers.append("passport expired")
        else:
            out["passport_seconds_left"] = p.get("seconds_left")
    return {**out, "verdict": "BLOCKED" if blockers else "READY", "blockers": blockers, "warnings": warnings,
            "next_action": "fix the blockers, then start" if blockers else "start the job"}
