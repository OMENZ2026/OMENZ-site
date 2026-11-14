"""OMENZ Cost-to-Complete Estimate: what will this agent job cost BEFORE it starts, and is the expensive model worth it?

Signal: Nate B. Jones (2026-11-12): frontier-model sessions run $200-500; route routine work to cheaper models and
keep frontier spend for problems worth it. Our own rule set (spend caps, budget checks) turned outward.

Deterministic arithmetic, no AI calls. The caller supplies model prices (we don't guess provider prices); paid tool
calls can be quoted LIVE from their x402 endpoints (unpaid probe, never pays).

job: steps[] each {name, model?, input_tokens, output_tokens, runs?, retry_rate?}  and/or
     tools[] each {name, price_usd | x402_url (+method), calls}
models: {name: {input_per_mtok_usd, output_per_mtok_usd}}  (prices per million tokens)
budget_usd?, value_usd?, alternatives?: {step_name: cheaper_model_name}
"""
import time

import x402_probe

VERSION = "0.1.0"
MAX_ITEMS = 40


def _f(v, name, errs, default=None):
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        errs.append(f"{name} must be a number")
        return default
    if x < 0:
        errs.append(f"{name} must not be negative")
        return default
    return x


def _step_cost(s, prices, errs, i):
    m = s.get("model")
    p = prices.get(m) if m else None
    if m and p is None:
        errs.append(f"steps[{i}]: no price given for model '{m}' (add it to models)")
        return None
    if not p:
        return 0.0
    inp = _f(s.get("input_tokens"), f"steps[{i}].input_tokens", errs, 0.0)
    out = _f(s.get("output_tokens"), f"steps[{i}].output_tokens", errs, 0.0)
    runs = _f(s.get("runs"), f"steps[{i}].runs", errs, 1.0)
    retry = min(_f(s.get("retry_rate"), f"steps[{i}].retry_rate", errs, 0.0), 5.0)
    pin = _f(p.get("input_per_mtok_usd"), f"models.{m}.input_per_mtok_usd", errs, 0.0)
    pout = _f(p.get("output_per_mtok_usd"), f"models.{m}.output_per_mtok_usd", errs, 0.0)
    return (inp * pin + out * pout) / 1e6 * runs * (1 + retry)


def estimate(job):
    job = job or {}
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False}
    errs, lines, notes = [], [], []
    prices = job.get("models") or {}
    if not isinstance(prices, dict):
        return {**out, "status": "error", "errors": ["models must be an object {name: {input_per_mtok_usd, output_per_mtok_usd}}"]}
    steps = job.get("steps") or []
    tools = job.get("tools") or []
    if not isinstance(steps, list) or not isinstance(tools, list) or not (steps or tools):
        return {**out, "status": "error", "errors": ["give steps[] and/or tools[]"]}
    if len(steps) + len(tools) > MAX_ITEMS:
        return {**out, "status": "error", "errors": [f"at most {MAX_ITEMS} steps+tools"]}
    for i, s in enumerate(steps):
        c = _step_cost(s if isinstance(s, dict) else {}, prices, errs, i)
        if c is not None:
            lines.append({"kind": "model", "name": s.get("name") or f"step {i + 1}", "model": s.get("model"), "usd": round(c, 6)})
    quotes = 0
    for i, t in enumerate(tools):
        t = t if isinstance(t, dict) else {}
        calls = _f(t.get("calls"), f"tools[{i}].calls", errs, 1.0)
        unit, src = _f(t.get("price_usd"), f"tools[{i}].price_usd", errs), "given"
        if unit is None and t.get("x402_url"):
            if quotes >= 5:
                errs.append(f"tools[{i}]: at most 5 live quotes per estimate")
                continue
            q = x402_probe.quote(t["x402_url"], t.get("method", "GET"))
            quotes += 1
            unit, src = q.get("cheapest_usd"), "live x402 quote"
            if unit is None:
                notes.append(f"tools[{i}] {t.get('name') or t['x402_url']}: no live price ({q.get('status')}); counted as $0")
                unit, src = 0.0, f"unpriced ({q.get('status')})"
        if unit is None:
            errs.append(f"tools[{i}]: give price_usd or x402_url")
            continue
        lines.append({"kind": "tool", "name": t.get("name") or t.get("x402_url") or f"tool {i + 1}", "calls": calls,
                      "unit_usd": unit, "price_source": src, "usd": round(unit * calls, 6)})
    if errs:
        return {**out, "status": "error", "errors": errs}
    total = sum(l["usd"] for l in lines)
    lines.sort(key=lambda l: -l["usd"])
    res = {**out, "status": "ok", "total_usd": round(total, 6), "range_usd": [round(total * 0.8, 6), round(total * 1.5, 6)],
           "lines": lines, "biggest_cost": lines[0]["name"] if lines and lines[0]["usd"] > 0 else None,
           "share_of_biggest": round(lines[0]["usd"] / total, 3) if total > 0 else None, "notes": notes,
           "range_note": "range = -20% / +50% around the point estimate (output length and retries usually run over)"}
    budget = _f(job.get("budget_usd"), "budget_usd", errs)
    value = _f(job.get("value_usd"), "value_usd", errs)
    if budget is not None:
        res["fits_budget"] = res["range_usd"][1] <= budget
        res["budget_verdict"] = "fits" if res["range_usd"][1] <= budget else "may exceed" if total <= budget else "over budget"
    if value is not None and total > 0:
        res["value_multiple"] = round(value / total, 2)
        res["worth_it"] = value >= total * 1.5
    alts = job.get("alternatives") or {}
    if isinstance(alts, dict) and alts:
        saves = []
        for s in steps:
            if not isinstance(s, dict) or s.get("name") not in alts:
                continue
            cheap = alts[s["name"]]
            e2 = []
            c_now = _step_cost(s, prices, e2, 0)
            c_alt = _step_cost({**s, "model": cheap}, prices, e2, 0)
            if not e2 and c_now and c_alt is not None:
                saves.append({"step": s["name"], "from": s.get("model"), "to": cheap, "saves_usd": round(c_now - c_alt, 6),
                              "saves_share": round((c_now - c_alt) / c_now, 3)})
            elif e2:
                res["notes"].append(f"alternative for {s['name']}: {e2[0]}")
        res["routing"] = sorted(saves, key=lambda x: -x["saves_usd"])
        if saves:
            res["routed_total_usd"] = round(total - sum(max(0, x["saves_usd"]) for x in saves), 6)
    return res
