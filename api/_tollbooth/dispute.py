"""OMENZ Dispute Packet: a purchase went bad; one call builds the machine-readable case.

Big Bro + founder 2026-11-18 (value-protection tier, $0.10-$1): "build machine-readable evidence when a transaction goes bad".
Assembles, from primitives OMENZ already runs:
  settlement   Settlement Rescue (EIP-3009 state / tx) -> did money move, how much, to whom, when; duplicates
  promise      the seller's own advertised output (live x402 discovery) + the authorized price/payee if a checkout exists
  delivery     Delivery Check of what came back (missing fields, wrong kinds, error bodies)
  timeline     checkout opened -> paid -> settled -> delivered/failed
  claim        a signed refund request (finance/refund-request format) with remedy + amount + evidence strength
  bundle       every piece hash-listed and Ed25519-signed (evidence/bundle), verifiable offline
OMENZ packages and signs the evidence; it never rules on the dispute and never moves money. Deterministic, no AI calls.
"""
import hashlib
import json
import time

import buyer
import rescue
from locker import LockerError, _kv

VERSION = "0.1.0"
ISSUES = ("not_delivered", "wrong_output", "partial", "overcharged", "duplicate", "other")


def _h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def packet(body):
    import contracts
    import finance
    body = body if isinstance(body, dict) else {}
    issue = str(body.get("issue") or "not_delivered").lower()
    if issue not in ISSUES:
        return {"status": "BAD_INPUT", "reasons": [f"issue must be one of {list(ISSUES)}"]}
    ck = None
    if str(body.get("checkout_id") or "").startswith("ck_"):
        try:
            ck = _kv("GET", body["checkout_id"])
        except LockerError:
            ck = None
    url = str(body.get("url") or (ck or {}).get("url") or "").strip()
    method = str(body.get("method") or (ck or {}).get("method") or "GET").upper()
    pay_to = body.get("pay_to") or (ck or {}).get("pay_to")
    authorized_usd = (ck or {}).get("amount_usd")
    rs = rescue.rescue({"payment_header": body.get("payment_header"), "tx_hash": body.get("tx_hash"), "payer": body.get("payer"),
                        "pay_to": pay_to, "amount_usd": body.get("amount_usd") or authorized_usd, "window_hours": body.get("window_hours") or 72})
    if rs.get("verdict") == "BAD_INPUT":
        return {"status": "BAD_INPUT", "reasons": ["send what you paid with: payment_header (X-PAYMENT), tx_hash, or payer + pay_to + amount_usd (or a checkout_id)"]}
    paid = (rs.get("evidence") or {}).get("transaction", {}).get("payment") or \
        ((rs.get("evidence") or {}).get("matching_payments_on_chain") or [None])[0]
    paid_usd = (paid or {}).get("amount_usd")
    promise, delivery = None, None
    if url:
        try:
            ex, schema, why = buyer._advertised(url, method)
            promise = {"url": url, "method": method, "advertised_output": schema or ex, "basis": "schema" if schema else "example" if ex else None,
                       "why_none": why, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        except Exception as e:
            promise = {"url": url, "method": method, "advertised_output": None, "why_none": type(e).__name__}
    if body.get("delivered") is not None:
        delivery = buyer.delivery_check({"url": None if not promise or not promise.get("advertised_output") else url, "method": method,
                                         "delivered": body.get("delivered"), "schema": body.get("schema"),
                                         "example": None if body.get("schema") else (promise or {}).get("advertised_output")})
    # the case
    findings, strength = [], 0
    if rs["verdict"] in ("SETTLED", "SETTLED_WITH_MISMATCH"):
        findings.append(f"payment settled on Base: {paid_usd} USDC" + (f" to {paid.get('to')}" if paid and paid.get("to") else ""))
        strength += 1
    else:
        findings.append(f"payment state: {rs['verdict']} ({rs.get('safe_next_action') or ''})")
    if (rs.get("evidence") or {}).get("duplicate"):
        findings.append("the same payment appears more than once on-chain (duplicate)")
        strength += 1
    if authorized_usd is not None and paid_usd is not None and paid_usd > authorized_usd + 1e-6:
        findings.append(f"charged {paid_usd} USDC, authorized {authorized_usd}")
        strength += 1
    if delivery:
        if delivery["verdict"] in ("MISMATCH", "PARTIAL"):
            findings.append(f"delivery {delivery['verdict']}: " + "; ".join(delivery.get("reasons") or []))
            strength += 1
        elif delivery["verdict"] == "MATCH" and issue in ("not_delivered", "wrong_output", "partial"):
            findings.append("NOTE: what was delivered matches the seller's advertised output; the claim is weaker")
    elif issue == "not_delivered":
        findings.append("nothing was delivered (buyer reports no response)")
    if promise and promise.get("advertised_output") is not None:
        strength += 1
    remedy = {"duplicate": "refund", "overcharged": "partial_refund", "partial": "partial_refund"}.get(issue, "refund")
    if remedy not in getattr(finance, "REMEDIES", (remedy,)):
        remedy = getattr(finance, "REMEDIES", ("refund",))[0]
    amount_req = body.get("amount_requested_usd")
    if amount_req is None:
        amount_req = (paid_usd - authorized_usd) if issue == "overcharged" and paid_usd and authorized_usd else paid_usd
    seller = body.get("seller") or (promise or {}).get("url") or pay_to or "unknown seller"
    try:
        rr = finance.refund_request({"seller": str(seller)[:200], "buyer": body.get("payer"), "description": (body.get("what") or (ck or {}).get("purpose") or f"x402 purchase of {url}")[:300],
                                     "amount_usd": paid_usd, "ordered_at": (ck or {}).get("created"), "tx_hash": rs.get("record", {}).get("tx_hash")},
                                    failure={"issue": issue, "findings": findings}, receipt_ids=[body.get("checkout_id")] if body.get("checkout_id") else None,
                                    remedy=remedy, amount_usd=amount_req)
    except LockerError as e:
        rr = {"error": e.msg}
    timeline = [t for t in [
        {"at": (ck or {}).get("created"), "event": "checkout opened (authorized)", "amount_usd": authorized_usd} if ck else None,
        {"at": (rs.get("evidence") or {}).get("transaction", {}).get("settled_at"), "event": "payment settled", "amount_usd": paid_usd} if paid else None,
        {"at": None, "event": "delivery " + (delivery["verdict"] if delivery else "missing")},
        {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": "dispute packet built"}] if t]
    pieces = {"settlement": rs.get("record"), "settlement_evidence": rs.get("evidence"), "promise": promise,
              "delivery": delivery, "timeline": timeline, "refund_request": rr.get("request") if isinstance(rr, dict) else None}
    manifest = {k: _h(v) for k, v in pieces.items() if v is not None}
    head = {"schema": "omenz.dispute-packet.v0", "issue": issue, "evidence_strength": strength, "findings": findings,
            "manifest_sha256": manifest, "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "issuer": "omenz.org"}
    try:
        signed = contracts._sign(head)
    except Exception:
        signed = None
    return {"version": VERSION, "status": "OK", "issue": issue,
            "case_strength": "strong" if strength >= 3 else "moderate" if strength == 2 else "weak",
            "findings": findings, "refund_request_token": rr.get("token") if isinstance(rr, dict) else None,
            "gaps": [g for g in ((rr.get("gaps") if isinstance(rr, dict) else None) or [])
                     if not (g.startswith("no purchase snapshot") and (promise or {}).get("advertised_output") is not None)
                     and not (g.startswith("no payment receipts") and rs["verdict"] in ("SETTLED", "SETTLED_WITH_MISMATCH"))],
            "evidence": pieces, "manifest": head, "signed_manifest": signed,
            "next": "Send refund_request_token (and this packet) to the seller, their PO Box or the marketplace you bought through. "
                    "OMENZ packages and signs the evidence; it does not rule on disputes or move money."}
