"""Payment Doctor: why was my x402 payment refused, whose fault is it, and how do I fix it? (2026-11-24)

Built from OMENZ's own incident: 50 of 93 paid attempts refused in a week, 45 by the facilitator because the seller's
resource description was > 500 chars. Buyers can't tell a seller bug from their own mistake. Deterministic: decodes the
402 the buyer got (PAYMENT-REQUIRED), the payment it sent (PAYMENT-SIGNATURE / X-PAYMENT, public data: no keys), and any
error text, then checks every known refusal cause. Nothing is stored; nothing is paid.
"""
import base64
import json
import time
import urllib.request

VERSION = "0.1.0"


def _dec(v):
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        return v
    s = str(v).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        return json.loads(base64.b64decode(s + "=" * (-len(s) % 4)))
    except Exception:
        return "undecodable"


ERRORS = [  # (substring in error text, cause, owner, fix)
    ("requires 'scheme'", "the facilitator rejected the payment format. With Coinbase CDP this happens when the seller's resource description is over 500 characters",
     "seller", "seller: shorten the route description in its x402 payment requirements to under 500 characters"),
    ("insufficient_funds", "the paying wallet doesn't hold enough of the asset (or gas-less transfer can't cover it)", "buyer", "fund the wallet with the asset and network shown in accepts"),
    ("invalid_signature", "the payment signature doesn't verify for this wallet and payload", "buyer", "re-sign with the same key that owns 'from', for exactly the accepted requirement"),
    ("nonce", "the authorization nonce was already used (replay) or is malformed", "buyer", "sign a fresh authorization with a new random nonce"),
    ("expired", "the authorization's validBefore time has passed", "buyer", "sign again and send it promptly (validBefore in the future)"),
    ("valid_before", "the authorization's time window is invalid", "buyer", "set validAfter in the past and validBefore a few minutes ahead"),
    ("unsupported", "the network or scheme isn't supported by the seller's facilitator", "buyer", "pay with one of the networks/schemes listed in accepts"),
    ("x402 v1 x-payment is not accepted", "you sent an x402 v1 X-PAYMENT header to an x402 v2 server", "buyer", "use an x402 v2 client: send PAYMENT-SIGNATURE built from the PAYMENT-REQUIRED header"),
    ("amount", "the amount signed doesn't match the price required", "buyer", "sign exactly the 'amount' from the accepted requirement (atomic units)"),
]


