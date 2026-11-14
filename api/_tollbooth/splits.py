"""OMENZ Split Check: verify an on-chain revenue split before you pay into it (or before you trust a seller's rev-share claim).

FIND THE ETHER tier 2 (founder 2026-11-14): sellers can route x402 payments into a 0xSplits v2 split (e.g. 97% seller /
3% OMENZ); the split pays out on-chain, nobody holds funds. This tool proves what a split actually does:
- is the address a 0xSplits v2 split (has splitHash())?
- does a claimed config (recipients + allocations) hash to the on-chain splitHash? (one call)
- otherwise, recent SplitUpdated events (last ~14 days) reveal the current config
- owner (zero address = immutable: nobody can change the shares later), USDC waiting to be distributed
Read-only, public chain data (Base mainnet or Base Sepolia). Deterministic, no AI calls.
"""
import json
import re
import time
import urllib.request

from eth_abi import decode, encode
from eth_utils import keccak

VERSION = "0.1.0"
RPC = {"base": ["https://base-rpc.publicnode.com", "https://mainnet.base.org"],
       "base-sepolia": ["https://base-sepolia-rpc.publicnode.com", "https://sepolia.base.org"]}
USDC = {"base": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "base-sepolia": "0x036cbd53842c5426634e7929541ec2318f3dcf7e"}
FACTORY_PUSH_V22 = "0x8E8eB0cC6AE34A38B67D5Cf91ACa38f60bc3Ecf4"  # same address on Base and Base Sepolia (0xSplits deployments)
SPLIT_TUPLE = "(address[],uint256[],uint256,uint16)"
SIG = {"splitHash": keccak(text="splitHash()")[:4].hex(), "owner": keccak(text="owner()")[:4].hex(),
       "getSplitBalance": keccak(text="getSplitBalance(address)")[:4].hex()}
TOPIC_UPDATED = "0x" + keccak(text=f"SplitUpdated({SPLIT_TUPLE})").hex()
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


class SplitError(Exception):
    pass


def _rpc(net, method, params):
    last = None
    for url in RPC[net]:
        try:
            req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "OMENZ-splits/0.1"})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            if "result" in d:
                return d["result"]
            last = (d.get("error") or {}).get("message")
            if "revert" in str(last).lower() or "execution" in str(last).lower():
                raise SplitError("call reverted")
        except SplitError:
            raise
        except Exception as e:
            last = type(e).__name__
    raise SplitError(f"Base RPC unavailable ({last})")


def _call(net, to, data):
    return _rpc(net, "eth_call", [{"to": to, "data": data}, "latest"])


def split_hash(recipients, allocations, total, incentive=0):
    """keccak256(abi.encode(Split)) exactly as SplitV2Lib.getHash."""
    return "0x" + keccak(encode([SPLIT_TUPLE], [([r for r in recipients], [int(a) for a in allocations], int(total), int(incentive))])).hex()


def _norm(cfg):
    rec = [r.lower() for r in cfg["recipients"]]
    alloc = [int(a) for a in cfg["allocations"]]
    if len(rec) != len(alloc) or not rec:
        raise SplitError("recipients and allocations must be non-empty lists of the same length")
    if not all(ADDR.match(r) for r in rec):
        raise SplitError("recipients must be 0x addresses")
    total = int(cfg.get("total_allocation") or sum(alloc))
    return rec, alloc, total, int(cfg.get("distribution_incentive") or 0)


def check(address, network="base", claimed=None, beneficiary=None):
    net = (network or "base").lower()
    if net not in RPC:
        raise SplitError("network must be base or base-sepolia")
    if not ADDR.match(address or ""):
        raise SplitError("address must be 0x + 40 hex characters")
    a = address.lower()
    out = {"version": VERSION, "address": a, "network": net, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    code = _rpc(net, "eth_getCode", [a, "latest"])
    if code in ("0x", "0x0", None):
        return {**out, "is_split": False, "verdict": "NOT_A_CONTRACT", "note": "a plain wallet: payments here are not split"}
    try:
        onchain = _call(net, a, "0x" + SIG["splitHash"])
    except SplitError:
        return {**out, "is_split": False, "verdict": "NOT_A_SPLIT", "note": "a contract without splitHash(): not a 0xSplits v2 split"}
    owner = "0x" + _call(net, a, "0x" + SIG["owner"])[-40:]
    bal = _call(net, a, "0x" + SIG["getSplitBalance"] + "0" * 24 + USDC[net][2:])
    split_bal, warehouse_bal = decode(["uint256", "uint256"], bytes.fromhex(bal[2:]))
    out.update({"is_split": True, "split_hash": onchain, "owner": owner, "immutable": int(owner, 16) == 0,
                "usdc_waiting_to_distribute": split_bal / 1e6, "usdc_in_warehouse": warehouse_bal / 1e6})
    cfg = None
    if claimed:
        rec, alloc, total, inc = _norm(claimed)
        match = split_hash(rec, alloc, total, inc).lower() == onchain.lower()
        out["claimed_config_matches"] = match
        if match:
            cfg = (rec, alloc, total, inc)
    if cfg is None:  # discover from recent SplitUpdated events
        head = int(_rpc(net, "eth_blockNumber", []), 16)
        frm = head
        for _ in range(12):  # ~14 days of Base in 50k-block windows
            lo = max(0, frm - 50000)
            logs = _rpc(net, "eth_getLogs", [{"address": a, "topics": [TOPIC_UPDATED], "fromBlock": hex(lo), "toBlock": hex(frm)}])
            if logs:
                (rec, alloc, total, inc), = decode([SPLIT_TUPLE], bytes.fromhex(logs[-1]["data"][2:]))
                cand = ([r.lower() for r in rec], list(alloc), total, inc)
                if split_hash(*cand).lower() == onchain.lower():
                    cfg = cand
                    out["config_source"] = f"SplitUpdated event in block {int(logs[-1]['blockNumber'], 16)}"
                break
            frm = lo - 1
            if lo == 0:
                break
    if cfg:
        rec, alloc, total, inc = cfg
        out["config"] = {"recipients": [{"address": r, "allocation": al, "share_pct": round(100 * al / total, 4)} for r, al in zip(rec, alloc)],
                         "total_allocation": total, "distribution_incentive_pct": inc / 1e4}
        if beneficiary:
            b = beneficiary.lower()
            share = sum(100 * al / total for r, al in zip(rec, alloc) if r == b)
            out["beneficiary"] = {"address": b, "share_pct": round(share, 4), "included": share > 0}
        out["verdict"] = "VERIFIED_SPLIT" if out["immutable"] else "VERIFIED_SPLIT_MUTABLE"
        if claimed and not out.get("claimed_config_matches"):
            out["verdict"] = "CLAIM_DOES_NOT_MATCH"
            out["note"] = "the claimed recipients/allocations do NOT match this split; 'config' shows what it actually pays"
    else:
        out["verdict"] = "SPLIT_CONFIG_UNKNOWN" if not claimed else "CLAIM_DOES_NOT_MATCH"
        out["note"] = ("pass the claimed recipients/allocations to verify them against splitHash" if not claimed
                       else "the claimed recipients/allocations do NOT match what this split pays")
    if not out["immutable"] and out.get("verdict", "").startswith("VERIFIED"):
        out["warning"] = "the split has an owner who can change the shares later"
    return out
