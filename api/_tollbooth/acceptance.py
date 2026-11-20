"""Seller Payment-Acceptance Check (challenge-first, founder handoff 11-20 sec 26).

OMENZ found on 2026-11-20 that its own x402 server refused real, funded buyers: x402 v2 servers match the buyer's
echoed requirements EXACTLY (price, timeout, extra, even the bazaar discovery text), so any buyer reusing an earlier 402
is rejected after the seller edits a route, and v1 clients are silently dropped. This probes a seller's route with a
throwaway, UNFUNDED key (no money can move) and reports whether the server turns away good money, with the fix.

Probes (max 5 requests to the seller's URL):
  0 unpaid            -> is there a valid 402? which x402 version?
  1 fresh payment     -> must reach the facilitator (expected answer: insufficient funds/balance)
  2 stale bazaar echo -> discovery text changed since the buyer read the 402
  3 stale timeout     -> a non-money field changed (maxTimeoutSeconds)
  4 v1 X-PAYMENT      -> old clients
"""
import base64
import json
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
UA = "OMENZ-acceptance-check/0.1 (+https://www.omenz.org; unfunded probe key, cannot pay)"
FACILITATOR_HINTS = ("insufficient", "balance", "funds", "facilitator", "verify failed", "invalid_exact_evm")
LOCAL_MISMATCH = ("no matching", "extension_echo_mismatch", "echo")


def _req(url, method, headers=None, body=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    data = body if body is not None else (b"{}" if method == "POST" else None)
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    t0 = time.time()
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=6)
        return r.status, dict(r.headers), r.read(4000), int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(4000), int((time.time() - t0) * 1000)


def _hdr(headers, name):
    for k, v in headers.items():
        if k.lower() == name:
            return v
    return None


def _b64json(v):
    try:
        return json.loads(base64.b64decode(v + "=" * (-len(v) % 4)))
    except Exception:
        return None


def _reason(status, headers, body):
    pr = _hdr(headers, "payment-required")
    d = _b64json(pr) if pr else None
    if d is None:
        try:
            d = json.loads(body or b"{}")
        except Exception:
            d = {}
    return str((d or {}).get("error") or (d or {}).get("invalidReason") or "")[:300]