def diagnose(d):
    out = {"service": "OMENZ Payment Doctor", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "stored": False, "paid_anything": False}
    d = d or {}
    pr, pay, err = _dec(d.get("payment_required")), _dec(d.get("payment")), str(d.get("error") or "")
    if pr is None and d.get("url"):
        from urllib.parse import urlparse
        import link_check
        u = urlparse(str(d["url"]))
        if u.scheme != "https" or not u.hostname or link_check._public(u.hostname) is not True:
            return {**out, "error": "url must be a public https address"}
        try:
            r = urllib.request.urlopen(urllib.request.Request(str(d["url"]), method=str(d.get("method") or "GET").upper(),
                                                              headers={"User-Agent": "OMENZ Payment Doctor"}), timeout=10)
            return {**out, "error": f"that URL answered {r.status}, not 402: nothing to diagnose"}
        except urllib.error.HTTPError as e:
            pr = _dec(e.headers.get("payment-required")) if e.code == 402 else None
            if pr is None:
                return {**out, "error": f"that URL answered {e.code} without a PAYMENT-REQUIRED header"}
        except Exception as e:
            return {**out, "error": f"couldn't reach the URL ({type(e).__name__})"}
    if pr is None and pay is None and not err:
        return {**out, "error": "send at least one of: payment_required (the 402's PAYMENT-REQUIRED header), payment (the PAYMENT-SIGNATURE you sent), error (the error text), or url"}
    if pr == "undecodable" or pay == "undecodable":
        return {**out, "error": "payment_required / payment must be the base64 header value or its JSON"}
    causes, ok = [], []

    def cause(c, owner, fix):
        causes.append({"cause": c, "whose_side": owner, "fix": fix})

    accepts = (pr or {}).get("accepts") or []
    if pr:
        res = pr.get("resource") or {}
        desc = res.get("description") if isinstance(res, dict) else None
        if desc and len(desc) > 500:
            cause(f"the seller's resource description is {len(desc)} characters; the Coinbase CDP facilitator rejects payment payloads when it is over 500",
                  "seller", "seller: shorten the description in its payment requirements to under 500 characters (keep the long text in its catalog)")
        if not accepts:
            cause("the 402 lists no payment options (accepts is empty)", "seller", "seller: fix its x402 configuration")
        else:
            ok.append(f"402 offers {len(accepts)} payment option(s): " + ", ".join(f"{a.get('scheme')}/{a.get('network')}" for a in accepts[:4]))
        if pr.get("x402Version") == 2 and isinstance(pay, dict) and pay.get("x402Version") == 1:
            cause("you paid with x402 v1 but the seller speaks x402 v2", "buyer", "upgrade the client to x402 v2 (PAYMENT-SIGNATURE header)")
    if isinstance(pay, dict):
        acc = pay.get("accepted") or {}
        au = ((pay.get("payload") or {}).get("authorization")) or {}
        if not (acc.get("scheme") or pay.get("scheme")):
            cause("the payment has no 'scheme' field", "buyer", "use an x402 v2 client that copies the chosen requirement into 'accepted'")
        if accepts and acc:
            same = [a for a in accepts if a.get("network") == acc.get("network") and str(a.get("payTo", "")).lower() == str(acc.get("payTo", "")).lower()
                    and str(a.get("asset", "")).lower() == str(acc.get("asset", "")).lower()]
            if not same:
                cause("the payment's 'accepted' (network / payTo / asset) doesn't match any option in the 402", "buyer",
                      "copy one requirement from the 402's accepts exactly; re-fetch the 402 if the seller changed it")
            elif str(same[0].get("amount")) != str(acc.get("amount")):
                cause(f"amount signed {acc.get('amount')} != amount required {same[0].get('amount')} (atomic units)", "buyer", "sign exactly the required amount")
            else:
                ok.append("payment matches a 402 option (network, payTo, asset, amount)")
        if au:
            now = int(time.time())
            vb, va = int(au.get("validBefore") or 0), int(au.get("validAfter") or 0)
            if vb and vb < now:
                cause(f"authorization expired {now - vb} s ago (validBefore)", "buyer", "sign again and send within the window")
            if va and va > now + 5:
                cause("authorization isn't valid yet (validAfter is in the future)", "buyer", "set validAfter to now or earlier")
            if acc and au.get("to") and str(au.get("to")).lower() != str(acc.get("payTo", "")).lower():
                cause("authorization 'to' differs from the requirement's payTo", "buyer", "sign the transfer to the payTo in the 402")
            if acc and au.get("value") and str(au.get("value")) != str(acc.get("amount")):
                cause(f"authorization value {au.get('value')} != accepted amount {acc.get('amount')}", "buyer", "sign value = amount")
    el = err.lower()
    for sub, c, owner, fix in ERRORS:
        if sub in el and not any(c == x["cause"] for x in causes):
            if sub == "requires 'scheme'" and any("description is" in x["cause"] for x in causes):
                continue
            cause(c, owner, fix)
    verdict = "CAUSE_FOUND" if causes else ("NO_PROBLEM_FOUND" if (pr or pay) else "UNKNOWN_ERROR")
    sides = sorted({c["whose_side"] for c in causes})
    return {**out, "verdict": verdict, "whose_side": sides[0] if len(sides) == 1 else (sides or None), "causes": causes, "checked_ok": ok,
            "next": {"CAUSE_FOUND": "apply the fix for each cause, then retry once", "NO_PROBLEM_FOUND": "format looks right: check the wallet balance and retry; if it fails again send the facilitator error text here",
                     "UNKNOWN_ERROR": "send the 402 header and the payment you sent for a full check"}[verdict],
            "limits": "Checks format, matching, time window and known facilitator messages; it can't see the wallet's private state or the seller's server internals."}
