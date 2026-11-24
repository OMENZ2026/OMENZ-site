"""Pay Ready: can THIS wallet pay THIS x402 seller right now? (2026-11-24, Big Bro 11-23 list: "wallet capability checks,
balance/readiness checks, network/asset compatibility").

Before an agent signs, it learns whether the payment can succeed: does the 402 offer an option this wallet can use (Base),
does the wallet hold enough of that exact asset, does the asset support gasless EIP-3009 transfers (what x402 'exact'
needs), is the wallet a plain account or a smart-contract wallet (some facilitators can't verify contract signatures),
is the payee on the OFAC list. READY / NOT_READY / CAUTION with the fix. Public chain data, never signs, never pays.
"""
import time
import urllib.error
import urllib.parse
import urllib.request

import chain_tools as ct
import pay_doctor
import sanctions

VERSION = "0.1.0"
BASE_NETS = {"eip155:8453", "base"}
EIP3009_SIG = "authorizationState(address,bytes32)"


def _code(addr):
    return ct._rpc(ct.BASE_RPCS, "eth_getCode", [addr, "latest"])


def check(d):
    d = d or {}
    out = {"service": "OMENZ Pay Ready", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "signed_anything": False, "paid_anything": False}
    w = str(d.get("wallet") or "").strip()
    if not ct.ADDR.match(w):
        return {**out, "error": "wallet must be a 0x address (40 hex chars)"}
    pr = pay_doctor._dec(d.get("payment_required"))
    if pr is None and d.get("url"):
        u = urllib.parse.urlparse(str(d["url"]))
        import link_check
        if u.scheme != "https" or not u.hostname or link_check._public(u.hostname) is not True:
            return {**out, "error": "url must be a public https address"}
        try:
            urllib.request.urlopen(urllib.request.Request(str(d["url"]), method=str(d.get("method") or "GET").upper(),
                                                          headers={"User-Agent": "OMENZ Pay Ready"}), timeout=10)
            return {**out, "error": "that URL didn't answer 402: nothing to pay"}
        except urllib.error.HTTPError as e:
            pr = pay_doctor._dec(e.headers.get("payment-required")) if e.code == 402 else None
            if pr is None:
                return {**out, "error": f"that URL answered {e.code} without a PAYMENT-REQUIRED header"}
        except Exception as e:
            return {**out, "error": f"couldn't reach the URL ({type(e).__name__})"}
    if not isinstance(pr, dict):
        return {**out, "error": "send url (a public https x402 endpoint) or payment_required (its PAYMENT-REQUIRED header or JSON), plus wallet"}
    accepts = pr.get("accepts") or []
    base_opts = [a for a in accepts if str(a.get("network")) in BASE_NETS]
    if not accepts:
        return {**out, "verdict": "NOT_READY", "reasons": ["the 402 lists no payment options"], "fix": "nothing to do on your side: the seller's x402 setup is broken"}
    if not base_opts:
        return {**out, "verdict": "NOT_READY", "reasons": ["no option on Base; offered: " + ", ".join(sorted({str(a.get('network')) for a in accepts}))],
                "fix": "this check reads Base only; use a wallet on one of the offered networks"}
    reasons, cautions, checks = [], [], []
    try:
        code = _code(w)
    except ct.ChainError as e:
        return {**out, "error": str(e)}
    kind = "plain account (EOA)" if code in ("0x", "0x0", None) else ("EIP-7702 delegated account" if str(code).startswith("0xef0100") else "smart-contract wallet")
    checks.append(f"wallet is a {kind}")
    if kind == "smart-contract wallet":
        cautions.append("smart-contract wallet: the facilitator must verify an EIP-1271/6492 signature; some x402 facilitators don't. A plain EOA always works")
    best = None
    for a in base_opts:
        asset = str(a.get("asset") or "")
        need = int(a.get("amount") or a.get("maxAmountRequired") or 0)
        sym, dec = ct.KNOWN_TOKENS.get(asset.lower(), (None, None))
        row = {"scheme": a.get("scheme"), "asset": asset, "symbol": sym, "amount_atomic": str(need)}
        try:
            bal = int(ct._call(ct.BASE_RPCS, asset, "balanceOf(address)", ct._word(w)), 16)
            if dec is None:
                dec = int(ct._rpc(ct.BASE_RPCS, "eth_call", [{"to": asset, "data": "0x313ce567"}, "latest"]), 16)
        except Exception:
            row["problem"] = "couldn't read the asset balance (is it an ERC-20 on Base?)"
            continue
        row.update({"balance_atomic": str(bal), "need_human": need / 10 ** dec, "balance_human": bal / 10 ** dec, "enough": bal >= need})
        if a.get("scheme") == "exact":
            try:
                ct._call(ct.BASE_RPCS, asset, EIP3009_SIG, ct._word(w) + "0" * 64)
                row["gasless_eip3009"] = True
            except Exception:
                row["gasless_eip3009"] = False
        payto = str(a.get("payTo") or "")
        if ct.ADDR.match(payto):
            sc = sanctions.check(payto)
            row["payee_ofac_listed"] = sc["listed"]
        if best is None or (row.get("enough") and not best.get("enough")):
            best = row
    if best is None:
        return {**out, "verdict": "NOT_READY", "reasons": ["couldn't read any Base asset the seller asks for"], "options": base_opts}
    if best.get("payee_ofac_listed"):
        reasons.append("the payee address is on the OFAC SDN list: do not pay")
    if not best.get("enough"):
        reasons.append(f"balance {best['balance_human']:g} {best.get('symbol') or 'tokens'} < price {best['need_human']:g}")
    if best.get("gasless_eip3009") is False:
        reasons.append("the asset has no EIP-3009 transferWithAuthorization, which x402 'exact' needs")
    verdict = "NOT_READY" if reasons else ("CAUTION" if cautions else "READY")
    fix = {"READY": "sign and pay", "CAUTION": "likely fine; if the payment is refused, run POST /v1/pay/doctor with the error",
           "NOT_READY": "; ".join(["top up the wallet with the asset on Base" if not best.get("enough") else "",
                                   "choose another seller (POST /v1/market/find)" if best.get("payee_ofac_listed") or best.get("gasless_eip3009") is False else ""]).strip("; ")}[verdict]
    return {**out, "verdict": verdict, "wallet": w, "reasons": reasons, "cautions": cautions, "checked_ok": checks, "best_option": best, "fix": fix,
            "limits": "Reads Base mainnet only; can't see pending transactions or the facilitator's own policy."}
