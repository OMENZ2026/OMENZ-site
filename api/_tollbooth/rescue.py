"""OMENZ Settlement Rescue: "payment weird? give it to us."

The expensive moment in agent commerce: the agent paid (or thinks it did), got a timeout / 5xx / no PAYMENT-RESPONSE,
and must decide whether to pay again. Paying again too early is how agents pay twice; never paying again is how jobs die.

x402 'exact' payments are EIP-3009 USDC authorizations (from, to, value, validAfter, validBefore, nonce). Whether that
exact authorization can still move money is on-chain state: USDC.authorizationState(from, nonce).
  used                       -> SETTLED (we find the AuthorizationUsed tx and verify the transfer)
  unused, past validBefore   -> NOT_SETTLED, and it never can: safe to pay again (once)
  unused, still valid        -> STILL_UNCERTAIN: a facilitator can still settle it until validBefore. Do NOT sign a new one yet.
Also: tx hash path (receipt/mempool), and an on-chain duplicate scan (same payer -> payee -> amount).
Output: verdict + evidence + safe_next_action + duplicate warning + signed record. Read-only, never pays. No AI calls.
"""
import base64
import json
import time

from eth_utils import keccak

import buyer
import guard
import wallet

VERSION = "0.1.0"
T_AUTH_USED = "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"
T_AUTH_CANCELED = "0x1cdd46ff242716cdaa72d159d339a485b3438398348d68f09d7c8c0a59353d81"
SEL_AUTH_STATE = "e94a0102"


def _decode_payment_header(h):
    """X-PAYMENT / PAYMENT-SIGNATURE header (base64 JSON) -> the EIP-3009 authorization inside it."""
    h = str(h or "").strip()
    try:
        d = json.loads(base64.b64decode(h + "=" * (-len(h) % 4)))
    except Exception:
        try:
            d = json.loads(h)
        except Exception:
            return None
    p = d.get("payload") if isinstance(d, dict) else None
    a = (p or {}).get("authorization") if isinstance(p, dict) else None
    return a if isinstance(a, dict) else None


def _nonce_state(frm, nonce):
    data = "0x" + SEL_AUTH_STATE + "0" * 24 + frm.lower()[2:] + nonce.lower()[2:].rjust(64, "0")
    return int(wallet._rpc("eth_call", [{"to": wallet.USDC, "data": data}, "latest"]), 16) == 1


def _find_auth_tx(frm, nonce, hours=48):
    head = int(wallet._rpc("eth_blockNumber", []), 16)
    start = head - int(hours * 3600 / wallet.block_s())
    frm_t = wallet._topic(frm.lower())
    n = "0x" + nonce.lower()[2:].rjust(64, "0")
    logs = wallet.logs_range({"address": wallet.USDC, "topics": [[T_AUTH_USED, T_AUTH_CANCELED], frm_t, n]}, start, head)
    if logs:
        return logs[0]["transactionHash"], ("used" if logs[0]["topics"][0] == T_AUTH_USED else "canceled")
    return None, None


def _sign(rec):
    try:
        import contracts
        return contracts._sign(rec)
    except Exception:
        return None


