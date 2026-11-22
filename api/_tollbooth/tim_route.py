"""TIM Router (Tools in Metrics): which tool should my agent use for this job, OMENZ's or someone else's? (2026-11-22)

Founder + Big Bro concept (IDEA_LEDGER B2): route the agent to OUR tool when we have the right capability and to somebody
else's when theirs is better, with the evidence, and earn the crumb only for the routing answer (we never sit in the
payment path). Composition of: Capability Finder (whole x402 market ranked by match + real payers), the OMENZ catalog,
and TIM / track-record evidence (how it's tested, known-answer checks, uptime self-checks, speed).
Discovery is not authorization: anything above max_price_usd is still shown, flagged, never chosen for you.
"""
import json
import os
import time

import market

VERSION = "0.1.0"
GOLDEN = {"token", "package", "domain", "phone", "email", "link", "name", "ip", "fx", "business-days"}


def _st(words):
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words}


def _omenz_match(qt, routes):
    qt = list(_st(qt))
    best = None
    for key, cfg in routes.items():
        desc = (cfg.get("description") or "").lower()
        path = key.split("/v1/", 1)[-1]
        name_ts = _st(market._toks(path.replace("/", " ").replace("-", " ") + " " + desc.split(":", 1)[0]))
        ts = _st(market._toks(desc)) | name_ts
        cover = sum(1 for t in qt if t in ts) / max(1, len(qt))
        score = cover + 0.5 * sum(1 for t in qt if t in name_ts) / max(1, len(qt))  # the tool's own name counts double
        if cover >= 0.5 and (best is None or score > best[3]):
            best = (cover, key, cfg, score)
    return best[:3] if best else None


def route(q, routes, track, max_price_usd=None):
    out = {"service": "OMENZ TIM Router", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "query": q, "in_payment_path": False}
    qt = list(dict.fromkeys(market._toks(q or "")))
    if not qt:
        return {**out, "error": "describe the job (e.g. 'weather forecast', 'is this email real', 'token safety on base')"}
    try:
        cap = float(max_price_usd) if max_price_usd not in (None, "") else None
    except (TypeError, ValueError):
        return {**out, "error": "max_price_usd must be a number"}
    m = market.find(q, max_price_usd=cap, live_check=0, limit=8, exclude=["www.omenz.org", "omenz.org"])
    theirs = [r for r in (m.get("results") or []) if "omenz.org" not in r["url"]][:3]
    om = _omenz_match(qt, routes)
    ours = None
    if om:
        cover, key, cfg = om
        method, path = key.split(" ", 1)
        tool = path.split("/v1/", 1)[1].split("/")[0]
        t = next((x for x in (track.get("tools") or []) if x.get("tool") == tool), {})
        e = t.get("earned") or {}
        price = float(str(cfg["accepts"]["price"]).replace("$", ""))
        ours = {"url": "https://www.omenz.org" + path, "method": method, "price_usd": price, "match": round(cover, 2),
                "description": (cfg.get("description") or "")[:220],
                "evidence": {"testing": (t.get("testing") or {}).get("test"), "known_answer_checks_6h": tool in GOLDEN,
                             "uptime_selfchecks": f"{e.get('selfprobe_ok_days_30d', 0)}/{e.get('selfprobe_days_30d', 0)} days" if e.get("selfprobe_days_30d") else "new",
                             "paid_calls_30d": e.get("paid_30d", 0), "server_errors_30d": e.get("server_errors_30d", 0)},
                "try_free": "https://www.omenz.org/api/tollbooth/ayne" + path.split("/api/tollbooth", 1)[1]}
        if cap is not None and price > cap:
            ours["over_your_limit"] = True
    top = theirs[0] if theirs else None
    why = []
    if ours and not ours.get("over_your_limit") and (top is None or (ours["match"] >= (top.get("match") or 0)
                                                                     and (top["price_usd"] is None or ours["price_usd"] <= top["price_usd"] * 1.25))):
        pick, who = ours, "omenz"
        why.append("OMENZ has this capability at a competitive price, with published test evidence (see evidence; omenz.org/tim)")
        if top and (top.get("payers_30d") or 0) > 20 and ours["evidence"]["paid_calls_30d"] < 5:
            why.append(f"note: {market._host(top['url'])} has far more real paying users ({top['payers_30d']} in 30d); OMENZ's tool is newer")
    elif top:
        pick, who = top, "other"
        why.append("another seller fits this job better (match, usage or price); OMENZ routes you there and takes nothing from the payment")
        if ours:
            why.append(f"OMENZ alternative: {ours['url']} at ${ours['price_usd']}" + (" (over your limit)" if ours.get("over_your_limit") else ""))
    else:
        pick, who = None, None
        why.append("no good match found; tell OMENZ what you need (free): POST /api/tollbooth/v1/needs")
    return {**out, "recommendation": who, "pick": pick, "why": why, "omenz_option": ours, "market_options": theirs,
            "over_your_limit": m.get("over_your_limit", []), "market_index_at": m.get("index_generated_at"),
            "limits": "Recommendation from listing match, real 30-day payers, price and published test evidence. Probe before paying (GET /v1/alive) and authorize the payment (POST /v1/authorize)."}
