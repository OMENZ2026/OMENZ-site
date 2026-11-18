"""OMENZ Checkout: the buyer layer. One call before an agent pays, one after.

open:  (optional) market/cheapest -> authorize -> seller track record -> budget/spend  => GO / REVIEW / STOP + checkout_id
close: pay/verify -> delivery-check -> signed spend receipt -> budget/release if it never paid -> seller track record

Seller track records are aggregate outcomes per seller host (no buyer identity, no payload contents): the transaction
telemetry that makes the next checkout smarter. Provider-neutral: works with any wallet, any x402 seller on Base.
Bookkeeping and checks only: OMENZ never holds, moves or signs for the buyer's money.
"""
import hashlib
import secrets
import time
import urllib.parse

import buyer
from locker import LockerError, _kv

VERSION = "0.1.0"
CK_TTL = 7 * 86400
BAD = ("PAID_NOT_DELIVERED", "PAID_PARTLY_DELIVERED")
GOOD = ("GOOD_BUY", "PAID_DELIVERY_UNCHECKED")


def _host(u):
    u = str(u or "")
    return (urllib.parse.urlparse(u if "://" in u else "https://" + u).hostname or "").lower()


def _seller_key(host):
    return "sr_" + hashlib.sha256(("omenz-seller|" + host).encode()).hexdigest()[:24]


def _blank(host):
    return {"host": host, "checkouts": 0, "outcomes": {}, "usd_settled": 0.0, "first": None, "last": None}


def seller_record(host_or_url):
    host = _host(host_or_url)
    if not host or "." not in host:
        raise LockerError(400, "host or url required")
    rec = _kv("GET", _seller_key(host)) or _blank(host)
    o = rec["outcomes"]
    good = sum(o.get(k, 0) for k in GOOD)
    bad = sum(o.get(k, 0) for k in BAD)
    return {"host": host, "checkouts_opened": rec["checkouts"], "purchases_closed": sum(o.values()), "outcomes": o,
            "delivery_rate": round(good / (good + bad), 3) if good + bad else None,
            "usd_settled_verified": round(rec["usd_settled"], 6),
            "seller_reported_sales_verified": rec.get("sales_verified", 0), "seller_reported_sales_usd": round(rec.get("sales_usd", 0.0), 6),
            "distinct_payers": len(rec.get("payer_hashes", [])), "first_seen": rec["first"], "last_seen": rec["last"],
            "basis": "OMENZ Checkout closes: settlement verified on Base and delivery checked against the seller's advertised output. Aggregate only."}


def _seller_bump(host, outcome=None, usd=0.0, opened=False):
    try:
        k = _seller_key(host)
        rec = _kv("GET", k) or _blank(host)
        now = int(time.time())
        rec["first"] = rec["first"] or now
        rec["last"] = now
        if opened:
            rec["checkouts"] += 1
        if outcome:
            rec["outcomes"][outcome] = rec["outcomes"].get(outcome, 0) + 1
            rec["usd_settled"] = round(rec["usd_settled"] + float(usd or 0), 6)
        _kv("PUT", k, rec)
    except Exception:
        pass  # a track-record write must never block a purchase


