"""Wallet Watch: low-balance / low-runway alerts for agent wallets (founder handoff 11-20 sec 4 'replenishment alerts').

An agent (or its owner) registers a Base wallet with thresholds; OMENZ checks it daily (same cron as Uptime Watch) and on
every report read (if the last check is >1h old). When USDC falls under min_usdc or runway (days of recent spend left)
under min_days, it drops ONE alert into the owner's Agent PO Box (if given) and marks the watch ALERTING until the wallet
recovers. Read-only public chain data; OMENZ never touches the wallet.

- watch(address, min_usdc, min_days, pobox_id, days) -> watch_id + watch_key (shown once). $0.01 for up to 30 days.
- report(id, key)  -> current balance/runway, state OK / LOW / ALERTING, history. $0.002.
- run_due(limit)   -> cron.
"""
import hashlib
import hmac
import secrets
import time

import wallet
from locker import LockerError, _kv

MAX_DAYS = 30
INDEX = "wallet_watch_index"


def _kh(k):
    return hashlib.sha256(("omenz-walletwatch|" + k).encode()).hexdigest()


def _check(rec):
    r = wallet.runway(rec["address"], 7)
    usdc, left = r.get("usdc_balance"), r.get("days_left")
    reasons = []
    if rec.get("min_usdc") is not None and usdc is not None and usdc < rec["min_usdc"]:
        reasons.append(f"USDC {usdc:.4f} < {rec['min_usdc']}")
    if rec.get("min_days") is not None and left is not None and left < rec["min_days"]:
        reasons.append(f"runway {left:.2f} days < {rec['min_days']}")
    c = {"at": int(time.time()), "usdc": usdc, "days_left": left, "daily_spend_usd": r.get("daily_spend_usd"), "low": bool(reasons), "reasons": reasons}
    rec["checks"] = (rec["checks"] + [c])[-120:]
    rec["last"] = c["at"]
    if reasons and not rec.get("alerting"):
        rec["alerting"] = True
        if rec.get("pobox_id"):
            try:
                import pobox
                pobox.drop(rec["pobox_id"], {"type": "omenz.wallet-alert.v0", "address": rec["address"], "usdc": usdc, "days_left": left,
                                             "reasons": reasons, "next": "Top up this wallet before purchases start failing."},
                           sender="OMENZ Wallet Watch", subject="Wallet running low")
                c["alert_sent"] = True
            except Exception as e:
                c["alert_error"] = str(e)[:120]
    elif not reasons:
        rec["alerting"] = False
    return c


def watch(address, min_usdc=None, min_days=None, pobox_id=None, days=30):
    a = str(address or "").strip()
    if not (a.startswith("0x") and len(a) == 42):
        raise LockerError(422, "address must be a 0x Base wallet address")
    try:
        min_usdc = None if min_usdc in (None, "") else float(min_usdc)
        min_days = None if min_days in (None, "") else float(min_days)
        days = max(1, min(int(days or MAX_DAYS), MAX_DAYS))
    except (TypeError, ValueError):
        raise LockerError(422, "min_usdc / min_days must be numbers, days an integer 1-30")
    if min_usdc is None and min_days is None:
        raise LockerError(422, "set min_usdc and/or min_days")
    wid, key = "ww_" + secrets.token_hex(10), secrets.token_urlsafe(24)
    now = int(time.time())
    rec = {"address": a, "min_usdc": min_usdc, "min_days": min_days, "pobox_id": (pobox_id or None), "key_hash": _kh(key),
           "created": now, "expires": now + days * 86400, "checks": [], "last": 0, "alerting": False}
    try:
        first = _check(rec)
    except Exception as e:
        raise LockerError(502, f"could not read the wallet on Base right now ({type(e).__name__})")
    _kv("PUT", wid, rec)
    try:
        idx = _kv("GET", INDEX) or {"ids": []}
        idx["ids"] = [i for i in idx["ids"] if i != wid][-4999:] + [wid]
        _kv("PUT", INDEX, idx)
    except Exception:
        pass
    return {"watch_id": wid, "watch_key": key, "address": a, "thresholds": {"min_usdc": min_usdc, "min_days": min_days},
            "alerts_to": pobox_id or "none (read GET /v1/wallet-watch/report)", "expires_at": rec["expires"], "first_check": first,
            "report": "GET /api/tollbooth/v1/wallet-watch/report?id=<watch_id> with header X-Watch-Key ($0.002)",
            "note": "watch_key is shown once. Checked daily; one PO Box alert per low spell (re-arms after the wallet recovers)."}


def report(wid, key):
    if not (wid or "").startswith("ww_") or not key:
        raise LockerError(401, "id and X-Watch-Key header required")
    rec = _kv("GET", wid)
    if rec is None:
        raise LockerError(404, "no such watch")
    if not hmac.compare_digest(rec["key_hash"], _kh(key)):
        raise LockerError(403, "wrong watch key")
    if time.time() - rec.get("last", 0) > 3600 and rec["expires"] > time.time():
        _check(rec)
        _kv("PUT", wid, rec)
    last = rec["checks"][-1] if rec["checks"] else {}
    return {"watch_id": wid, "address": rec["address"], "state": "ALERTING" if rec.get("alerting") else "OK",
            "now": last, "thresholds": {"min_usdc": rec["min_usdc"], "min_days": rec["min_days"]},
            "low_checks": sum(1 for c in rec["checks"] if c.get("low")), "checks": len(rec["checks"]),
            "history": rec["checks"][-14:], "expires_at": rec["expires"]}


def run_due(limit=60):
    idx = _kv("GET", INDEX) or {"ids": []}
    now, done, keep = time.time(), 0, []
    for wid in idx["ids"]:
        rec = _kv("GET", wid)
        if not rec or rec["expires"] < now:
            continue
        keep.append(wid)
        if done < limit and now - rec.get("last", 0) > 20 * 3600:
            try:
                _check(rec)
                _kv("PUT", wid, rec)
                done += 1
            except Exception:
                pass
    if len(keep) != len(idx["ids"]):
        _kv("PUT", INDEX, {"ids": keep})
    return {"checked": done, "active_watches": len(keep)}
