"""OMENZ Send Check: one call before an agent sends USDC or ETH on Base (2026-11-21).

Evidence: the fastest-growing x402 service this week was agents SENDING money (keyring send-native/send-token,
+2,492 paying wallets in 7 days, $0.05/send). A send is irreversible; the costly failure is the wrong recipient.
Checks, all read-only public chain data:
  sanctions      recipient on OFAC SDN list                      -> STOP
  contract       recipient is a contract (token/contract address) -> CAUTION (STOP if it's the token itself)
  fresh          recipient has never sent a transaction           -> CAUTION
  poisoning      recipient looks like one of your recent payees (same first+last 4 hex) but isn't -> STOP
  balance        sender can't cover amount (+ ETH for gas)        -> STOP
Verdict SEND / CAUTION / STOP with reasons. Never signs, never moves money.
"""
import time

import sanctions
import wallet

VERSION = "0.1.0"
USDC = wallet.USDC.lower()


def _look(a):
    a = a.lower()
    return (a[2:6], a[-4:])


def check(body):
    body = body if isinstance(body, dict) else {}
    frm, to = str(body.get("from") or "").strip(), str(body.get("to") or "").strip()
    asset = str(body.get("asset") or "USDC").upper()
    out = {"service": "OMENZ Send Check", "version": VERSION, "network": "base", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "never_moves_money": True}
    try:
        to = wallet._check(to)
        frm = wallet._check(frm) if frm else None
    except Exception:
        return {**out, "verdict": "BAD_INPUT", "reasons": ["to (and optional from) must be 0x Base addresses"]}
    try:
        amount = float(body["amount"]) if body.get("amount") is not None else None
    except (TypeError, ValueError):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["amount must be a number (in USDC or ETH units)"]}
    if asset not in ("USDC", "ETH"):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["asset must be USDC or ETH"]}
    stop, caution, passed, checks = [], [], [], {}

    sc = sanctions.check(to)
    checks["sanctions"] = sc
    (stop.append(f"recipient is on the OFAC SDN list ({sc['entity']})") if sc["listed"] else passed.append("not on OFAC SDN list"))

    try:
        code = wallet._rpc("eth_getCode", [to, "latest"])
        nonce = int(wallet._rpc("eth_getTransactionCount", [to, "latest"]), 16)
    except Exception as e:
        return {**out, "verdict": "UNAVAILABLE", "reasons": [f"Base RPC unavailable ({type(e).__name__})"]}
    is_contract = bool(code and code not in ("0x", "0x0"))
    checks["recipient"] = {"is_contract": is_contract, "tx_count": nonce}
    if to.lower() == USDC:
        stop.append("recipient is the USDC token contract itself: tokens sent there are lost")
    elif is_contract:
        caution.append("recipient is a contract, not a wallet: make sure it is meant to receive funds (smart wallets and payment contracts are; token contracts are not)")
    elif nonce == 0:
        caution.append("recipient address has never sent a transaction (new or unused): double-check you have the right address")
    else:
        passed.append(f"recipient is an active wallet ({nonce} txs)")

    if frm:
        try:
            logs, _, _ = wallet._outgoing(frm, float(body.get("history_days") or 30))
            payees = {("0x" + lg["topics"][2][-40:]).lower() for lg in logs}
            checks["history"] = {"payees_checked": len(payees), "window_days": float(body.get("history_days") or 30)}
            if to.lower() in payees:
                passed.append("you have paid this exact address before")
            else:
                twins = [p for p in payees if _look(p) == _look(to)]
                if twins:
                    stop.append(f"ADDRESS POISONING RISK: recipient looks like {twins[0]} (a payee you used before: same first and last 4 characters) but is a different address")
        except Exception as e:
            checks["history"] = {"error": str(e)[:120]}
        try:
            b = wallet.balance(frm)
            checks["sender_balance"] = {"usdc": b["usdc"], "eth": b["eth"]}
            if amount is not None:
                have = b["usdc"] if asset == "USDC" else b["eth"]
                if amount > have:
                    stop.append(f"sender has {have:g} {asset}, less than the {amount:g} to send")
                else:
                    passed.append("balance covers the amount")
            if b["eth"] < 0.00001 and not body.get("gasless"):
                caution.append("sender has almost no ETH for gas (fine only if a relayer/facilitator pays gas, e.g. x402)")
        except Exception:
            checks["sender_balance"] = {"error": "unavailable"}
    verdict = "STOP" if stop else "CAUTION" if caution else "SEND"
    return {**out, "verdict": verdict, "to": to, "from": frm, "asset": asset, "amount": amount,
            "stop_reasons": stop, "caution_reasons": caution, "passed": passed, "checks": checks,
            "next": {"SEND": "ok to send", "CAUTION": "confirm the flagged points, then send",
                     "STOP": "do not send; fix the reasons above"}[verdict]}
