"""OMENZ Receipt Locker v0: machine-readable proof that an agent paid someone, for what, when.
Founder "Build all" 2026-11-11 (agent utilities family #5).

- put: record a receipt. If tx_hash + network Base are given, OMENZ checks the chain: a real USDC Transfer from payer to
  payee of at least the stated amount must exist in that transaction, so chain_verified=true means the payment is on Base.
  The receipt is content-addressed: receipt_id = sha256 of its canonical JSON.
- verify (free): anyone fetches a receipt by id and gets it back with the hash recomputed and the chain check result.
Receipts are public by id (they hold no secrets); don't put private data in "note".
"""
import hashlib
import json
import math
import os
import re
import time
import urllib.request

from locker import LockerError, _kv

RPC = os.environ.get("BASE_RPC", "https://mainnet.base.org")
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
FIELDS = ("payer", "payee", "amount", "currency", "network", "tx_hash", "job_id", "service", "request_sha256", "response_sha256", "note")


def _chain_check(tx_hash, payer, payee, amount):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionReceipt", "params": [tx_hash]}).encode()
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json", "User-Agent": "omenz-receipts/0"}), timeout=8))
    except Exception:
        return {"checked": False, "reason": "chain RPC unavailable"}
    rec = r.get("result")
    if not rec:
        return {"checked": True, "verified": False, "reason": "transaction not found"}
    if rec.get("status") != "0x1":
        return {"checked": True, "verified": False, "reason": "transaction failed"}
    want = int(round(float(amount) * 1e6))
    for lg in rec.get("logs", []):
        t = lg.get("topics", [])
        if lg.get("address", "").lower() == USDC and len(t) == 3 and t[0] == TRANSFER:
            frm, to = "0x" + t[1][-40:], "0x" + t[2][-40:]
            val = int(lg.get("data", "0x0"), 16)
            if frm.lower() == payer.lower() and to.lower() == payee.lower() and val >= want:
                return {"checked": True, "verified": True, "usdc_amount": val / 1e6, "block": int(rec["blockNumber"], 16)}
    return {"checked": True, "verified": False, "reason": "no matching USDC transfer (payer, payee, amount) in this tx"}


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def put(data):
    if not isinstance(data, dict):
        raise LockerError(400, "JSON object required")
    rec = {k: str(data[k])[:300] for k in FIELDS if data.get(k) not in (None, "")}
    for k in ("payer", "payee", "amount"):
        if k not in rec:
            raise LockerError(400, f"{k} is required")
    for k in ("payer", "payee"):
        if not ADDR.match(rec[k]) and len(rec[k]) > 120:
            raise LockerError(400, f"{k} too long")
    try:
        amt = float(rec["amount"])
    except ValueError:
        raise LockerError(400, "amount must be a number")
    if not math.isfinite(amt) or amt <= 0:
        raise LockerError(400, "amount must be a positive finite number")
    rec.setdefault("currency", "USDC")
    rec["recorded_at"] = int(time.time())
    rec["recorded_by"] = "omenz.org receipt locker v0"
    chain = {"checked": False, "reason": "no tx_hash given"}
    if "tx_hash" in rec:
        if not TX.match(rec["tx_hash"]):
            raise LockerError(400, "tx_hash must be 0x + 64 hex")
        if rec.get("network", "base").lower() in ("base", "eip155:8453") and ADDR.match(rec["payer"]) and ADDR.match(rec["payee"]):
            chain = _chain_check(rec["tx_hash"], rec["payer"], rec["payee"], rec["amount"])
        else:
            chain = {"checked": False, "reason": "chain check supports USDC on Base with 0x addresses"}
    rec["chain"] = chain
    rid = "rc_" + hashlib.sha256(_canon(rec).encode()).hexdigest()[:40]
    _kv("PUT", rid, rec)
    return {"receipt_id": rid, "receipt": rec, "verify_url": f"https://www.omenz.org/api/tollbooth/v1/receipt/verify?id={rid}"}


def verify(rid):
    if not (rid or "").startswith("rc_"):
        raise LockerError(400, "id required")
    rec = _kv("GET", rid)
    if rec is None:
        raise LockerError(404, "no such receipt")
    ok = "rc_" + hashlib.sha256(_canon(rec).encode()).hexdigest()[:40] == rid
    return {"receipt_id": rid, "intact": ok, "receipt": rec}
