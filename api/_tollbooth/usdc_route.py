"""OMENZ USDC Route Check: cheapest and fastest way to move USDC from chain A to chain B right now (2026-11-25).

Demand (XCHAIN brief 11-25): agents pay for ranked route comparisons (~22 quote routes, median $0.01) and for
native-vs-wrapped token identity. For plain USDC moves, Circle CCTP V2 direct is often the cheapest path and nobody
headlines it. One call: is USDC native (Circle-issued) on both chains + the bridged look-alikes to avoid, CCTP V2
Standard vs Fast fee for the amount + the live Fast allowance + Circle's published attestation times, and Across +
Relay live quotes when they answer (best effort). Keyless public sources, no signing, no execution, nothing stored.
LI.FI is deliberately left out (its terms require non-US users); Socket/Bungee public API is gone (410).
"""
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

VERSION = "0.1.0"
UA = {"User-Agent": "OMENZ-usdc-route/0.1", "Accept": "application/json"}
IRIS = "https://iris-api.circle.com/v2"

# Circle's native USDC per chain (developers.circle.com/stablecoins/usdc-contract-addresses), CCTP V2 domain
# (developers.circle.com/cctp/concepts/supported-chains-and-domains). EVM ones verified 11-25 by eth_call
# symbol()/name() on public RPCs (all 'USDC' / 'USD Coin'); Solana mint verified via getAccountInfo (spl-token mint, 6 dp).
# Attestation times: developers.circle.com/cctp/required-block-confirmations (Circle averages, by SOURCE chain).
CHAINS = {
    "ethereum": {"chain_id": 1, "domain": 0, "usdc": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                 "standard": ("~15-19 minutes", 1020), "fast": ("~20 seconds", 20)},
    "avalanche": {"chain_id": 43114, "domain": 1, "usdc": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
                  "standard": ("~8 seconds", 8), "fast": None},
    "optimism": {"chain_id": 10, "domain": 2, "usdc": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
                 "standard": ("~15-19 minutes", 1020), "fast": ("~8 seconds", 8)},
    "arbitrum": {"chain_id": 42161, "domain": 3, "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                 "standard": ("~15-19 minutes", 1020), "fast": ("~8 seconds", 8)},
    "solana": {"chain_id": None, "domain": 5, "usdc": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
               "standard": ("~17 seconds", 17), "fast": ("~0.4-0.6 seconds", 1)},
    "base": {"chain_id": 8453, "domain": 6, "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
             "standard": ("~15-19 minutes", 1020), "fast": ("~8 seconds", 8)},
    "polygon": {"chain_id": 137, "domain": 7, "usdc": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                "standard": ("~8 seconds", 8), "fast": None},
}
# Bridged look-alikes: NOT Circle-issued, NOT burnable/mintable by CCTP. Several still report symbol 'USDC' on-chain.
BRIDGED = {
    "base": [{"symbol": "USDbC", "address": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA", "via": "Base canonical bridge from Ethereum (legacy)"}],
    "arbitrum": [{"symbol": "USDC.e", "address": "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8", "via": "Arbitrum canonical bridge from Ethereum (on-chain symbol 'USDC', name 'USD Coin (Arb1)')"}],
    "optimism": [{"symbol": "USDC.e", "address": "0x7F5c764cBc14f9669B88837ca1490cCa17c31607", "via": "Optimism standard bridge from Ethereum (on-chain symbol 'USDC')"}],
    "polygon": [{"symbol": "USDC.e", "address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "via": "Polygon PoS bridge from Ethereum (on-chain name 'USD Coin (PoS)')"}],
    "avalanche": [{"symbol": "USDC.e", "address": "0xA7D7079b0FEaD91F3e65f86E8915Cb59c1a4C664", "via": "Avalanche Bridge from Ethereum"}],
    "solana": [{"symbol": "USDCet", "address": "A9mUU4qviSctJVPJdBJWkb28deg915LYJKrzQ19ji3FM", "via": "Wormhole (Portal) wrapped Ethereum USDC"}],
    "ethereum": [],
}
ALIASES = {"eth": "ethereum", "mainnet": "ethereum", "ethereum mainnet": "ethereum", "arb": "arbitrum", "arbitrum one": "arbitrum",
           "arbitrum-one": "arbitrum", "op": "optimism", "op mainnet": "optimism", "op-mainnet": "optimism", "matic": "polygon",
           "polygon pos": "polygon", "pol": "polygon", "avax": "avalanche", "avalanche c-chain": "avalanche", "sol": "solana",
           "base mainnet": "base", "1": "ethereum", "8453": "base", "42161": "arbitrum", "10": "optimism", "137": "polygon", "43114": "avalanche"}
MINT_GAS = 200000  # rough gas for CCTP receiveMessage (mint) on an EVM destination
MAX_AMOUNT = 10_000_000
_cache = {}


def _chain(v):
    k = str(v or "").strip().lower()
    k = ALIASES.get(k, k)
    return k if k in CHAINS else None


def _get(url, timeout=6, body=None):
    hdr = dict(UA)
    if body is not None:
        hdr["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdr), timeout=timeout))


def _cached(key, ttl, fn):  # short dedupe for Circle only (Iris asks for polite polling); relayer quotes never cached
    if key in _cache and time.time() - _cache[key][1] < ttl:
        return _cache[key][0]
    v = fn()
    _cache[key] = (v, time.time())
    return v


def _cctp_fees(src, dst):
    rows = _cached(f"fee:{src}:{dst}", 30, lambda: _get(f"{IRIS}/burn/USDC/fees/{src}/{dst}", 5))
    out = {}
    for r in rows:
        t = int(r.get("finalityThreshold", 0))
        out["fast" if t <= 1000 else "standard"] = float(r.get("minimumFee", 0))
    return out


def _allowance():
    return float(_cached("allow", 30, lambda: _get(f"{IRIS}/fastBurn/USDC/allowance", 5))["allowance"])


def _mint_gas_usd(dst):
    import gas_compare
    if dst not in gas_compare.CHAINS:
        return None
    row = gas_compare._one(dst)
    if "error" in row:
        return None
    return round(row["erc20_transfer_usd"] * MINT_GAS / gas_compare.GAS["erc20_transfer"], 6)


def _across(a, b, units):
    d = _get("https://app.across.to/api/suggested-fees?inputToken=%s&outputToken=%s&originChainId=%d&destinationChainId=%d&amount=%d"
             % (CHAINS[a]["usdc"], CHAINS[b]["usdc"], CHAINS[a]["chain_id"], CHAINS[b]["chain_id"], units), 6)
    if d.get("isAmountTooLow"):
        return {"ok": False, "reason": "amount below Across minimum", "min_usdc": int(d.get("limits", {}).get("minDeposit", 0)) / 1e6}
    fee = int(d["totalRelayFee"]["total"]) / 1e6
    lim = d.get("limits") or {}
    r = {"ok": True, "fee_usd": round(fee, 6), "receive_usdc": round(int(d.get("outputAmount", units - int(d["totalRelayFee"]["total"]))) / 1e6, 6),
         "time_s": int(d.get("estimatedFillTimeSec") or 0) or None}
    if lim.get("maxDepositInstant") and units > int(lim["maxDepositInstant"]):
        r["note"] = "amount above Across instant-fill limit; fill may be slower"
    return r


def _relay(a, b, units):
    d = _get("https://api.relay.link/quote", 6, {
        "user": "0x000000000000000000000000000000000000dEaD", "originChainId": CHAINS[a]["chain_id"],
        "destinationChainId": CHAINS[b]["chain_id"], "originCurrency": CHAINS[a]["usdc"], "destinationCurrency": CHAINS[b]["usdc"],
        "amount": str(units), "tradeType": "EXACT_INPUT"})
    fees = d.get("fees") or {}
    fee = sum(float((fees.get(k) or {}).get("amountUsd") or 0) for k in ("gas", "relayer", "app"))
    det = d.get("details") or {}
    out = ((det.get("currencyOut") or {}).get("amountFormatted"))
    if out is None:
        return {"ok": False, "reason": (d.get("message") or "no quote")[:120]}
    return {"ok": True, "fee_usd": round(fee, 6), "receive_usdc": round(float(out), 6), "time_s": det.get("timeEstimate")}


def _amount(v):
    s = str(v if v is not None else "100").strip().replace(",", "").replace("$", "")
    try:
        x = float(s)
    except ValueError:
        return None
    if not (x == x) or x <= 0 or x > MAX_AMOUNT:
        return None
    return round(x, 6)


def check(d):
    d = d or {}
    raw_from, raw_to = d.get("from"), d.get("to")
    a, b = _chain(raw_from), _chain(raw_to)
    if not raw_from or not raw_to:
        return {"error": "from and to are required, e.g. from=base&to=arbitrum&amount=100", "supported": list(CHAINS)}
    bad = [str(x) for x, c in ((raw_from, a), (raw_to, b)) if not c]
    if bad:
        return {"error": f"unsupported chain(s) (this tool covers Circle CCTP V2 chains with native USDC): {', '.join(bad)}", "supported": list(CHAINS)}
    if a == b:
        return {"error": "from and to are the same chain; nothing to bridge", "supported": list(CHAINS)}
    amt = _amount(d.get("amount"))
    if amt is None:
        return {"error": f"amount must be a number of USDC > 0 and <= {MAX_AMOUNT:,} (e.g. 100)"}
    units = int(round(amt * 1e6))
    evm = CHAINS[a]["chain_id"] and CHAINS[b]["chain_id"]
    deadline = time.time() + 12
    ex = ThreadPoolExecutor(6)
    jobs = {"fees": ex.submit(_cctp_fees, CHAINS[a]["domain"], CHAINS[b]["domain"]), "allowance": ex.submit(_allowance),
            "mint_gas": ex.submit(_mint_gas_usd, b)}
    if evm:
        jobs["across"] = ex.submit(_across, a, b, units)
        jobs["relay"] = ex.submit(_relay, a, b, units)
    wait(list(jobs.values()), timeout=max(deadline - time.time(), 1))
    ex.shutdown(wait=False, cancel_futures=True)
    res, errs = {}, {}
    for k, f in jobs.items():
        if not f.done():
            errs[k] = "timed out"
            continue
        try:
            res[k] = f.result()
        except Exception as e:
            errs[k] = f"unavailable ({type(e).__name__}: {str(e)[:60]})"

    mint_gas = res.get("mint_gas")
    gas_note = (f"plus ~${mint_gas} destination gas to mint (est., {MINT_GAS:,} gas) unless you use Circle's Forwarding Service"
                if mint_gas is not None else "plus destination gas to mint (you submit receiveMessage, or use Circle's Forwarding Service)")
    sa, fa = CHAINS[a]["standard"], CHAINS[a]["fast"]
    options = []
    cctp = {"protocol": "Circle CCTP V2", "source": "iris-api.circle.com (live)", "ok": "fees" in res}
    if "fees" in res:
        std = {"name": "cctp_standard", "fee_bps": res["fees"].get("standard", 0.0), "fee_usd": round(amt * res["fees"].get("standard", 0.0) / 1e4, 6),
               "time": sa[0], "time_s": sa[1], "native_to_native": True, "note": gas_note}
        cctp["standard"] = std
        options.append(std)
        if fa is None:
            cctp["fast"] = {"available": False, "reason": f"Circle disables Fast Transfer from {a}: Standard is already {sa[0]}"}
        else:
            allow = res.get("allowance")
            fast = {"name": "cctp_fast", "available": True, "fee_bps": res["fees"].get("fast"),
                    "fee_usd": round(amt * (res["fees"].get("fast") or 0) / 1e4, 6), "time": fa[0], "time_s": fa[1],
                    "fast_allowance_usdc": allow, "native_to_native": True, "note": gas_note}
            if allow is not None and amt > allow:
                fast.update(available=False, reason="amount exceeds Circle's current global Fast Transfer allowance")
            cctp["fast"] = fast
            if fast["available"]:
                options.append(fast)
    else:
        cctp["error"] = errs.get("fees", "unavailable")
    for opt in options:
        opt["all_in_usd_est"] = round(opt["fee_usd"] + (mint_gas or 0), 6)

    relayers = {}
    for k, label, src in (("across", "Across", "app.across.to/api/suggested-fees (legacy endpoint)"),
                          ("relay", "Relay", "api.relay.link/quote")):
        if not evm:
            relayers[k] = {"best_effort": True, "source": src, "ok": False, "reason": "skipped: relayer quotes are EVM-to-EVM only in this version"}
            continue
        q = res.get(k) if k in res else {"ok": False, "reason": errs.get(k, "unavailable")}
        q = dict(q, best_effort=True, source=src)
        relayers[k] = q
        if q.get("ok"):
            options.append({"name": k, "fee_usd": q["fee_usd"], "all_in_usd_est": q["fee_usd"], "time_s": q.get("time_s"),
                            "time": f"~{q['time_s']} s (quoted)" if q.get("time_s") else "not quoted"})

    def _t(o):
        return o["time_s"] if o.get("time_s") is not None else 10 ** 9
    cheapest = min(options, key=lambda o: (o["all_in_usd_est"], _t(o))) if options else None
    fastest = min(options, key=lambda o: (_t(o), o["all_in_usd_est"])) if options else None

    def _why(o, kind):
        if not o:
            return None
        gas = " excl. destination mint gas" if o["name"].startswith("cctp") and mint_gas is None else ""
        base = f"{o['name']}: ~${o['all_in_usd_est']} all-in (est.{gas}), {o['time']}"
        return {"route": o["name"], "reason": base + (" - lowest cost of the options that answered" if kind == "cheap" else " - shortest time of the options that answered")}

    def _native(c):
        return {"chain": c, "native_usdc": True, "usdc_address": CHAINS[c]["usdc"], "cctp_domain": CHAINS[c]["domain"],
                "bridged_variants_to_avoid": BRIDGED.get(c, [])}

    return {"service": "OMENZ USDC Route Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from": a, "to": b, "amount_usdc": amt,
            "cheapest_now": _why(cheapest, "cheap"), "fastest_now": _why(fastest, "fast"),
            "destination": _native(b), "origin": _native(a),
            "cctp": cctp, "relayers": relayers,
            "sources_ok": {"circle_fees": "fees" in res, "circle_allowance": "allowance" in res, "dest_gas_estimate": mint_gas is not None,
                           "across": bool(relayers["across"].get("ok")), "relay": bool(relayers["relay"].get("ok"))},
            "limits": ("Quote-time check, not a guarantee. CCTP fees/allowance live from Circle Iris; CCTP times are Circle's published averages by source chain. "
                       "CCTP is native USDC -> native USDC only (bridged USDC.e/USDbC must be swapped first). CCTP rows add an estimated destination mint gas; "
                       "relayer fees are their own quoted totals (best effort, legacy/keyless endpoints that may close). Source-chain gas for your deposit/burn is not included. "
                       "No signing, no execution, nothing stored.")}


def _is_evm(s):
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", s))


def _is_sol(s):
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", s))


def native(d):
    d = d or {}
    raw, tok = d.get("chain"), str(d.get("token") or "").strip()
    c = _chain(raw)
    if not raw or not tok:
        return {"error": "chain and token are required, e.g. chain=base&token=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "supported": list(CHAINS)}
    if not c:
        return {"error": f"unsupported chain (this tool covers Circle CCTP V2 chains with native USDC): {raw}", "supported": list(CHAINS)}
    if c == "solana":
        if not _is_sol(tok):
            return {"error": "token must be a Solana mint address (base58) for chain=solana"}
        same = lambda x, y: x == y  # noqa: E731  base58 is case-sensitive
    else:
        if not _is_evm(tok):
            return {"error": f"token must be a 0x EVM address (40 hex) for chain={c}"}
        same = lambda x, y: x.lower() == y.lower()  # noqa: E731
    out = {"service": "OMENZ USDC Native Check", "version": VERSION, "chain": c, "token": tok,
           "native_usdc_address": CHAINS[c]["usdc"], "cctp_domain": CHAINS[c]["domain"]}
    if same(tok, CHAINS[c]["usdc"]):
        return dict(out, verdict="NATIVE_USDC", issuer="Circle", cctp_supported=True,
                    reason=f"This is Circle-issued native USDC on {c}: issued by Circle and moveable by CCTP V2.")
    for v in BRIDGED.get(c, []):
        if same(tok, v["address"]):
            return dict(out, verdict="BRIDGED_USDC", symbol=v["symbol"], bridged_via=v["via"], cctp_supported=False,
                        reason=f"This is {v['symbol']}, a bridged USDC look-alike on {c}, not Circle-issued. CCTP cannot move it; "
                               f"swap it to native USDC ({CHAINS[c]['usdc']}) first. x402 sellers asking for USDC on {c} expect the native address.")
    for oc, info in CHAINS.items():
        if oc != c and (info["usdc"].lower() == tok.lower() if _is_evm(tok) and _is_evm(info["usdc"]) else info["usdc"] == tok):
            return dict(out, verdict="UNKNOWN", cctp_supported=False, matches_other_chain={"chain": oc, "is": "native USDC"},
                        reason=f"Not USDC on {c}. This address is native USDC on {oc}; on {c} the native USDC is {CHAINS[c]['usdc']}.")
        for v in BRIDGED.get(oc, []):
            if oc != c and same(tok, v["address"]):
                return dict(out, verdict="UNKNOWN", cctp_supported=False, matches_other_chain={"chain": oc, "is": v["symbol"]},
                            reason=f"Not USDC on {c}. This address is {v['symbol']} (bridged) on {oc}.")
    return dict(out, verdict="UNKNOWN", cctp_supported=False,
                reason=f"Not Circle's native USDC on {c} and not a known bridged USDC variant. Treat as unverified; native USDC on {c} is {CHAINS[c]['usdc']}.",
                known_bridged_variants=BRIDGED.get(c, []))