def open_(body, budget_key=None):
    import authorize
    body = body if isinstance(body, dict) else {}
    url, picked = str(body.get("url") or "").strip(), None
    if not url and body.get("q"):
        cw = buyer.cheapest_working(body["q"], body.get("max_price_usd"), body.get("network"), want=3)
        picked = cw.get("pick")
        if not picked:
            return {"checkout_id": None, "decision": "STOP", "reasons": ["no working provider found for that need within your max price"],
                    "skipped_not_working": cw.get("skipped_not_working", [])}
        url = picked["url"]
        body = {**body, "method": picked.get("method") or body.get("method")}
    if not url:
        return {"checkout_id": None, "decision": "STOP",
                "reasons": ["send url (what you are about to pay) or q (what you need; OMENZ picks the cheapest working seller)"]}
    az = authorize.authorize({**body, "url": url})
    if az.get("decision") == "ERROR":
        return {"checkout_id": None, "decision": "STOP", "reasons": [az.get("error")]}
    a = az.get("authorization") or {}
    host = _host(url)
    try:
        sr = seller_record(host)
    except Exception:
        sr = None
    reasons = list(az.get("decline_reasons") or []) + list(az.get("review_reasons") or [])
    decision = {"APPROVE": "GO", "REVIEW": "REVIEW", "DECLINE": "STOP"}[az["decision"]]
    if sr and sr["delivery_rate"] is not None and sr["purchases_closed"] >= 5 and sr["delivery_rate"] < 0.6 and decision == "GO":
        decision = "REVIEW"
        reasons.append(f"seller delivered on only {int(sr['delivery_rate'] * 100)}% of {sr['purchases_closed']} checked purchases")
    spend = None
    if decision == "GO" and body.get("budget_id"):
        spend = buyer.budget_spend(body["budget_id"], budget_key, {
            "amount_usd": a.get("amount_usd") or 0, "recipient": a.get("pay_to"), "agent": body.get("agent"), "url": url,
            "memo": body.get("purpose"), "idempotency_key": body.get("idempotency_key")})
        if spend["decision"] != "ALLOW":
            decision = "STOP" if spend["decision"] == "DENY" else "REVIEW"
            reasons += [f"budget: {r}" for r in spend.get("reasons", [])]
    cid = "ck_" + secrets.token_hex(10)
    now = int(time.time())
    try:
        _kv("PUT", cid, {"v": 0, "url": url, "method": a.get("method"), "pay_to": a.get("pay_to"), "amount_usd": a.get("amount_usd"),
                         "decision": decision, "budget_id": body.get("budget_id") if spend and spend["decision"] == "ALLOW" else None,
                         "spend_id": (spend or {}).get("spend_id"), "agent": str(body.get("agent") or "")[:80] or None,
                         "purpose": str(body.get("purpose") or "")[:300] or None, "job_id": str(body.get("job_id") or "")[:120] or None,
                         "created": now, "expires": now + CK_TTL, "closed": None})
        _seller_bump(host, opened=True)
    except LockerError:
        cid = None
    return {"checkout_id": cid, "decision": decision, "reasons": reasons or ["all checks passed"],
            "pay": {"url": url, "method": a.get("method"), "amount_usd": a.get("amount_usd"), "pay_to": a.get("pay_to"), "network": a.get("network")},
            "picked_by_omenz": bool(picked), "authorization_token": az.get("authorization_token"), "expires_in_s": az.get("expires_in_s"),
            "budget": {k: spend.get(k) for k in ("decision", "spend_id", "remaining_usd")} if spend else None,
            "seller_record": sr,
            "next": {"GO": "Pay the url now, then POST checkout/close with checkout_id + tx_hash (or the PAYMENT-RESPONSE header) + the response you got.",
                     "REVIEW": "Ask your owner before paying.", "STOP": "Do not pay."}[decision]}


def close(body, budget_key=None):
    body = body if isinstance(body, dict) else {}
    cid = str(body.get("checkout_id") or "")
    if not cid.startswith("ck_"):
        return {"verdict": "BAD_INPUT", "reasons": ["checkout_id from checkout/open is required"]}
    ck = _kv("GET", cid)
    if ck is None or ck["expires"] < time.time():
        return {"verdict": "BAD_INPUT", "reasons": ["no such checkout (or older than 7 days)"]}
    if ck.get("closed"):
        return {"checkout_id": cid, "already_closed": True, **ck["closed"]}
    if body.get("not_paid"):
        out = {"verdict": "NOT_PAID", "reasons": ["buyer reports it did not pay"]}
    else:
        out = buyer.spend_receipt({"url": ck["url"], "method": ck["method"], "tx_hash": body.get("tx_hash"),
                                   "payment_response": body.get("payment_response"), "expected_pay_to": ck["pay_to"],
                                   "expected_amount_usd": ck["amount_usd"], "delivered": body.get("delivered"), "schema": body.get("schema"),
                                   "must_have": body.get("must_have"), "purpose": ck.get("purpose"), "agent": ck.get("agent"),
                                   "job_id": ck.get("job_id")})
        if out.get("verdict") == "BAD_INPUT":
            return out
    released = None
    unpaid = out["verdict"] in ("NOT_PAID", "PAYMENT_NOT_CONFIRMED")
    if unpaid and ck.get("budget_id") and ck.get("spend_id") and (out["verdict"] == "NOT_PAID" or body.get("release_if_unconfirmed")):
        if not budget_key:
            released = {"released": False, "error": "send header X-Budget-Key to give the money back to the budget"}
        else:
            try:
                released = buyer.budget_release(ck["budget_id"], budget_key, ck["spend_id"], "checkout " + out["verdict"].lower())
            except LockerError as e:
                released = {"released": False, "error": e.msg}
    if not unpaid:
        _seller_bump(_host(ck["url"]), outcome=out["verdict"], usd=(out.get("payment") or {}).get("amount_usd") or 0)
    ck["closed"] = {"verdict": out["verdict"], "reasons": out.get("reasons"), "at": int(time.time())}
    try:
        _kv("PUT", cid, ck)
    except LockerError:
        pass
    return {"checkout_id": cid, "verdict": out["verdict"], "reasons": out.get("reasons"), "payment": out.get("payment"),
            "delivery": out.get("delivery"), "signed_receipt": out.get("signed"), "next": out.get("next"),
            "budget_release": released, "seller_record_updated": not unpaid}


