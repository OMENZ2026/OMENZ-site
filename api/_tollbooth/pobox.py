"""OMENZ Agent PO Box v0: a stable address where any agent can drop a message for an agent that isn't running.
Founder "Build all" 2026-11-11 (agent utilities family #13).

- create: get box_id (public address, share it) + owner_key (private, shown once).
- drop: anyone with box_id leaves a JSON message (<= 16 KB). It's sealed to the box's public key (X25519 + AES-GCM),
  so only the owner_key can open it. OMENZ can't read drops.
- inbox: owner opens all waiting messages; ack=true clears them.
Limits: 100 waiting messages per box; boxes live 30 days from their last pickup.
"""
import base64
import json
import secrets
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from locker import LockerError, _kv

MAX_MSG = 16 * 1024
MAX_WAITING = 100
TTL = 30 * 86400
b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw(pub):
    return pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _key(shared, info):
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=info).derive(shared)


def create(label=None):
    priv = X25519PrivateKey.generate()
    box_id = "pb_" + secrets.token_hex(12)
    now = int(time.time())
    _kv("PUT", box_id, {"v": 0, "pub": b64(_raw(priv.public_key())), "label": (label or "")[:80], "created": now,
                        "expires": now + TTL, "msgs": []})
    owner_key = b64(priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    return {"box_id": box_id, "owner_key": owner_key, "expires_at": now + TTL,
            "note": "Share box_id so others can drop messages. Keep owner_key private: it's shown once and is the only way to open the box."}


def _box(box_id):
    if not (box_id or "").startswith("pb_"):
        raise LockerError(400, "box_id required")
    box = _kv("GET", box_id)
    if box is None or box["expires"] < time.time():
        raise LockerError(404, "no such box (or expired)")
    return box


def drop(box_id, message, sender=None, subject=None):
    if not isinstance(message, (dict, list, str)) or message in ("", {}, []):
        raise LockerError(400, "message must be non-empty JSON (object, list or string)")
    raw = json.dumps({"from": (sender or "")[:80], "subject": (subject or "")[:120], "body": message},
                     separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > MAX_MSG:
        raise LockerError(413, f"message is {len(raw)} bytes; max {MAX_MSG}")
    box = _box(box_id)
    if len(box["msgs"]) >= MAX_WAITING:
        raise LockerError(409, "box is full; the owner must pick up messages first")
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(unb64(box["pub"])))
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_key(shared, b"omenz-pobox-v0|" + box_id.encode())).encrypt(nonce, raw, box_id.encode())
    msg_id = "m_" + secrets.token_hex(6)
    entry = {"id": msg_id, "at": int(time.time()), "eph": b64(_raw(eph.public_key())), "n": b64(nonce), "ct": b64(ct)}
    conflict = False
    for _attempt in range(2):  # read-modify-write; re-read to catch a concurrent drop overwriting ours
        box["msgs"].append(entry)
        _kv("PUT", box_id, box)
        check = _box(box_id)
        if any(m["id"] == msg_id for m in check["msgs"]):
            box = check
            break
        conflict = True
        box = check
    else:
        raise LockerError(503, "busy box; retry the drop")
    return {"dropped": msg_id, "box_id": box_id, "waiting": len(box["msgs"]), "_conflict": conflict, "_bytes": len(raw)}


def inbox(box_id, owner_key, ack=False):
    box = _box(box_id)
    try:
        priv = X25519PrivateKey.from_private_bytes(unb64(owner_key or ""))
        if _raw(priv.public_key()) != unb64(box["pub"]):
            raise ValueError
    except Exception:
        raise LockerError(403, "wrong owner key")
    out = []
    for m in box["msgs"]:
        try:  # one damaged entry must not lock the owner out of the rest
            shared = priv.exchange(X25519PublicKey.from_public_bytes(unb64(m["eph"])))
            raw = AESGCM(_key(shared, b"omenz-pobox-v0|" + box_id.encode())).decrypt(unb64(m["n"]), unb64(m["ct"]), box_id.encode())
            out.append({"id": m.get("id"), "at": m.get("at"), **json.loads(raw)})
        except Exception:
            out.append({"id": m.get("id"), "at": m.get("at"), "error": "unreadable message (damaged or not sealed to this box)"})
    if ack:
        box["msgs"] = []
    box["expires"] = int(time.time()) + TTL
    _kv("PUT", box_id, box)
    return {"box_id": box_id, "messages": out, "cleared": bool(ack), "expires_at": box["expires"]}
