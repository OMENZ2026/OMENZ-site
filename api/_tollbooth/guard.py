"""OMENZ Transaction Guard: one call before money moves. "PAY $X TO Y FOR Z" -> GO / CAUTION / STOP with every check.

Big Bro + founder 2026-11-18 ("bigger bag per transaction"): the price of a financial control does not have to equal
the price of a JSON lookup. Guard is the value-protection tier on top of the nickel machines:
  x402: $0.05 flat per guarded purchase; credits: max($0.01, 10 bps x protected value), capped at $5.

Checks (assembled from primitives OMENZ already runs):
  budget authorized        Shared Budget draw (if budget_id)        -> checkout.open_
  counterparty checked     Authorize (live 402, payTo, known seller, fair price) + Seller Track Record
  duplicate payment        same payer -> same payee, same amount: in OMENZ guard records (window) AND on-chain USDC (Base)
  quoted price unchanged   live 402 price vs the price the agent was quoted
  settlement economics     live Base settlement cost vs the payment
  expected delivery        snapshot of the seller's advertised output (field list + hash) for checkout/close to hold them to
After paying: checkout/close (SETTLED -> DELIVERY VERIFIED -> signed RECEIPT -> budget reconciled -> seller record).
OMENZ never holds, moves or signs for the buyer's money. Deterministic, no AI calls.
"""
import hashlib
import json
import time

import buyer
import checkout
import gas
import wallet
from locker import LockerError, _kv

VERSION = "0.1.0"
DUP_WINDOW_S = 24 * 3600
FLAT_X402_USD = 0.05
BPS, MIN_FEE, MAX_FEE = 10, 0.01, 5.0


def fee(protected_usd):
    """Credits pricing: max($0.01, 10 basis points of the protected value), capped at $5."""
    return round(min(MAX_FEE, max(MIN_FEE, float(protected_usd or 0) * BPS / 10000)), 6)


def _fp(payer, pay_to, amount, purpose):
    raw = f"{(payer or '').lower()}|{(pay_to or '').lower()}|{round(float(amount or 0), 6)}|{(purpose or '').strip().lower()[:200]}"
    return "gd_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _onchain_dupes(payer, pay_to, amount, hours=24):
    """USDC transfers payer -> pay_to on Base in the last `hours` with the same amount."""
    head = int(wallet._rpc("eth_blockNumber", []), 16)
    start = head - int(hours * 3600 / wallet.BLOCK_S)
    hits, frm = [], start
    while frm <= head:
        to = min(head, frm + wallet.CHUNK - 1)
        logs = wallet._rpc("eth_getLogs", [{"address": wallet.USDC, "topics": [wallet.TRANSFER, wallet._topic(payer.lower()), wallet._topic(pay_to.lower())],
                                            "fromBlock": hex(frm), "toBlock": hex(to)}])
        for lg in logs:
            amt = int(lg["data"], 16) / 1e6
            if amount is None or abs(amt - float(amount)) <= 1e-6:
                hits.append({"tx_hash": lg["transactionHash"], "amount_usd": amt, "block": int(lg["blockNumber"], 16)})
        frm = to + 1
    return hits