def fee(amount_usd):
    """Credits pricing for the buyer layer: 1% of the purchase, minimum $0.0002, per side (open / close)."""
    return round(max(0.01 * float(amount_usd or 0), 0.0002), 6)


# ---------------------------------------------------------------- Seller side: sale/record
def sale_record(body):
    """A seller (or its x402 middleware) reports one sale. OMENZ checks the payment really reached the payTo that the
    sold URL advertises right now, on Base, then counts it once (idempotent per tx) in the seller's public track record.
    Wash trading is possible (a seller paying itself), so the record shows distinct payers next to the totals."""
    import x402_probe
    body = body if isinstance(body, dict) else {}
    url = str(body.get("url") or "").strip()
    if not url:
        return {"verdict": "BAD_INPUT", "reasons": ["send url: the paid route that was sold"]}
    q = x402_probe.quote(url, str(body.get("method") or "GET").upper())
    pay_tos = sorted({(o.get("pay_to") or "").lower() for o in q.get("options") or [] if o.get("network") == "base" and o.get("pay_to")})
    if not pay_tos:
        return {"verdict": "NO_LIVE_PAYTO", "reasons": [f"the url's live 402 shows no Base payTo ({q.get('status')}); we only count sales we can tie to it"]}
    pv = buyer.pay_verify({"tx_hash": body.get("tx_hash"), "payment_response": body.get("payment_response"), "expected_pay_to": pay_tos[0],
                           "min_confirmations": 1})
    if pv["verdict"] == "BAD_INPUT":
        return pv
    pay = pv.get("payment") or {}
    if pv["verdict"] != "SETTLED" and (pay.get("to") or "").lower() in pay_tos:
        pv["verdict"] = "SETTLED"
    if pv["verdict"] != "SETTLED" or (pay.get("to") or "").lower() not in pay_tos:
        return {"verdict": "NOT_COUNTED", "reasons": pv.get("reasons") or ["payment did not settle to this url's payTo"], "payment": pay}
    host = _host(url)
    tx = pv["tx_hash"].lower()
    dk = "sx_" + hashlib.sha256(("omenz-sale|" + tx).encode()).hexdigest()[:24]
    if _kv("GET", dk):
        return {"verdict": "ALREADY_COUNTED", "tx_hash": tx, "seller_record": seller_record(host)}
    _kv("PUT", dk, {"host": host, "at": int(time.time())})
    k = _seller_key(host)
    rec = _kv("GET", k) or _blank(host)
    now = int(time.time())
    rec["first"] = rec["first"] or now
    rec["last"] = now
    rec["sales_verified"] = rec.get("sales_verified", 0) + 1
    rec["sales_usd"] = round(rec.get("sales_usd", 0.0) + float(pay.get("amount_usd") or 0), 6)
    payers = set(rec.get("payer_hashes", []))
    payers.add(hashlib.sha256(("omenz-payer|" + (pay.get("from") or "")).encode()).hexdigest()[:16])
    rec["payer_hashes"] = sorted(payers)[-5000:]
    _kv("PUT", k, rec)
    receipt = {"schema": "omenz.sale-receipt.v0", "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seller_host": host,
               "url": url[:500], "tx_hash": tx, "amount_usd": pay.get("amount_usd"), "pay_to": pay.get("to"), "settled_at": pv.get("settled_at")}
    try:
        import contracts
        token = contracts._sign(receipt)
    except Exception:
        token = None
    return {"verdict": "COUNTED", **receipt, "signed": token, "seller_record": seller_record(host)}
