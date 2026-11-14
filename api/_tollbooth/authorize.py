"""OMENZ Authorize: the authorization step for agent payments. One call before every x402 payment -> APPROVE / REVIEW /
DECLINE plus a signed, short-lived authorization code. FIND THE ETHER (founder 2026-11-14): be the network that earns on every
agent transaction the way card networks earn on authorization, without ever holding anyone's money.

Checks, in one round trip (all unpaid probes; we never pay the target):
  1. live quote + transaction preflight (endpoint up, price within max, network, stablecoin, expected payTo)
  2. payee check (is the payTo a known x402 seller? shared/platform wallet? unknown?)
  3. fair price (percentile vs comparable x402 endpoints when the endpoint is listed)
  4. owner spend policy (Spend Gate) when a policy is sent
  5. Permission Passport when a token is sent
Signed authorization (Ed25519, OMENZ key at /v1/passport/key): auth_id, url, payTo, amount, decision, expires (5 min), so
sellers, auditors and ledgers can verify the payment was authorized.
"""
import secrets
import time

import contracts
import market
import passport
import spend_gate
import x402_probe

VERSION = "0.1.0"
TTL = 300


def authorize(req):
    req = req or {}
    url, method = req.get("url"), (req.get("method") or "GET").upper()
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_targets": False}
    if not isinstance(url, str) or not url:
        return {**out, "decision": "ERROR", "error": "url (the x402 endpoint you're about to pay) is required"}
    try:
        max_price = float(req["max_price_usd"]) if req.get("max_price_usd") is not None else None
    except (TypeError, ValueError):
        return {**out, "decision": "ERROR", "error": "max_price_usd must be a number"}
    decline, review, passed, checks = [], [], [], {}

    pf = x402_probe.preflight(url, method, max_price, req.get("expected_pay_to"), req.get("networks"), req.get("listed_price_usd"))
    checks["preflight"] = {k: pf.get(k) for k in ("verdict", "reasons", "warnings")}
    chosen = pf.get("chosen") or {}
    if pf.get("verdict") != "GO":
        decline += [f"preflight: {r}" for r in pf.get("reasons", [])]
    else:
        passed.append("preflight")
        review += [f"preflight: {w}" for w in pf.get("warnings", []) if "drift" in w or "slow" in w]
    amount = chosen.get("price_usd")
    pay_to = (chosen.get("pay_to") or "").lower()

    if pay_to:
        try:
            pc = market.payee(pay_to)
            checks["payee"] = {k: pc.get(k) for k in ("verdict", "x402_endpoints")}
            if pc.get("verdict") == "KNOWN_SELLER":
                passed.append("payee known")
            elif pc.get("verdict") == "SHARED_ADDRESS":
                passed.append("payee shared platform wallet")
            else:
                review.append("payee: address is not the payout of any listed x402 service")
        except Exception:
            checks["payee"] = {"verdict": "UNAVAILABLE"}
            review.append("payee check unavailable")

    if amount is not None:
        try:
            r, _ = market._listing(url)
            if r:
                pi = market.price_index(None, amount, url)
                checks["price"] = {k: pi.get(k) for k in ("comparables", "median", "p75", "percentile", "verdict")}
                if pi.get("verdict") == "HIGH":
                    review.append(f"price ${amount:g} is far above comparable endpoints (median ${pi.get('median')})")
                elif pi.get("verdict"):
                    passed.append("price " + pi["verdict"].lower())
        except Exception:
            checks["price"] = {"verdict": "UNAVAILABLE"}

    if isinstance(req.get("policy"), dict) and amount is not None:
        sg = spend_gate.check(req["policy"], {**(req.get("spend") or {}), "amount_usd": amount, "recipient": pay_to,
                                               "network": chosen.get("network")})
        checks["spend_gate"] = {k: sg.get(k) for k in ("decision", "deny_reasons", "escalate_reasons")}
        if sg.get("decision") == "DENY":
            decline += [f"spend policy: {r}" for r in sg["deny_reasons"]]
        elif sg.get("decision") == "ESCALATE":
            review += [f"spend policy: {r}" for r in sg["escalate_reasons"]]
        elif sg.get("decision") == "ALLOW":
            passed.append("spend policy")

    if req.get("passport_token"):
        pp = passport.check(req["passport_token"], {"tool": req.get("tool") or "", "url": url, "amount_usd": amount or 0,
                                                    "spent_so_far_usd": (req.get("spend") or {}).get("spent_today_usd", 0)})
        checks["passport"] = {k: pp.get(k) for k in ("decision", "reasons")}
        if pp.get("decision") != "ALLOW":
            decline += [f"passport: {r}" for r in pp.get("reasons", [])]
        else:
            passed.append("passport")

    decision = "DECLINE" if decline else "REVIEW" if review else "APPROVE"
    now = int(time.time())
    auth = {"schema": "omenz.authorization.v0", "auth_id": "az_" + secrets.token_hex(10), "decision": decision, "url": url,
            "method": method, "pay_to": pay_to or None, "amount_usd": amount, "network": chosen.get("network"),
            "issued": now, "expires": now + TTL, "issuer": "omenz.org"}
    return {**out, "decision": decision, "decline_reasons": decline, "review_reasons": review, "passed": passed, "checks": checks,
            "authorization": auth, "authorization_token": contracts._sign(auth), "expires_in_s": TTL,
            "next_action": {"APPROVE": "pay now (the authorization expires in 5 minutes)",
                            "REVIEW": "a person or a stricter policy should look before paying",
                            "DECLINE": "don't pay; fix the listed reasons"}[decision]}