def rescue(body):
    body = body if isinstance(body, dict) else {}
    now = int(time.time())
    auth = _decode_payment_header(body.get("payment_header")) if body.get("payment_header") else None
    if not auth and isinstance(body.get("authorization"), dict):
        auth = body["authorization"]
    tx = str(body.get("tx_hash") or "").strip()
    payer = str(body.get("payer") or (auth or {}).get("from") or "").strip()
    pay_to = str(body.get("pay_to") or (auth or {}).get("to") or "").strip()
    amount = body.get("amount_usd")
    if amount in (None, "") and auth and auth.get("value") is not None:
        amount = int(auth["value"]) / 1e6
    if not (auth or buyer.TXH.match(tx) or (buyer.ADDR.match(payer) and buyer.ADDR.match(pay_to))):
        return {"verdict": "BAD_INPUT", "reasons": ["send payment_header (the X-PAYMENT you sent), or tx_hash, or payer + pay_to + amount_usd"]}
    ev, verdict, action, reasons = {}, None, None, []
    try:
        # 1. the authorization itself (strongest evidence)
        if auth and auth.get("nonce") and buyer.ADDR.match(str(auth.get("from") or "")):
            used = _nonce_state(auth["from"], auth["nonce"])
            vb = int(auth.get("validBefore") or 0)
            ev["authorization"] = {"from": auth["from"], "to": auth.get("to"), "value_usd": int(auth.get("value") or 0) / 1e6,
                                   "nonce": auth["nonce"], "valid_before": vb, "expired": bool(vb and now >= vb), "used_on_chain": used}
            if used:
                txh, kind = _find_auth_tx(auth["from"], auth["nonce"])
                ev["authorization"]["state_tx"] = txh
                if kind == "canceled":
                    verdict, action = "NOT_SETTLED", "The payer canceled this authorization on-chain; no money moved under it. Pay again only if you still want the item."
                else:
                    tx = tx or txh or ""
                    verdict = "SETTLED"
            elif vb and now >= vb:
                verdict, action = "NOT_SETTLED", "This authorization expired unused, so it can never settle. Safe to pay again ONCE (new authorization)."
            else:
                verdict = "STILL_UNCERTAIN"
                wait = vb - now if vb else None
                action = (f"Do NOT sign a new payment yet: a facilitator can still settle this one for about {wait}s (until validBefore). "
                          "Ask the seller to retry the same request with the SAME X-PAYMENT, or wait for expiry, then call rescue again.") if wait else \
                    "Do NOT sign a new payment: this authorization has no expiry we can read."
                reasons.append("authorization unused and still valid")
        # 2. tx hash path
        if tx and buyer.TXH.match(tx):
            pv = buyer.pay_verify({"tx_hash": tx, "expected_pay_to": pay_to or None, "expected_amount_usd": amount})
            ev["transaction"] = {k: pv.get(k) for k in ("verdict", "payment", "confirmations", "settled_at", "tx_status")}
            if pv["verdict"] == "SETTLED":
                verdict = "SETTLED"
            elif pv["verdict"] == "PENDING" and verdict != "SETTLED":
                verdict, action = "STILL_UNCERTAIN", "The transaction is broadcast but not final. Wait for it; do not pay again."
            elif pv["verdict"] in ("FAILED", "NO_USDC_TRANSFER") and verdict is None:
                verdict, action = "NOT_SETTLED", "The transaction moved no USDC (reverted or no transfer). Safe to pay again once."
            elif pv["verdict"] == "NOT_FOUND" and verdict is None:
                verdict, action = "STILL_UNCERTAIN", "No such transaction on Base yet. If you have the X-PAYMENT you sent, call rescue with payment_header for a definite answer."
            elif pv["verdict"] == "MISMATCH":
                reasons += pv.get("reasons") or []
                verdict = verdict or "SETTLED_WITH_MISMATCH"
        # 3. duplicate scan (same payer -> payee -> amount)
        if buyer.ADDR.match(payer) and buyer.ADDR.match(pay_to):
            hits = guard._onchain_dupes(payer, pay_to, amount if amount not in (None, "") else None,
                                        hours=max(1, min(168, int(body.get("window_hours") or 24))))
            ev["matching_payments_on_chain"] = hits[:10]
            if verdict is None:
                verdict = "SETTLED" if hits else "NOT_FOUND_ON_CHAIN"
                if not hits:
                    action = "No matching USDC payment from this payer to this payee in the window. If you never signed one, it is safe to pay; if you did, send payment_header."
            if len(hits) > 1:
                reasons.append(f"DUPLICATE: {len(hits)} matching payments payer -> payee in the window")
                ev["duplicate"] = True
    except wallet.WalletError as e:
        return {"verdict": "UNAVAILABLE", "reasons": [str(e)], "safe_next_action": "Do not pay again until this check can run."}
    if verdict == "SETTLED" and not action:
        action = "Paid. Do NOT pay again. If the seller did not deliver, ask it to resend for this payment (cite the tx), then file finance/refund-request with this record."
    if ev.get("duplicate"):
        action = (action or "") + " You appear to have paid more than once: use this record to ask the seller for a refund of the extra payment(s)."
    rec = {"schema": "omenz.settlement-rescue.v0", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "verdict": verdict,
           "payer": payer or None, "pay_to": pay_to or None, "amount_usd": float(amount) if amount not in (None, "") else None,
           "tx_hash": tx or None, "nonce": (auth or {}).get("nonce"), "duplicate": bool(ev.get("duplicate"))}
    return {"version": VERSION, "verdict": verdict, "safe_next_action": action, "reasons": reasons, "evidence": ev,
            "record": rec, "signed": _sign(rec), "verify": "Ed25519; public key at GET /api/tollbooth/v1/passport/key"}
