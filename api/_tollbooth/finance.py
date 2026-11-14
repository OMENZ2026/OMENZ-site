"""OMENZ Agent Finance: the back office for agents that buy and sell machine services.

- reconcile(invoice, payments)   Invoice/Payment Reconciler: invoice lines vs USDC-on-Base payments (each tx checked
                                 on-chain: payer, payee, amount) -> MATCH / UNDERPAID / OVERPAID / MISSING / UNVERIFIED.
- forecast(spend)                Agent Budget Forecaster: spend history (list or a Job Ledger) -> daily rate, next 7/30-day
                                 projection, biggest dependencies, trend.
- watchdog(endpoints)            Subscription Watchdog: the paid endpoints an agent business relies on -> live price vs
                                 expected (drift), down/up, terms changed (via Terms Changed? fingerprints).
- snapshot(url, method)          Machine Warranty / Purchase Snapshot: signed record of what a service promised at
                                 purchase time (live payment requirements + description + terms digest).
- refund_request(...)            Structured Refund Request: failure + receipts + snapshot -> a standard, signed dispute object.
Deterministic, no AI calls, never pays a target.
"""
import hashlib
import re
import time
from collections import defaultdict

import contracts
import receipts
import x402_probe
from locker import LockerError

VERSION = "0.1.0"
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
TX = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _f(v, name):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise LockerError(422, f"{name} must be a number")
    if x < 0:
        raise LockerError(422, f"{name} must not be negative")
    return x


def reconcile(invoice, payments):
    if not isinstance(invoice, dict) or not isinstance(payments, list):
        raise LockerError(422, "invoice object and payments list required")
    payee = str(invoice.get("payee") or "")
    lines = invoice.get("lines") or []
    line_total = round(sum(_f(l.get("amount_usd"), "lines[].amount_usd") for l in lines if isinstance(l, dict)), 6)
    total = _f(invoice["total_usd"], "total_usd") if invoice.get("total_usd") is not None else line_total
    issues = []
    if lines and abs(line_total - total) > 1e-6:
        issues.append(f"invoice lines add up to ${line_total:g} but total says ${total:g}")
    if len(payments) > 20:
        raise LockerError(422, "at most 20 payments per reconciliation")
    rows, verified_sum, unverified = [], 0.0, 0
    seen = set()
    for p in payments:
        p = p if isinstance(p, dict) else {}
        tx, payer, amt = str(p.get("tx_hash") or ""), str(p.get("payer") or ""), p.get("amount_usd")
        row = {"tx_hash": tx, "payer": payer, "amount_usd": amt}
        if tx in seen:
            row["status"] = "DUPLICATE"
            issues.append(f"payment {tx[:12]}… listed twice")
            rows.append(row)
            continue
        seen.add(tx)
        if not (TX.match(tx) and ADDR.match(payer) and ADDR.match(payee)):
            row["status"] = "UNCHECKABLE"
            unverified += 1
            rows.append(row)
            continue
        c = receipts._chain_check(tx, payer, payee, _f(amt or 0, "amount_usd"))
        row["chain"] = c
        if c.get("verified"):
            row["status"] = "VERIFIED"
            verified_sum += c["usdc_amount"]
        else:
            row["status"] = "NOT_VERIFIED" if c.get("checked") else "RPC_UNAVAILABLE"
            unverified += 1
        rows.append(row)
    diff = round(verified_sum - total, 6)
    if not payments:
        verdict = "MISSING"
    elif abs(diff) <= 1e-6:
        verdict = "MATCH" if not unverified else "MATCH_WITH_UNVERIFIED"
    elif diff < 0:
        verdict = "UNDERPAID" if verified_sum > 0 else ("UNVERIFIED" if unverified else "MISSING")
    else:
        verdict = "OVERPAID"
    return {"version": VERSION, "verdict": verdict, "invoice_total_usd": total, "verified_paid_usd": round(verified_sum, 6),
            "difference_usd": diff, "payments": rows, "issues": issues,
            "note": "Only USDC on Base with 0x addresses is checked on-chain; other payments show as UNCHECKABLE."}


def forecast(spend):
    if not isinstance(spend, list) or not spend:
        raise LockerError(422, "spend: list of {at (unix), amount_usd, tool?}")
    pts = []
    for s in spend[:5000]:
        if not isinstance(s, dict):
            continue
        try:
            pts.append((int(s["at"]), _f(s.get("amount_usd"), "amount_usd"), str(s.get("tool") or s.get("type") or "other")[:80]))
        except (KeyError, TypeError, ValueError):
            raise LockerError(422, "each spend item needs at (unix seconds) and amount_usd")
    pts.sort()
    span_days = max(1.0, (pts[-1][0] - pts[0][0]) / 86400) if len(pts) > 1 else 1.0
    total = sum(p[1] for p in pts)
    rate = total / span_days
    by = defaultdict(float)
    for _, a, t in pts:
        by[t] += a
    top = sorted(by.items(), key=lambda x: -x[1])[:5]
    half = pts[0][0] + (pts[-1][0] - pts[0][0]) / 2
    first = sum(a for at, a, _ in pts if at <= half)
    second = total - first
    trend = "rising" if second > first * 1.25 else "falling" if second < first * 0.8 else "flat"
    return {"version": VERSION, "observed_days": round(span_days, 2), "observed_total_usd": round(total, 6),
            "daily_rate_usd": round(rate, 6), "next_7_days_usd": round(rate * 7, 4), "next_30_days_usd": round(rate * 30, 4),
            "trend": trend, "biggest_dependencies": [{"tool": t, "usd": round(a, 6), "share": round(a / total, 3) if total else 0} for t, a in top],
            "note": "linear projection of the observed rate; widen it if the workload is about to change"}


