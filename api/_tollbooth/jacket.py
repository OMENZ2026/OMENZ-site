"""Job Jacket: the portable minimum working state for one assignment (founder 2026-11-15: "provide and hold the jacket
for that job in storage so they don't have to carry it or waste tokens"; "jacket go").

An agent checks the jacket OUT at the start of a shift: objective, instructions, the current state (trimmed to what it
asked for), last checkpoint, and its Permission Passport verdict. At the end of the shift it checks the jacket back IN:
the state patch becomes a new version, encrypted in the Locker, with a lease so two workers can't hold it at once.
The next worker (or the same one tomorrow) resumes in one call without dragging history through its context.

- create(spec)                        -> jacket_id + jacket_key (shown once), version 1
- checkout(id, key, worker, ...)      -> minimum working state + lease (409 if another worker holds an active lease)
- checkin(id, key, worker, ...)       -> version + 1, lease released (or renewed), optional Job Ledger entry
- history(id, key)                    -> versions: who, when, checkpoint, note, state hash (no state contents)
Storage: OMENZ Apify KV, AES-GCM with the jacket key (OMENZ can't read jackets), 64 KB state, up to 30 days.
Composes Locker (encryption), Context Diet (trimming), Passport (permissions) and Job Ledger (proof).
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

import hygiene
import ledger
import passport
import secret_scan
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from locker import LockerError, _kv

VERSION = "0.1.0"
MAX_STATE = 64 * 1024
MAX_DAYS = 30
LEASE_MIN, LEASE_MAX = 5, 24 * 60


def _kh(key):
    return hashlib.sha256(("omenz-jacket|" + key).encode()).hexdigest()


def _aes(key, jid):
    return AESGCM(hashlib.sha256(("omenz-jacket-v0|" + jid + "|" + key).encode()).digest())


def _seal(key, jid, body):
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > MAX_STATE:
        raise LockerError(413, f"jacket contents are {len(raw)} bytes; max {MAX_STATE}. Put bulky data in a Locker and keep its pointer here.")
    n = secrets.token_bytes(12)
    return {"nonce": base64.b64encode(n).decode(), "ct": base64.b64encode(_aes(key, jid).encrypt(n, raw, jid.encode())).decode(),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()[:16]}


def _open(key, jid, rec):
    try:
        raw = _aes(key, jid).decrypt(base64.b64decode(rec["nonce"]), base64.b64decode(rec["ct"]), jid.encode())
    except Exception:
        raise LockerError(403, "wrong jacket key")
    return json.loads(raw)


def _load(jid, key):
    if not (jid or "").startswith("jk_") or not key:
        raise LockerError(401, "X-Jacket-Id and X-Jacket-Key headers required")
    rec = _kv("GET", jid)
    if rec is None or rec["expires"] < time.time():
        raise LockerError(404, "no such jacket (or expired)")
    if not hmac.compare_digest(rec["key_hash"], _kh(key)):
        raise LockerError(403, "wrong jacket key")
    return rec


def _clean_state(state, what):
    if state is None:
        return {}
    if not isinstance(state, dict):
        raise LockerError(422, f"{what} must be a JSON object")
    scan = secret_scan.scan(state)
    if scan["verdict"] == "BLOCK":
        raise LockerError(422, f"{what} contains secrets (" + ", ".join(sorted(scan["counts"])) +
                          "); store credentials elsewhere and keep only a reference name in the jacket. Nothing was saved.")
    return state


def create(spec):
    spec = spec or {}
    objective = str(spec.get("objective") or "").strip()
    if not objective:
        raise LockerError(422, "objective is required (what this job is for)")
    state = _clean_state(spec.get("state"), "state")
    try:
        ttl = max(1, min(int(spec.get("ttl_days") or 14), MAX_DAYS))
    except (TypeError, ValueError):
        raise LockerError(422, "ttl_days must be an integer")
    jid, key = "jk_" + secrets.token_hex(12), secrets.token_urlsafe(32)
    now = int(time.time())
    body = {"objective": objective[:1000], "instructions": str(spec.get("instructions") or "")[:4000], "state": state,
            "checkpoint": str(spec.get("checkpoint") or "start")[:300], "passport_token": str(spec.get("passport_token") or "")[:4000] or None,
            "ledger_id": str(spec.get("ledger_id") or "")[:40] or None}
    sealed = _seal(key, jid, body)
    rec = {"v": 0, "job_id": str(spec.get("job_id") or "")[:80], "key_hash": _kh(key), "created": now, "expires": now + ttl * 86400,
           "version": 1, "lease": None, "sealed": sealed,
           "history": [{"version": 1, "at": now, "worker": str(spec.get("worker") or "creator")[:80], "checkpoint": body["checkpoint"],
                        "note": "created", "state_sha256": sealed["sha256"], "bytes": sealed["bytes"]}]}
    _kv("PUT", jid, rec)
    return {"jacket_id": jid, "jacket_key": key, "version": 1, "expires_at": rec["expires"],
            "use": "Start a shift: POST /api/tollbooth/v1/jacket/checkout with headers X-Jacket-Id / X-Jacket-Key. End it: POST /v1/jacket/checkin.",
            "note": "jacket_key is shown once; OMENZ can't recover it (contents are encrypted with it)."}


def checkout(jid, key, d):
    d = d or {}
    rec = _load(jid, key)
    worker = str(d.get("worker") or "").strip()[:80]
    if not worker:
        raise LockerError(422, "worker is required (who is putting the jacket on)")
    now = int(time.time())
    lease = rec.get("lease")
    if lease and lease["until"] > now and lease["worker"] != worker and not d.get("take_over"):
        raise LockerError(409, f"jacket is checked out by '{lease['worker']}' until {lease['until']} (unix). "
                               "Wait, or pass take_over=true if that worker is dead (logged in history).")
    try:
        minutes = max(LEASE_MIN, min(int(d.get("lease_minutes") or 60), LEASE_MAX))
    except (TypeError, ValueError):
        raise LockerError(422, "lease_minutes must be an integer")
    body = _open(key, jid, rec["sealed"])
    state = body["state"]
    fields = d.get("fields")
    if fields:
        want = [str(f) for f in fields][:50] if isinstance(fields, list) else [f.strip() for f in str(fields).split(",") if f.strip()]
        state = {k: state[k] for k in want if k in state}
    trimmed = None
    if d.get("max_string_chars") or d.get("max_list_items"):
        dt = hygiene.diet(state, required=d.get("required"), max_string_chars=d.get("max_string_chars") or 400,
                          max_list_items=d.get("max_list_items") or 50)
        state, trimmed = dt["packet"], {k: dt[k] for k in ("bytes_before", "bytes_after", "approx_tokens_saved")}
    took_over = bool(lease and lease["until"] > now and lease["worker"] != worker)
    rec["lease"] = {"worker": worker, "since": now, "until": now + minutes * 60}
    if took_over:
        rec["history"].append({"version": rec["version"], "at": now, "worker": worker, "checkpoint": body["checkpoint"],
                               "note": f"took over from {lease['worker']}", "state_sha256": rec["sealed"]["sha256"], "bytes": rec["sealed"]["bytes"]})
    _kv("PUT", jid, rec)
    out = {"jacket_id": jid, "version": rec["version"], "job_id": rec["job_id"], "objective": body["objective"],
           "instructions": body["instructions"], "checkpoint": body["checkpoint"], "state": state,
           "state_fields_available": sorted(body["state"].keys())[:100], "lease": rec["lease"], "trimmed": trimmed,
           "ledger_id": body.get("ledger_id"), "checkin": "POST /api/tollbooth/v1/jacket/checkin when the shift ends"}
    if body.get("passport_token"):
        pc = passport.check(body["passport_token"], d.get("action") or {})
        out["passport"] = {"decision": pc.get("decision"), "valid": pc.get("valid", pc.get("decision") != "DENY"),
                           "reasons": pc.get("reasons", [])[:6], "token": body["passport_token"]}
    return out


def checkin(jid, key, d, ledger_key=None):
    d = d or {}
    rec = _load(jid, key)
    worker = str(d.get("worker") or "").strip()[:80]
    if not worker:
        raise LockerError(422, "worker is required")
    now = int(time.time())
    lease = rec.get("lease")
    if not lease or lease["worker"] != worker:
        raise LockerError(409, "you don't hold this jacket: check it out first (or take_over if the holder died)")
    body = _open(key, jid, rec["sealed"])
    if d.get("state") is not None and d.get("state_patch") is not None:
        raise LockerError(422, "send state (replace) or state_patch (merge), not both")
    if d.get("state") is not None:
        body["state"] = _clean_state(d["state"], "state")
    elif d.get("state_patch") is not None:
        patch = _clean_state(d["state_patch"], "state_patch")
        for k, v in patch.items():
            if v is None:
                body["state"].pop(k, None)
            else:
                body["state"][k] = v
    if d.get("checkpoint"):
        body["checkpoint"] = str(d["checkpoint"])[:300]
    if d.get("instructions"):
        body["instructions"] = str(d["instructions"])[:4000]
    rec["sealed"] = _seal(key, jid, body)
    rec["version"] += 1
    note = str(d.get("note") or "")[:300]
    rec["history"] = (rec["history"] + [{"version": rec["version"], "at": now, "worker": worker, "checkpoint": body["checkpoint"],
                                         "note": note, "state_sha256": rec["sealed"]["sha256"], "bytes": rec["sealed"]["bytes"]}])[-200:]
    rec["lease"] = {"worker": worker, "since": lease["since"], "until": now + 3600} if d.get("keep_lease") else None
    _kv("PUT", jid, rec)
    out = {"jacket_id": jid, "version": rec["version"], "checkpoint": body["checkpoint"], "state_sha256": rec["sealed"]["sha256"],
           "bytes": rec["sealed"]["bytes"], "lease": rec["lease"], "released": rec["lease"] is None}
    if body.get("ledger_id") and ledger_key:
        try:
            le = ledger.append(body["ledger_id"], ledger_key, {"type": "status", "jacket_id": jid, "version": rec["version"],
                                                               "worker": worker, "checkpoint": body["checkpoint"], "note": note})
            out["ledger"] = {"seq": le["seq"], "hash": le["hash"]}
        except LockerError as e:
            out["ledger"] = {"error": e.msg}
    return out


def history(jid, key):
    rec = _load(jid, key)
    return {"jacket_id": jid, "job_id": rec["job_id"], "version": rec["version"], "lease": rec.get("lease"),
            "expires_at": rec["expires"], "history": rec["history"][-50:][::-1]}
