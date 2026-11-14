"""OMENZ Agent Wallet tools: what an agent's wallet holds, what it has been paying for, and how long it can keep going.
"Find the Ether" (founder 2026-11-14): own the infrastructure around agent-wallet micropayments.

All public on-chain data (USDC on Base), read through a public RPC; payees are named from the x402 market index
(which x402 services pay out to that address). Never moves funds, never needs a key.

- balance(addr)             USDC + ETH balance on Base.
- spend(addr, days)         outgoing USDC payments in the window, grouped by payee, with the x402 service each payee runs.
- runway(addr, days)        balance / recent daily spend -> days left, OK / LOW / CRITICAL, top cost drivers.
"""
import json
import re
import time
import urllib.request

VERSION = "0.1.0"
RPCS = ["https://base-rpc.publicnode.com", "https://mainnet.base.org"]
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
BLOCK_S = 2  # Base block time
CHUNK = 50000
MAX_DAYS = 14


class WalletError(Exception):
    pass


def _rpc(method, params):
    last = None
    for url in RPCS:
        try:
            req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "OMENZ-wallet/0.1"})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            if "result" in d:
                return d["result"]
            last = (d.get("error") or {}).get("message")
        except Exception as e:
            last = type(e).__name__
    raise WalletError(f"Base RPC unavailable ({last})")


def _check(addr):
    if not ADDR.match(addr or ""):
        raise WalletError("address must be 0x + 40 hex characters")
    return addr.lower()


def _topic(a):
    return "0x" + "0" * 24 + a[2:]


def balance(addr):
    a = _check(addr)
    raw = _rpc("eth_call", [{"to": USDC, "data": "0x70a08231" + "0" * 24 + a[2:]}, "latest"])
    eth = _rpc("eth_getBalance", [a, "latest"])
    return {"version": VERSION, "address": a, "network": "base", "usdc": int(raw, 16) / 1e6, "eth": int(eth, 16) / 1e18,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _outgoing(a, days):
    head = int(_rpc("eth_blockNumber", []), 16)
    start = head - int(days * 86400 / BLOCK_S)
    logs, frm = [], start
    while frm <= head:
        to = min(head, frm + CHUNK - 1)
        got = _rpc("eth_getLogs", [{"address": USDC, "topics": [TRANSFER, _topic(a)], "fromBlock": hex(frm), "toBlock": hex(to)}])
        logs += got
        if len(logs) > 20000:
            raise WalletError("too many transfers to summarize; use a shorter window")
        frm = to + 1
    return logs, head, start


def _payee_names(addrs):
    try:
        import market
        ix = market._index()
    except Exception:
        return {}
    want = set(addrs)
    out = {}
    for r in ix["rows"]:
        for p in r[8] or []:
            if p in want:
                o = out.setdefault(p, {"hosts": {}, "endpoints": 0})
                h = market._host(r[0])
                o["hosts"][h] = o["hosts"].get(h, 0) + 1
                o["endpoints"] += 1
    return {k: {"service_hosts": sorted(v["hosts"], key=lambda h: -v["hosts"][h])[:3], "x402_endpoints": v["endpoints"]} for k, v in out.items()}


def spend(addr, days=7):
    a = _check(addr)
    try:
        days = max(0.1, min(float(days or 7), MAX_DAYS))
    except (TypeError, ValueError):
        raise WalletError("days must be a number")
    logs, head, start = _outgoing(a, days)
    by = {}
    total = 0.0
    for lg in logs:
        to = "0x" + lg["topics"][2][-40:]
        v = int(lg["data"], 16) / 1e6
        total += v
        b = by.setdefault(to, {"payee": to, "usd": 0.0, "payments": 0, "first_block": int(lg["blockNumber"], 16)})
        b["usd"] += v
        b["payments"] += 1
    names = _payee_names(list(by))
    payees = sorted(by.values(), key=lambda x: -x["usd"])
    for p in payees:
        p["usd"] = round(p["usd"], 6)
        p["avg_payment_usd"] = round(p["usd"] / p["payments"], 6)
        p.update(names.get(p["payee"], {"service_hosts": [], "x402_endpoints": 0}))
        p["known_x402_seller"] = p["x402_endpoints"] > 0
        p.pop("first_block", None)
    micro = sum(1 for lg in logs if int(lg["data"], 16) <= 100000)  # <= $0.10
    return {"version": VERSION, "address": a, "network": "base", "asset": "USDC", "window_days": round(days, 2),
            "blocks": [start, head], "payments": len(logs), "total_usd": round(total, 6), "daily_rate_usd": round(total / days, 6),
            "micropayments_le_10c": micro, "payees_count": len(payees), "payees": payees[:25],
            "known_x402_share": round(sum(p["usd"] for p in payees if p["known_x402_seller"]) / total, 3) if total else None,
            "note": "Outgoing USDC transfers only (public chain data). Payees are named from the x402 market index when they run listed services."}


def runway(addr, days=7, low_days=3, critical_days=1):
    b = balance(addr)
    s = spend(addr, days)
    rate = s["daily_rate_usd"]
    left = (b["usdc"] / rate) if rate > 0 else None
    try:
        low, crit = float(low_days), float(critical_days)
    except (TypeError, ValueError):
        raise WalletError("low_days / critical_days must be numbers")
    status = "NO_RECENT_SPEND" if left is None else "CRITICAL" if left < crit else "LOW" if left < low else "OK"
    return {"version": VERSION, "address": b["address"], "network": "base", "usdc_balance": b["usdc"], "eth_balance": b["eth"],
            "daily_spend_usd": rate, "days_left": round(left, 2) if left is not None else None, "status": status,
            "top_cost_drivers": [{k: p[k] for k in ("payee", "usd", "payments", "service_hosts")} for p in s["payees"][:5]],
            "based_on": f"last {s['window_days']} days, {s['payments']} payments", "checked_at": b["checked_at"],
            "next_action": {"CRITICAL": "top up now or pause paid calls", "LOW": "top up soon", "OK": "none",
                            "NO_RECENT_SPEND": "no outgoing USDC in the window"}[status]}