def watchdog(endpoints):
    import terms_changed
    if not isinstance(endpoints, list) or not endpoints or len(endpoints) > 8:
        raise LockerError(422, "endpoints: list of 1-8 {url, method?, expected_price_usd?, terms_url?, terms_fingerprint?}")
    rows, alerts = [], []
    for e in endpoints:
        e = e if isinstance(e, dict) else {}
        u = e.get("url")
        if not isinstance(u, str):
            raise LockerError(422, "each endpoint needs a url")
        q = x402_probe.quote(u, e.get("method", "GET"))
        row = {"url": u, "status": q["status"], "live_price_usd": q.get("cheapest_usd"), "latency_ms": q.get("latency_ms")}
        if q["status"] not in ("quoted", "no_payment_requested"):
            alerts.append(f"{u}: not taking payment ({q['status']})")
        exp = e.get("expected_price_usd")
        if exp is not None and q.get("cheapest_usd") is not None and abs(q["cheapest_usd"] - _f(exp, "expected_price_usd")) > 1e-9:
            row["price_drift"] = {"expected": float(exp), "live": q["cheapest_usd"]}
            alerts.append(f"{u}: price moved ${float(exp):g} -> ${q['cheapest_usd']:g}")
        if e.get("terms_url"):
            t = terms_changed.check(e["terms_url"], e.get("terms_fingerprint"))
            row["terms"] = {k: t.get(k) for k in ("state", "kinds", "money_changed", "added", "removed", "fingerprint")}
            if t.get("state") == "CHANGED":
                alerts.append(f"{u}: terms changed ({', '.join(t.get('kinds') or [])})")
        rows.append(row)
    return {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "alerts": alerts,
            "endpoints": rows, "verdict": "ALERT" if alerts else "OK",
            "note": "keep each terms fingerprint and pass it back next time; we store nothing"}


def snapshot(url, method="GET"):
    import capability_card
    c = capability_card.card(url, method)
    if c.get("status") != "ok":
        raise LockerError(422, f"no x402 offer to snapshot at this url ({c.get('status')})")
    snap = {"schema": "omenz.purchase-snapshot.v0", "url": url, "method": (method or "GET").upper(), "taken_at": int(time.time()),
            "offer": c["endpoints"][0] if c.get("endpoints") else None, "digest": c.get("digest"), "issuer": "omenz.org"}
    return {"snapshot": snap, "token": contracts._sign(snap),
            "note": "Proof of what was promised when you bought. Attach it to a refund request or dispute; verify with /v1/passport/key."}


REMEDIES = ["refund", "partial_refund", "redo", "credit"]


def refund_request(order, failure=None, receipt_ids=None, snapshot_token=None, remedy="refund", amount_usd=None):
    if not isinstance(order, dict) or not order.get("seller") or not order.get("description"):
        raise LockerError(422, "order {seller, description, amount_usd?, ordered_at?} required")
    if remedy not in REMEDIES:
        raise LockerError(422, f"remedy must be one of {REMEDIES}")
    snap = contracts._open(snapshot_token) if snapshot_token else None
    if snapshot_token and not snap:
        raise LockerError(422, "snapshot token invalid or forged")
    req = {"schema": "omenz.refund-request.v0", "request_id": "rr_" + hashlib.sha256(str(time.time()).encode()).hexdigest()[:16],
           "created": int(time.time()), "order": {k: order.get(k) for k in ("seller", "buyer", "description", "amount_usd", "ordered_at", "tx_hash")},
           "failure": failure if isinstance(failure, dict) else None, "receipt_ids": [str(r)[:60] for r in (receipt_ids or [])][:10],
           "promised": snap, "remedy": remedy,
           "amount_requested_usd": _f(amount_usd, "amount_usd") if amount_usd is not None else order.get("amount_usd"),
           "evidence_strength": sum([bool(snap), bool(receipt_ids), bool(failure)]), "issuer": "omenz.org"}
    gaps = [g for g, ok in (("no purchase snapshot (what was promised)", snap), ("no payment receipts", receipt_ids),
                            ("no failure receipt (what went wrong)", failure)) if not ok]
    return {"request": req, "token": contracts._sign(req), "gaps": gaps,
            "note": "Send the token to the seller (or their PO Box). OMENZ packages and signs the evidence; it doesn't rule on or move money."}