def guard(body, budget_key=None):
    body = body if isinstance(body, dict) else {}
    payer = str(body.get("payer") or "").strip()
    if payer and not buyer.ADDR.match(payer):
        return {"decision": "STOP", "reasons": ["payer must be your 0x wallet address (used for the duplicate-payment check)"]}
    # 1-2. budget + counterparty (+ cheapest working seller when only q is given)
    op = checkout.open_(body, budget_key)
    if not op.get("checkout_id") and op.get("decision") == "STOP" and not op.get("pay"):
        return {"decision": "STOP", "reasons": op.get("reasons"), "checks": {}}
    pay = op.get("pay") or {}
    amount, pay_to, url = pay.get("amount_usd"), pay.get("pay_to"), pay.get("url")
    checks, caution, stop = {}, [], []
    base = {"GO": "pass", "REVIEW": "caution", "STOP": "fail"}[op["decision"]]
    checks["counterparty"] = {"result": base, "authorize_reasons": op.get("reasons"), "seller_record": op.get("seller_record")}
    checks["budget"] = {"result": "pass" if (op.get("budget") or {}).get("decision") == "ALLOW" else
                        "not_used" if not body.get("budget_id") else "fail", **({"budget": op["budget"]} if op.get("budget") else {})}
    if op["decision"] == "STOP":
        stop += op.get("reasons") or []
    elif op["decision"] == "REVIEW":
        caution += op.get("reasons") or []
    # 3. duplicate payment
    dup = {"result": "not_checked", "why": "send payer (your wallet address) to check for duplicate payments"}
    if payer and pay_to and amount is not None:
        fp = _fp(payer, pay_to, amount, body.get("purpose"))
        try:
            prev = _kv("GET", fp)
        except LockerError:
            prev = None
        recent_guard = prev and time.time() - prev.get("at", 0) < DUP_WINDOW_S
        try:
            chain = _onchain_dupes(payer, pay_to, amount, hours=max(1, min(168, int(body.get("dup_window_hours") or 24))))
        except wallet.WalletError as e:
            chain, dup["chain_error"] = [], str(e)
        dup = {"result": "caution" if (recent_guard or chain) else "pass",
               "guarded_before": {"at": prev["at"], "checkout_id": prev.get("checkout_id")} if recent_guard else None,
               "same_payment_on_chain_24h": chain[:5]}
        if recent_guard or chain:
            caution.append(f"possible duplicate: you already {'guarded' if recent_guard else 'paid'} {amount} USDC to this payee"
                           f"{' (' + str(len(chain)) + ' matching on-chain payment(s) in 24h)' if chain else ''}")
        try:
            _kv("PUT", fp, {"at": int(time.time()), "checkout_id": op.get("checkout_id")})
        except LockerError:
            pass
    checks["duplicate_payment"] = dup
    # 4. quoted price unchanged
    q = body.get("quoted_price_usd")
    if q not in (None, "") and amount is not None:
        drift = round(float(amount) - float(q), 6)
        checks["quoted_price"] = {"result": "pass" if abs(drift) <= 1e-9 else "caution" if drift < 0 else "fail",
                                  "quoted_usd": float(q), "live_usd": amount, "drift_usd": drift}
        if drift > 1e-9:
            stop.append(f"live price {amount} is above the {q} you were quoted")
    else:
        checks["quoted_price"] = {"result": "not_checked", "live_usd": amount, "why": "send quoted_price_usd to catch price changes"}
    # 5. settlement economics
    try:
        sc = gas.settlement_cost(amount) if amount else None
        if sc and sc.get("payment"):
            pv = sc["payment"]
            checks["settlement_economics"] = {"result": "pass" if pv["verdict"] == "SETTLE" else "info", **{k: pv[k] for k in ("verdict", "overhead_pct", "settlement_cost_usd")}}
        else:
            checks["settlement_economics"] = {"result": "not_checked"}
    except Exception:
        checks["settlement_economics"] = {"result": "not_checked"}
    # 6. expected delivery snapshot
    try:
        ex, schema, why = buyer._advertised(url, pay.get("method") or "GET") if url else (None, None, "no url")
        contract = schema or ex
        if contract is not None:
            fields = sorted(contract.keys()) if isinstance(contract, dict) else []
            checks["expected_delivery"] = {"result": "recorded", "basis": "schema" if schema else "example", "fields": fields[:40],
                                           "contract_sha256": hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()}
        else:
            checks["expected_delivery"] = {"result": "none_advertised", "why": why or "seller advertises no output; send your own schema at checkout/close"}
    except Exception:
        checks["expected_delivery"] = {"result": "not_checked"}
    decision = "STOP" if stop else "CAUTION" if caution else "GO"
    return {"version": VERSION, "decision": decision, "pay": pay, "protected_value_usd": amount,
            "reasons": stop + caution or ["all checks passed"], "checks": checks,
            "checkout_id": op.get("checkout_id"), "authorization_token": op.get("authorization_token"), "expires_in_s": op.get("expires_in_s"),
            "next": {"GO": "Pay now, then POST checkout/close with checkout_id + tx hash + the response: settled -> delivery verified -> signed receipt -> reconciled.",
                     "CAUTION": "Look at the reasons (duplicate? review?) before paying; if you pay, still close with checkout/close.",
                     "STOP": "Do not pay."}[decision],
            "pricing": {"x402": f"${FLAT_X402_USD} flat", "credits": f"max(${MIN_FEE}, {BPS} bps of protected value), cap ${MAX_FEE}"}}
