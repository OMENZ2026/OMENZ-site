"""OMENZ Price Check: a crypto price an agent can act on, cross-checked across independent sources (2026-11-24).

Demand (market index 11-24): 'token price' = 210 endpoints, 99 sellers, 691 payers in 30 days, median $0.002. Most return
one source. Agents act on prices (swaps, invoices, limits), and one bad feed is expensive, so this reads up to three
independent sources (Coinbase spot, Kraken, Chainlink on-chain feed on Base) and says whether they AGREE.
Public data, no keys, no AI.
"""
import json
import re
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import chain_tools as ct

VERSION = "0.1.0"
CHAINLINK_BASE = {"ETH": "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70", "BTC": "0x64c911996D3c6aC71f9b455B1E8E7266BcbD848F",
                  "USDC": "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B", "DAI": "0x591e79239a7d679378eC8c847e5038150364C78F",
                  "CBETH": "0xd7818272B9e248357d13057AAb0B417aF31E817d"}
ALIAS = {"WETH": "ETH", "WBTC": "BTC", "CBBTC": "BTC", "XBT": "BTC", "MATIC": "POL"}
SYM = re.compile(r"^[A-Z0-9]{2,10}$")
UA = {"User-Agent": "OMENZ-price/0.1"}


def _get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=6))


def _coinbase(s):
    return float(_get(f"https://api.coinbase.com/v2/prices/{s}-USD/spot")["data"]["amount"])


def _kraken(s):
    d = _get(f"https://api.kraken.com/0/public/Ticker?pair={'XBT' if s == 'BTC' else s}USD")
    if d.get("error"):
        raise ValueError(d["error"])
    return float(list(d["result"].values())[0]["c"][0])


def _chainlink(s):
    a = CHAINLINK_BASE[s]
    r = ct._rpc(ct.BASE_RPCS, "eth_call", [{"to": a, "data": "0xfeaf968c"}, "latest"])
    dec = int(ct._call(ct.BASE_RPCS, a, "decimals()"), 16)
    updated = int(r[2 + 192:2 + 256], 16)
    return int(r[2 + 64:2 + 128], 16) / 10 ** dec, int(time.time()) - updated


def _one(sym):
    s = ALIAS.get(sym, sym)
    src = {}
    jobs = {"coinbase": lambda: _coinbase(s), "kraken": lambda: _kraken(s)}
    if s in CHAINLINK_BASE:
        jobs["chainlink_base"] = lambda: _chainlink(s)
    with ThreadPoolExecutor(3) as ex:
        fut = {k: ex.submit(f) for k, f in jobs.items()}
    age = None
    for k, f in fut.items():
        try:
            v = f.result()
            if k == "chainlink_base":
                v, age = v
            if v and v > 0:
                src[k] = v
        except Exception:
            pass
    if not src:
        return {"symbol": sym, "error": "no source has a USD price for this symbol"}
    vals = list(src.values())
    mid = statistics.median(vals)
    spread = (max(vals) - min(vals)) / mid * 100 if len(vals) > 1 else None
    verdict = "SINGLE_SOURCE" if len(vals) == 1 else ("AGREE" if spread <= 0.5 else ("CHECK" if spread <= 2 else "DISAGREE"))
    out = {"symbol": sym, "usd": round(mid, 8), "verdict": verdict, "spread_pct": round(spread, 4) if spread is not None else None,
           "sources": {k: round(v, 8) for k, v in src.items()}}
    if s != sym:
        out["priced_as"] = s
    if age is not None:
        out["chainlink_age_s"] = age
    return out


def check(symbols):
    syms = [x.strip().upper() for x in str(symbols or "").split(",") if x.strip()]
    if not syms:
        return {"error": "send symbols=, e.g. ETH or ETH,BTC,USDC (up to 5)"}
    if len(syms) > 5 or not all(SYM.match(x) for x in syms):
        return {"error": "up to 5 ticker symbols, letters/digits only (e.g. ETH,BTC,SOL)"}
    with ThreadPoolExecutor(len(syms)) as ex:
        rows = list(ex.map(_one, syms))
    return {"service": "OMENZ Price Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prices": rows,
            "verdicts": {"AGREE": "sources within 0.5%", "CHECK": "0.5-2% apart: fine for display, re-check before a large trade",
                         "DISAGREE": "over 2% apart: don't act on this price", "SINGLE_SOURCE": "only one source answered"},
            "limits": "USD reference prices, not an executable quote; DEX liquidity and slippage not included."}