def check(url, method="GET"):
    method = (method or "GET").upper()
    out = {"service": "OMENZ Seller Payment-Acceptance Check", "version": VERSION, "url": url, "method": method,
           "probe_key": "throwaway, unfunded: no payment can settle", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "probes": []}
    if not url.startswith("https://"):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["url must be https://"]}
    st, hd, body, ms = _req(url, method)
    pr = _hdr(hd, "payment-required")
    v2 = _b64json(pr) if pr else None
    v1 = None
    if not v2:
        try:
            j = json.loads(body or b"{}")
            v1 = j if j.get("x402Version") == 1 and j.get("accepts") else None
        except Exception:
            pass
    out["probes"].append({"probe": "unpaid", "status": st, "ms": ms, "x402_version": 2 if v2 else 1 if v1 else None})
    if st != 402 or not (v2 or v1):
        return {**out, "verdict": "NO_VALID_402", "reasons": [f"unpaid request returned HTTP {st} without x402 payment requirements"],
                "fix": "Return HTTP 402 with x402 requirements (v2: PAYMENT-REQUIRED header) on unpaid requests."}
    if v1 and not v2:
        return {**out, "verdict": "V1_SELLER", "x402_version": 1,
                "reasons": ["seller speaks x402 v1 only; v2 clients (PAYMENT-SIGNATURE) cannot pay it"],
                "fix": "Upgrade to an x402 v2 server, or accept both versions."}

    from eth_account import Account
    from x402 import x402ClientSync
    from x402.http.utils import decode_payment_required_header, encode_payment_signature_header
    from x402.mechanisms.evm.exact import ExactEvmScheme

    req = decode_payment_required_header(pr)
    nets = sorted({a.network for a in req.accepts})
    evm = [n for n in nets if n.startswith("eip155:")]
    if not evm:
        return {**out, "verdict": "UNSUPPORTED_NETWORK", "networks": nets, "reasons": ["only EVM (eip155) payment requirements are probed"]}
    client = x402ClientSync()
    for n in evm:
        client.register(n, ExactEvmScheme(Account.create()))

    def pay(p, label):
        try:
            payload = client.create_payment_payload(p, getattr(p, "resource", None), getattr(p, "extensions", None))
        except Exception as e:
            out["probes"].append({"probe": label, "skipped": f"could not build payload: {type(e).__name__}"})
            return None
        s, h, b, m = _req(url, method, {"PAYMENT-SIGNATURE": encode_payment_signature_header(payload)})
        why = _reason(s, h, b)
        low = why.lower()
        res = ("REACHED_FACILITATOR" if any(k in low for k in FACILITATOR_HINTS) and not any(k in low for k in LOCAL_MISMATCH)
               else "REFUSED_LOCALLY" if any(k in low for k in LOCAL_MISMATCH) else "OTHER")
        if s < 300:
            res = "ACCEPTED_WITHOUT_SETTLEMENT"
        out["probes"].append({"probe": label, "status": s, "ms": m, "result": res, "reason": why})
        return res

    fresh = pay(req, "fresh payment")
    stale_ext = None
    if req.extensions and "bazaar" in req.extensions:
        p = req.model_copy(deep=True)
        e = p.extensions["bazaar"]
        e = e if isinstance(e, dict) else e.model_dump()
        info = e.setdefault("info", {})
        info["output"] = {"type": "json", "example": {"stale": "example from an older 402"}}
        p.extensions["bazaar"] = e
        stale_ext = pay(p, "stale bazaar echo")
    p = req.model_copy(deep=True)
    for a in p.accepts:
        a.max_timeout_seconds = (a.max_timeout_seconds or 60) + 17
    stale_timeout = pay(p, "stale timeout field")
    v1_payload = base64.b64encode(json.dumps({"x402Version": 1, "scheme": "exact", "network": "base",
                                              "payload": {"signature": "0x" + "00" * 65, "authorization": {}}}).encode()).decode()
    s, h, b, m = _req(url, method, {"X-PAYMENT": v1_payload})
    v1_reason = _reason(s, h, b)
    v1_res = "IGNORED_SILENTLY" if s == 402 and v1_reason.lower() in ("", "payment required") else "ANSWERED"
    out["probes"].append({"probe": "v1 X-PAYMENT", "status": s, "ms": m, "result": v1_res, "reason": v1_reason})

    problems, fixes = [], []
    if fresh == "ACCEPTED_WITHOUT_SETTLEMENT":
        problems.append("SERVES_UNPAID: an unfunded payment got a success response")
        fixes.append("Verify (and settle) with the facilitator before running the handler.")
    elif fresh != "REACHED_FACILITATOR":
        problems.append("FRESH_PAYMENT_NOT_VERIFIED: a correctly built payment did not reach the facilitator")
        fixes.append("Check the facilitator config and that your 402 requirements are internally consistent.")
    if stale_ext == "REFUSED_LOCALLY":
        problems.append("REFUSES_STALE_DISCOVERY_ECHO: buyers who read an older 402 are refused after you edit description/examples")
        fixes.append("Treat the bazaar extension as discovery-only: drop it before validate_extensions (it never affects money).")
    if stale_timeout == "REFUSED_LOCALLY":
        problems.append("STRICT_EXACT_MATCH: any non-money field change (timeout/extra) refuses buyers holding an older 402")
        fixes.append("Match on money terms only: scheme, network, asset, payTo equal and signed amount >= current price; the facilitator still verifies the signature.")
    if v1_res == "IGNORED_SILENTLY":
        problems.append("V1_CLIENTS_DROPPED_SILENTLY: X-PAYMENT (x402 v1) payments get the same 402 with no reason")
        fixes.append("Accept v1 payloads too, or return an explicit error telling v1 clients to upgrade.")
    verdict = "ACCEPTS_GOOD_MONEY" if not problems else ("SERVES_UNPAID" if fresh == "ACCEPTED_WITHOUT_SETTLEMENT" else "REFUSES_GOOD_MONEY")
    return {**out, "verdict": verdict, "x402_version": 2, "networks": nets, "problems": problems, "fixes": fixes,
            "note": "OMENZ found this exact leak on its own server (2026-11-20): a funded repeat buyer was refused 4 times."}
