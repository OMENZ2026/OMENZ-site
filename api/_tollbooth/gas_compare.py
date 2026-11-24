"""OMENZ Gas Compare: what does it cost to move money on each major chain RIGHT NOW, and which is cheapest? (2026-11-24)

Demand (market index 11-24): 'gas price/estimate/fee' = 260 endpoints, 137 sellers, 1,248 payers in 30 days, median $0.003;
most sellers cover one chain. One call here: base fee + suggested tip on 7 EVM chains, the USD cost of a native transfer
and a USDC/ERC-20 transfer on each, and the cheapest chain. Public RPCs + Coinbase public spot prices; no keys, no AI.
"""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

VERSION = "0.1.0"
CHAINS = {  # name: (chain id, rpcs, native symbol)
    "ethereum": (1, ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"], "ETH"),
    "base": (8453, ["https://mainnet.base.org", "https://base-rpc.publicnode.com"], "ETH"),
    "arbitrum": (42161, ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc"], "ETH"),
    "optimism": (10, ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"], "ETH"),
    "polygon": (137, ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"], "POL"),
    "bsc": (56, ["https://bsc-rpc.publicnode.com", "https://bsc-dataseed.bnbchain.org"], "BNB"),
    "avalanche": (43114, ["https://avalanche-c-chain-rpc.publicnode.com", "https://api.avax.network/ext/bc/C/rpc"], "AVAX"),
}
GAS = {"native_transfer": 21000, "erc20_transfer": 62000}
_cache = {}


def _rpc(rpcs, method, params):
    last = None
    for u in rpcs:
        try:
            req = urllib.request.Request(u, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "OMENZ-gas/0.1"})
            d = json.load(urllib.request.urlopen(req, timeout=6))
            if "result" in d:
                return d["result"]
            last = (d.get("error") or {}).get("message")
        except Exception as e:
            last = type(e).__name__
    raise RuntimeError(last or "rpc failed")


def _usd(sym):
    k = "px:" + sym
    if k in _cache and time.time() - _cache[k][1] < 120:
        return _cache[k][0]
    d = json.load(urllib.request.urlopen(urllib.request.Request(f"https://api.coinbase.com/v2/prices/{sym}-USD/spot",
                                                                headers={"User-Agent": "OMENZ-gas/0.1"}), timeout=6))
    p = float(d["data"]["amount"])
    _cache[k] = (p, time.time())
    return p


def _one(name):
    cid, rpcs, sym = CHAINS[name]
    try:
        blk = _rpc(rpcs, "eth_getBlockByNumber", ["latest", False])
        base = int(blk.get("baseFeePerGas") or "0x0", 16)
        try:
            tip = int(_rpc(rpcs, "eth_maxPriorityFeePerGas", []), 16)
        except Exception:
            tip = max(int(_rpc(rpcs, "eth_gasPrice", []), 16) - base, 0)
        if not base:  # pre-1559 style chains
            base, tip = int(_rpc(rpcs, "eth_gasPrice", []), 16), 0
        price = _usd(sym)
        per_gas = base + tip
        row = {"chain": name, "chain_id": cid, "native": sym, "block": int(blk["number"], 16),
               "block_age_s": max(int(time.time()) - int(blk["timestamp"], 16), 0),
               "base_fee_gwei": round(base / 1e9, 6), "priority_fee_gwei": round(tip / 1e9, 6), f"{sym.lower()}_usd": price}
        for k, g in GAS.items():
            row[f"{k}_usd"] = round(g * per_gas / 1e18 * price, 6)
        return row
    except Exception as e:
        return {"chain": name, "error": f"unavailable right now ({str(e)[:60]})"}


def compare(chains=None):
    want = [c.strip().lower() for c in str(chains or "").split(",") if c.strip()] or list(CHAINS)
    bad = [c for c in want if c not in CHAINS]
    if bad:
        return {"error": f"unknown chain(s): {', '.join(bad)}", "supported": list(CHAINS)}
    with ThreadPoolExecutor(len(want)) as ex:
        rows = list(ex.map(_one, want))
    ok = sorted([r for r in rows if "error" not in r], key=lambda r: r["erc20_transfer_usd"])
    return {"service": "OMENZ Gas Compare", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cheapest_for_token_transfer": ok[0]["chain"] if ok else None,
            "cheapest_for_native_transfer": min(ok, key=lambda r: r["native_transfer_usd"])["chain"] if ok else None,
            "chains": ok + [r for r in rows if "error" in r],
            "assumptions": {"gas_units": GAS, "fee_per_gas": "base fee + suggested priority fee of the latest block",
                            "prices": "Coinbase public spot, cached up to 2 min"},
            "limits": "Execution fee only: rollups (Base, Arbitrum, Optimism) add a small L1 data fee; your real gas use depends on the contract. Not a guarantee of inclusion."}
