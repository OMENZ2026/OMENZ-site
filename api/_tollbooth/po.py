"""OMENZ Agent Purchase Order: a signed, single-use "this agent may spend up to $X with seller Y for Z, until T".

Big Bro list (founder-pasted 2026-11-18), transaction-utility tier. Passport = what a job may do in general; a Purchase
Order = ONE specific purchase, pre-approved by whoever controls the money.
  po/issue   (owner or spender of a Shared Budget, or standalone) -> signed PO token (Ed25519, verifiable offline)
  po/redeem  (the buyer agent, or the seller before serving) -> checks signature, expiry, payee, amount, single use;
             if budget-backed, draws the amount from the Shared Budget (team caps + delegation tree apply); marks it used.
Bookkeeping and signatures only: OMENZ never holds or moves money. Deterministic, no AI calls.
"""
import hashlib
import secrets
import time

import buyer
import contracts
from locker import LockerError, _kv

VERSION = "0.1.0"
MAX_HOURS = 7 * 24


def issue(body, budget_key=None):
    body = body if isinstance(body, dict) else {}
    try:
        max_usd = float(body["max_usd"])
        hours = float(body.get("expires_in_hours") or 24)
    except (KeyError, TypeError, ValueError):
        raise LockerError(400, "max_usd (number) is required; expires_in_hours must be a number")
    if max_usd <= 0 or max_usd > 1e6:
        raise LockerError(400, "max_usd must be above 0")
    if not 0 < hours <= MAX_HOURS:
        raise LockerError(400, f"expires_in_hours must be 0..{MAX_HOURS}")
    pay_to = str(body.get("pay_to") or "").strip().lower()
    if pay_to and not buyer.ADDR.match(pay_to):
        raise LockerError(400, "pay_to must be a 0x address")
    seller = str(body.get("seller") or "").strip()[:200]
    if not (pay_to or seller):
        raise LockerError(400, "name the seller: pay_to (0x payout address) and/or seller (host or url)")
    bid = body.get("budget_id")
    if bid:
        buyer._load(bid, budget_key)  # proves the issuer controls that budget (owner or spender key)
    now = int(time.time())
    po = {"schema": "omenz.purchase-order.v0", "po_id": "po_" + secrets.token_hex(10), "iat": now, "exp": now + int(hours * 3600),
          "agent": str(body.get("agent") or "")[:80] or None, "for": str(body.get("for") or body.get("purpose") or "")[:300] or None,
          "seller": seller or None, "pay_to": pay_to or None, "max_usd": round(max_usd, 6), "budget_id": bid or None,
          "job_id": str(body.get("job_id") or "")[:120] or None, "single_use": True, "issuer": "omenz.org"}
    token = contracts._sign(po)
    return {"po": po, "token": token,
            "note": "Give the token to the buying agent. It (or the seller) calls po/redeem before paying; the PO works once. "
                    "Verify offline with GET /v1/passport/key."}


def redeem(body, budget_key=None):
    body = body if isinstance(body, dict) else {}
    po = contracts._open(body.get("token"))
    if not po or po.get("schema") != "omenz.purchase-order.v0":
        return {"decision": "DENY", "reasons": ["not a valid OMENZ purchase order (bad or forged signature)"]}
    now = int(time.time())
    reasons = []
    try:
        amt = float(body.get("amount_usd"))
    except (TypeError, ValueError):
        return {"decision": "DENY", "reasons": ["amount_usd (what you are about to pay) is required"], "po": po}
    if now >= po["exp"]:
        reasons.append("purchase order expired")
    if amt > po["max_usd"] + 1e-9:
        reasons.append(f"amount ${amt} is above the PO's max ${po['max_usd']}")
    pay_to = str(body.get("pay_to") or "").strip().lower()
    if po.get("pay_to") and pay_to and pay_to != po["pay_to"]:
        reasons.append("payee does not match the PO")
    if po.get("pay_to") and not pay_to:
        reasons.append("send pay_to (the address you are paying) to match the PO")
    seller = str(body.get("seller") or body.get("url") or "").lower()
    if po.get("seller") and seller and po["seller"].lower() not in seller and seller not in po["seller"].lower():
        reasons.append("seller does not match the PO")
    used_key = "pu_" + hashlib.sha256(po["po_id"].encode()).hexdigest()[:24]
    used = _kv("GET", used_key)
    if used:
        reasons.append(f"purchase order already used at {used.get('at')}")
    if reasons:
        return {"decision": "DENY", "reasons": reasons, "po": po}
    spend = None
    if po.get("budget_id"):
        spend = buyer.budget_spend(po["budget_id"], budget_key, {"amount_usd": amt, "recipient": pay_to or po.get("pay_to"),
                                                                  "agent": po.get("agent"), "memo": "PO " + po["po_id"],
                                                                  "idempotency_key": po["po_id"]})
        if spend["decision"] != "ALLOW":
            return {"decision": spend["decision"], "reasons": ["budget: " + r for r in spend.get("reasons", [])], "po": po}
    _kv("PUT", used_key, {"at": now, "amount_usd": amt})
    rec = {"schema": "omenz.po-redemption.v0", "po_id": po["po_id"], "amount_usd": amt, "pay_to": pay_to or po.get("pay_to"),
           "redeemed_at": now, "budget_spend_id": (spend or {}).get("spend_id")}
    return {"decision": "ALLOW", "po": po, "redemption": rec, "signed_redemption": contracts._sign(rec),
            "budget": {k: spend.get(k) for k in ("spend_id", "remaining_usd")} if spend else None,
            "next": "Pay now. The PO is used up. If the purchase fails, budget/release the spend_id (if budget-backed)."}
