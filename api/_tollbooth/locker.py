"""OMENZ Agent Locker v0: an agent checks a job's resume packet in, works on something else, then checks it out.
Founder idea 2026-11-11 ("agent closet / PO box"); founder "yes on agent locker run it".

- put: store a JSON resume packet (<= 64 KB) for up to 30 days. Returns locker_id + access_key (shown once).
  Optional "to" label makes it a PO-box handoff: hand the id + key to another agent.
- get: retrieve it with the key; pass fields=a,b to hydrate only the parts you need (saves the reader's context).
- delete: free, with the key.
Encryption at rest: AES-256-GCM, with a key derived from the access key, which OMENZ never stores. A lost key = a lost packet.
Storage: Apify key-value store. Expiry enforced on read; expired records are purged on access.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STORE = os.environ.get("LOCKER_KV_STORE", "VRiqBigG65b1Aeb1H")
TOKEN = os.environ.get("APIFY_LOG_TOKEN", "")
MAX_BYTES = 64 * 1024
MAX_DAYS = 30
SUGGESTED_FIELDS = ["objective", "decisions", "open_items", "facts", "permissions", "prohibited", "artifacts", "next_action", "pointers"]


class LockerError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status
        self.msg = msg


def _kv(method, key, body=None):
    if not (STORE and TOKEN):
        raise LockerError(503, "locker storage not configured")
    url = f"https://api.apify.com/v2/key-value-stores/{STORE}/records/{key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read()
            return json.loads(raw) if raw and method == "GET" else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise LockerError(502, f"storage error {e.code}")


def _aes(access_key, locker_id):
    return AESGCM(hashlib.sha256(("omenz-locker-v0|" + locker_id + "|" + access_key).encode()).digest())


def put(packet, ttl_days=7, to=None, frm=None):
    if not isinstance(packet, dict) or not packet:
        raise LockerError(400, "packet must be a non-empty JSON object")
    raw = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > MAX_BYTES:
        raise LockerError(413, f"packet is {len(raw)} bytes; max {MAX_BYTES}")
    ttl = max(1, min(int(ttl_days or 7), MAX_DAYS))
    locker_id = "lk_" + secrets.token_hex(12)
    access_key = secrets.token_urlsafe(32)
    nonce = secrets.token_bytes(12)
    ct = _aes(access_key, locker_id).encrypt(nonce, raw, locker_id.encode())
    now = int(time.time())
    rec = {"v": 0, "nonce": base64.b64encode(nonce).decode(), "ct": base64.b64encode(ct).decode(), "created": now,
           "expires": now + ttl * 86400, "to": (to or "")[:80], "from": (frm or "")[:80], "bytes": len(raw),
           "fields": sorted(packet.keys())[:50]}
    _kv("PUT", locker_id, rec)
    return {"locker_id": locker_id, "access_key": access_key, "expires_at": rec["expires"], "bytes": len(raw),
            "fields": rec["fields"], "note": "Keep access_key: it's shown once and OMENZ can't recover it (encrypted at rest)."}


def _load(locker_id, access_key):
    if not (locker_id or "").startswith("lk_") or not access_key:
        raise LockerError(400, "locker_id and X-Locker-Key header required")
    rec = _kv("GET", locker_id)
    if rec is None:
        raise LockerError(404, "no such locker (or expired)")
    if rec["expires"] < time.time():
        _kv("DELETE", locker_id)
        raise LockerError(404, "no such locker (or expired)")
    return rec


def get(locker_id, access_key, fields=None):
    rec = _load(locker_id, access_key)
    try:
        raw = _aes(access_key, locker_id).decrypt(base64.b64decode(rec["nonce"]), base64.b64decode(rec["ct"]), locker_id.encode())
    except Exception:
        raise LockerError(403, "wrong access key")
    packet = json.loads(raw)
    if fields:
        want = [f.strip() for f in fields.split(",") if f.strip()]
        packet = {k: packet[k] for k in want if k in packet}
    return {"locker_id": locker_id, "to": rec.get("to", ""), "from": rec.get("from", ""), "expires_at": rec["expires"],
            "fields_available": rec.get("fields", []), "packet": packet}


def delete(locker_id, access_key):
    rec = _load(locker_id, access_key)
    try:
        _aes(access_key, locker_id).decrypt(base64.b64decode(rec["nonce"]), base64.b64decode(rec["ct"]), locker_id.encode())
    except Exception:
        raise LockerError(403, "wrong access key")
    _kv("DELETE", locker_id)
    return {"deleted": locker_id}
