"""OMENZ prepaid credits: one x402 payment buys a balance; checks draw from it with no per-check settlement.

Why (pricing study 2026-11-15, products/agent_utilities/PRICING_STUDY.md): every x402 settlement costs ~$0.00166 on Base
(PayAI), so per-call prices under ~$0.002 lose money and percentage fees settled per call can never cover it. Real x402
payments have a $0.02 median, and the top 10 wallets make a third of payments. Prepaid credits were the most robust winner
across four buyer-tolerance bands.

- buy(pack_usd) -> credit_id + credit_key (shown once) + balance
- balance(id, key)
- charge(id, key, usd, memo) -> remaining balance (insufficient = refused, nothing charged)
Storage: OMENZ Apify KV, 365 days. Last-write-wins under heavy concurrent use of one credit account (v0; small overdraw risk accepted).
"""
import hashlib
import hmac
import secrets
import time

from locker import LockerError, _kv

VERSION = "0.1.0"
TTL = 365 * 86400


def _h(k):
    return hashlib.sha256(("omenz-credits|" + k).encode()).hexdigest()


def buy(pack_usd):
    cid, key = "cr_" + secrets.token_hex(12), secrets.token_urlsafe(32)
    now = int(time.time())
    rec = {"v": 0, "key_hash": _h(key), "balance_usd": round(float(pack_usd), 6), "bought_usd": round(float(pack_usd), 6),
           "created": now, "expires": now + TTL, "ledger": [{"at": now, "usd": float(pack_usd), "memo": "pack purchase"}]}
    _kv("PUT", cid, rec)
    return {"credit_id": cid, "credit_key": key, "balance_usd": rec["balance_usd"], "expires_at": rec["expires"],
            "use": "send headers X-Credit-Id and X-Credit-Key to POST /api/tollbooth/v1/authorize/credit (no per-check payment)",
            "note": "credit_key is shown once; OMENZ can't recover it."}


def _load(cid, key):
    if not (cid or "").startswith("cr_") or not key:
        raise LockerError(401, "X-Credit-Id and X-Credit-Key headers required")
    rec = _kv("GET", cid)
    if rec is None or rec["expires"] < time.time():
        raise LockerError(404, "no such credit account (or expired)")
    if not hmac.compare_digest(rec["key_hash"], _h(key)):
        raise LockerError(403, "wrong credit key")
    return rec


def balance(cid, key):
    rec = _load(cid, key)
    return {"credit_id": cid, "balance_usd": round(rec["balance_usd"], 6), "bought_usd": rec["bought_usd"],
            "recent": rec["ledger"][-20:][::-1], "expires_at": rec["expires"]}


def charge(cid, key, usd, memo):
    rec = _load(cid, key)
    usd = round(float(usd), 6)
    if rec["balance_usd"] + 1e-9 < usd:
        raise LockerError(402, f"credit balance ${rec['balance_usd']:.4f} is below this check's ${usd:.4f}; buy a pack at /v1/credits/buy-1 or /v1/credits/buy-5")
    rec["balance_usd"] = round(rec["balance_usd"] - usd, 6)
    rec["ledger"] = (rec["ledger"] + [{"at": int(time.time()), "usd": -usd, "memo": str(memo)[:80]}])[-500:]
    _kv("PUT", cid, rec)
    return rec["balance_usd"]


def authorize_fee(amount_usd):
    """Evidence-chosen price: 2% of the payment being authorized, minimum $0.0003 (covers compute; no settlement per check)."""
    return round(max(0.02 * float(amount_usd or 0), 0.0003), 6)
