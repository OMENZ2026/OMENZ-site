"""OMENZ Agent Job Ledger: one append-only, hash-chained record of what a job consumed and did.

Tool calls, money spent, receipts, handoffs, failures, outputs and status, each entry chained to the one before it
(sha256), so anyone holding the key can prove nothing was edited or removed afterwards. Pairs with Receipt Locker
(payment proofs), Failure Receipt (why it failed) and Handoff Packager (who has it now).

- create(job_id, objective) -> ledger_id + ledger_key (shown once)
- append(ledger_id, key, entry) -> seq, hash   (entry secret-scanned; secrets refused, not stored)
- get(ledger_id, key) -> entries, totals (spent, by type, last status), chain_intact
Storage: OMENZ Apify key-value store, 90 days, max 500 entries. Deterministic, no AI calls.
"""
import hashlib
import hmac
import json
import secrets
import time

import secret_scan
from locker import LockerError, _kv

VERSION = "0.1.0"
TYPES = ["tool_call", "spend", "receipt", "handoff", "failure", "output", "status", "note", "decision"]
MAX_ENTRIES, MAX_ENTRY_BYTES, TTL = 500, 8 * 1024, 90 * 86400
GENESIS = "0" * 64


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _kh(key):
    return hashlib.sha256(("omenz-ledger|" + key).encode()).hexdigest()


def create(job_id=None, objective=None):
    lid, key = "lg_" + secrets.token_hex(12), secrets.token_urlsafe(32)
    now = int(time.time())
    rec = {"v": 0, "key_hash": _kh(key), "job_id": str(job_id or "")[:120], "objective": str(objective or "")[:300],
           "created": now, "expires": now + TTL, "entries": []}
    _kv("PUT", lid, rec)
    return {"ledger_id": lid, "ledger_key": key, "expires_at": rec["expires"],
            "note": "Keep ledger_key: it's shown once. Send it as header X-Ledger-Key to append or read."}


def _load(lid, key):
    if not (lid or "").startswith("lg_") or not key:
        raise LockerError(400, "ledger id and X-Ledger-Key header required")
    rec = _kv("GET", lid)
    if rec is None or rec["expires"] < time.time():
        raise LockerError(404, "no such ledger (or expired)")
    if not hmac.compare_digest(rec["key_hash"], _kh(key)):
        raise LockerError(403, "wrong ledger key")
    return rec


def append(lid, key, entry):
    if not isinstance(entry, dict) or not entry:
        raise LockerError(400, "entry must be a non-empty JSON object")
    typ = str(entry.get("type") or "note").lower()
    if typ not in TYPES:
        raise LockerError(422, f"type must be one of {TYPES}")
    if entry.get("amount_usd") is not None:
        try:
            if float(entry["amount_usd"]) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise LockerError(422, "amount_usd must be a non-negative number")
    body = {**entry, "type": typ}
    raw = _canon(body)
    if len(raw.encode()) > MAX_ENTRY_BYTES:
        raise LockerError(413, f"entry over {MAX_ENTRY_BYTES} bytes")
    scan = secret_scan.scan(body)
    if scan["verdict"] == "BLOCK":
        raise LockerError(422, "entry contains secrets (" + ", ".join(sorted(scan["counts"])) + "); not stored")
    rec = _load(lid, key)
    if len(rec["entries"]) >= MAX_ENTRIES:
        raise LockerError(409, f"ledger full ({MAX_ENTRIES} entries); create a new one and link it")
    prev = rec["entries"][-1]["hash"] if rec["entries"] else GENESIS
    seq = len(rec["entries"]) + 1
    at = int(time.time())
    h = hashlib.sha256((prev + "|" + str(seq) + "|" + str(at) + "|" + raw).encode()).hexdigest()
    rec["entries"].append({"seq": seq, "at": at, "entry": body, "prev": prev, "hash": h})
    _kv("PUT", lid, rec)
    return {"ledger_id": lid, "seq": seq, "hash": h, "prev": prev,
            "warning": "possible sensitive data: " + ", ".join(sorted(scan["counts"])) if scan["verdict"] == "REVIEW" else None}


def verify_chain(entries):
    prev = GENESIS
    for i, e in enumerate(entries, 1):
        h = hashlib.sha256((prev + "|" + str(i) + "|" + str(e["at"]) + "|" + _canon(e["entry"])).encode()).hexdigest()
        if e["seq"] != i or e["prev"] != prev or e["hash"] != h:
            return False, i
        prev = h
    return True, None


def get(lid, key, since_seq=0):
    rec = _load(lid, key)
    ok, broken = verify_chain(rec["entries"])
    spent, by_type, status = 0.0, {}, None
    for e in rec["entries"]:
        en = e["entry"]
        by_type[en["type"]] = by_type.get(en["type"], 0) + 1
        if en.get("amount_usd") is not None and en["type"] in ("spend", "tool_call", "receipt"):
            spent += float(en["amount_usd"])
        if en["type"] == "status":
            status = en.get("status") or en.get("value")
    try:
        since = int(since_seq or 0)
    except (TypeError, ValueError):
        since = 0
    return {"ledger_id": lid, "job_id": rec["job_id"], "objective": rec["objective"], "entries_total": len(rec["entries"]),
            "entries": [e for e in rec["entries"] if e["seq"] > since][-200:], "chain_intact": ok, "broken_at_seq": broken,
            "head_hash": rec["entries"][-1]["hash"] if rec["entries"] else GENESIS,
            "totals": {"spent_usd": round(spent, 6), "by_type": by_type, "last_status": status}, "expires_at": rec["expires"]}
