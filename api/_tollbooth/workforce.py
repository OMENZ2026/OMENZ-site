"""OMENZ Agent Workforce: employment infrastructure for agents that work like staff.

One work queue covers: job intake, claiming with a LEASE (who is responsible right now), heartbeats + checkpoints
(dead-agent recovery: an expired lease returns the job, with its last checkpoint, to the next worker = replacement +
load balancing), completion/failure with retries and a dead state, supervisor escalation (sealed drop into the
supervisor's Agent PO Box), task bidding + award, a worker roster (availability), and scheduling (not_before, repeat).

Keys: owner_key (create/enqueue/award/config) and worker_key (claim/heartbeat/complete/fail/bid/escalate), both shown
once. Storage: OMENZ Apify KV, one record per queue, max 300 open+recent items, 30 days. Deterministic, no AI calls.
v0 limit: last-write-wins under heavy concurrent writes to the same queue (fine for small teams; documented).
"""
import hashlib
import hmac
import secrets
import time

import pobox
import secret_scan
from locker import LockerError, _kv

VERSION = "0.1.0"
MAX_ITEMS, TTL, MAX_PAYLOAD = 300, 30 * 86400, 8 * 1024
STATES = ["queued", "bidding", "leased", "done", "failed", "dead", "escalated"]


def _h(k):
    return hashlib.sha256(("omenz-wq|" + k).encode()).hexdigest()


def _now():
    return int(time.time())


def _load(qid, key, role):
    if not (qid or "").startswith("wq_") or not key:
        raise LockerError(400, "queue_id and X-Queue-Key header required")
    q = _kv("GET", qid)
    if q is None or q["expires"] < time.time():
        raise LockerError(404, "no such queue (or expired)")
    ok_owner = hmac.compare_digest(q["owner_hash"], _h(key))
    ok_worker = hmac.compare_digest(q["worker_hash"], _h(key))
    if role == "owner" and not ok_owner:
        raise LockerError(403, "owner key required")
    if role == "worker" and not (ok_worker or ok_owner):
        raise LockerError(403, "worker or owner key required")
    _sweep(q)
    return q


def _save(qid, q):
    # keep open items + the 100 most recent finished ones
    open_ = [i for i in q["items"] if i["state"] not in ("done", "dead")]
    closed = [i for i in q["items"] if i["state"] in ("done", "dead")][-100:]
    q["items"] = (open_ + closed)[-MAX_ITEMS:]
    _kv("PUT", qid, q)


def _event(item, what, who=None, **kw):
    item.setdefault("history", []).append({"at": _now(), "event": what, "by": who, **kw})
    item["history"] = item["history"][-40:]


def _sweep(q):
    """Expired leases go back to the queue with their checkpoint (dead-agent recovery)."""
    now = _now()
    for i in q["items"]:
        if i["state"] == "leased" and i.get("lease_until", 0) < now:
            _event(i, "lease_expired", i.get("holder"), checkpoint=i.get("checkpoint"))
            i["attempts"] = i.get("attempts", 0) + 1
            i["holder"], i["lease_until"] = None, None
            i["state"] = "dead" if i["attempts"] >= i.get("max_attempts", 3) else "queued"
    for w in q["roster"].values():
        w["available"] = now - w.get("last_seen", 0) < q.get("heartbeat_grace_s", 300)


def _item(q, item_id):
    for i in q["items"]:
        if i["id"] == item_id:
            return i
    raise LockerError(404, "no such item")


def _public(i):
    return {k: i.get(k) for k in ("id", "title", "state", "priority", "holder", "lease_until", "attempts", "max_attempts",
                                  "not_before", "repeat_every_minutes", "payload", "checkpoint", "result", "bids",
                                  "escalation", "history", "created")}


def create(name=None, supervisor_box_id=None, lease_seconds=900, heartbeat_grace_s=300):
    qid, ok, wk = "wq_" + secrets.token_hex(12), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    try:
        lease = max(30, min(int(lease_seconds or 900), 86400))
        grace = max(30, min(int(heartbeat_grace_s or 300), 86400))
    except (TypeError, ValueError):
        raise LockerError(422, "lease_seconds / heartbeat_grace_s must be integers")
    q = {"v": 0, "name": str(name or "")[:120], "owner_hash": _h(ok), "worker_hash": _h(wk), "created": _now(),
         "expires": _now() + TTL, "lease_seconds": lease, "heartbeat_grace_s": grace,
         "supervisor_box_id": supervisor_box_id if str(supervisor_box_id or "").startswith("pb_") else None,
         "items": [], "roster": {}}
    _kv("PUT", qid, q)
    return {"queue_id": qid, "owner_key": ok, "worker_key": wk, "expires_at": q["expires"],
            "note": "Keys are shown once. Give worker_key to your worker agents; keep owner_key. Send either as header X-Queue-Key."}


def enqueue(qid, key, title, payload=None, priority=0, not_before=None, repeat_every_minutes=None, max_attempts=3, bidding=False):
    q = _load(qid, key, "owner")
    if not title:
        raise LockerError(422, "title required")
    if payload is not None:
        import json
        if len(json.dumps(payload).encode()) > MAX_PAYLOAD:
            raise LockerError(413, f"payload over {MAX_PAYLOAD} bytes")
        if secret_scan.scan(payload)["verdict"] == "BLOCK":
            raise LockerError(422, "payload contains secrets; give workers a Permission Passport or Locker pointer instead")
    if sum(1 for i in q["items"] if i["state"] not in ("done", "dead")) >= MAX_ITEMS - 100:
        raise LockerError(409, "queue is full of open items")
    try:
        item = {"id": "wi_" + secrets.token_hex(8), "title": str(title)[:200], "payload": payload, "priority": int(priority or 0),
                "state": "bidding" if bidding else "queued", "attempts": 0, "max_attempts": max(1, min(int(max_attempts or 3), 10)),
                "not_before": int(not_before) if not_before else None,
                "repeat_every_minutes": max(1, int(repeat_every_minutes)) if repeat_every_minutes else None,
                "created": _now(), "bids": [] if bidding else None}
    except (TypeError, ValueError):
        raise LockerError(422, "priority, not_before, repeat_every_minutes, max_attempts must be integers")
    _event(item, "enqueued", "owner")
    q["items"].append(item)
    _save(qid, q)
    return {"item_id": item["id"], "state": item["state"]}


def claim(qid, key, worker_id):
    if not worker_id:
        raise LockerError(422, "worker_id required")
    q = _load(qid, key, "worker")
    now = _now()
    ready = [i for i in q["items"] if i["state"] == "queued" and (not i.get("not_before") or i["not_before"] <= now)]
    ready.sort(key=lambda i: (-i["priority"], i["created"]))
    w = q["roster"].setdefault(str(worker_id)[:80], {})
    w.update({"last_seen": now, "available": True})
    if not ready:
        _save(qid, q)
        return {"item": None, "note": "nothing ready to claim"}
    i = ready[0]
    i.update({"state": "leased", "holder": str(worker_id)[:80], "lease_until": now + q["lease_seconds"]})
    _event(i, "claimed", worker_id, resumed_from=i.get("checkpoint"))
    w["current"] = i["id"]
    _save(qid, q)
    return {"item": _public(i), "lease_seconds": q["lease_seconds"],
            "note": "a checkpoint is present: resume from it" if i.get("checkpoint") else None}


def _held(q, item_id, worker_id):
    i = _item(q, item_id)
    if i["state"] != "leased" or i.get("holder") != worker_id:
        raise LockerError(409, f"item is {i['state']} and held by {i.get('holder') or 'nobody'}, not {worker_id}")
    return i


def heartbeat(qid, key, worker_id, item_id=None, checkpoint=None, status=None):
    q = _load(qid, key, "worker")
    w = q["roster"].setdefault(str(worker_id)[:80], {})
    w.update({"last_seen": _now(), "available": True, "status": str(status or "")[:120] or w.get("status")})
    out = {"worker_id": worker_id, "roster_size": len(q["roster"])}
    if item_id:
        i = _held(q, item_id, worker_id)
        i["lease_until"] = _now() + q["lease_seconds"]
        if checkpoint is not None:
            if secret_scan.scan(checkpoint)["verdict"] == "BLOCK":
                raise LockerError(422, "checkpoint contains secrets; store it in a Locker and pass the locker_id")
            i["checkpoint"] = checkpoint if isinstance(checkpoint, (str, dict)) else str(checkpoint)
            _event(i, "checkpoint", worker_id)
        out.update({"item_id": item_id, "lease_until": i["lease_until"]})
    _save(qid, q)
    return out


def complete(qid, key, worker_id, item_id, result=None):
    q = _load(qid, key, "worker")
    i = _held(q, item_id, worker_id)
    if result is not None and secret_scan.scan(result)["verdict"] == "BLOCK":
        raise LockerError(422, "result contains secrets; not stored")
    i.update({"state": "done", "result": result, "holder": worker_id, "lease_until": None})
    _event(i, "completed", worker_id)
    nxt = None
    if i.get("repeat_every_minutes"):
        nxt = {**{k: i[k] for k in ("title", "payload", "priority", "max_attempts", "repeat_every_minutes")},
               "id": "wi_" + secrets.token_hex(8), "state": "queued", "attempts": 0, "created": _now(),
               "not_before": _now() + i["repeat_every_minutes"] * 60, "bids": None}
        _event(nxt, "scheduled_repeat", "scheduler", after=i["id"])
        q["items"].append(nxt)
    q["roster"].get(worker_id, {}).pop("current", None)
    _save(qid, q)
    return {"item_id": item_id, "state": "done", "next_scheduled": nxt and {"item_id": nxt["id"], "not_before": nxt["not_before"]}}


def fail(qid, key, worker_id, item_id, reason=None, retry=True):
    q = _load(qid, key, "worker")
    i = _held(q, item_id, worker_id)
    i["attempts"] = i.get("attempts", 0) + 1
    i.update({"holder": None, "lease_until": None})
    i["state"] = "queued" if retry and i["attempts"] < i["max_attempts"] else "dead"
    _event(i, "failed", worker_id, reason=str(reason or "")[:300])
    _save(qid, q)
    return {"item_id": item_id, "state": i["state"], "attempts": i["attempts"]}


def escalate(qid, key, worker_id, item_id, reason):
    q = _load(qid, key, "worker")
    i = _item(q, item_id)
    i["escalation"] = {"by": worker_id, "reason": str(reason or "")[:500], "at": _now()}
    prev = i["state"]
    i["state"] = "escalated"
    i.update({"holder": None, "lease_until": None})
    _event(i, "escalated", worker_id, reason=i["escalation"]["reason"], from_state=prev)
    sent = None
    if q.get("supervisor_box_id"):
        try:
            pobox.drop(q["supervisor_box_id"], {"type": "escalation", "queue_id": qid, "item_id": item_id, "title": i["title"],
                                                "reason": i["escalation"]["reason"], "by": worker_id},
                       sender=worker_id, subject="escalation: " + i["title"][:80])
            sent = True
        except LockerError as e:
            sent = False
            i["escalation"]["drop_error"] = e.msg
    _save(qid, q)
    return {"item_id": item_id, "state": "escalated", "supervisor_notified": sent}


def resolve(qid, key, item_id, action="requeue", note=None):
    q = _load(qid, key, "owner")
    i = _item(q, item_id)
    if action not in ("requeue", "close", "kill"):
        raise LockerError(422, "action must be requeue, close or kill")
    i["state"] = {"requeue": "queued", "close": "done", "kill": "dead"}[action]
    _event(i, "resolved_" + action, "owner", note=str(note or "")[:300])
    _save(qid, q)
    return {"item_id": item_id, "state": i["state"]}


def bid(qid, key, worker_id, item_id, price_usd=None, eta_minutes=None, note=None):
    q = _load(qid, key, "worker")
    i = _item(q, item_id)
    if i["state"] != "bidding":
        raise LockerError(409, f"item is {i['state']}, not open for bids")
    try:
        b = {"worker_id": str(worker_id)[:80], "price_usd": float(price_usd) if price_usd is not None else None,
             "eta_minutes": int(eta_minutes) if eta_minutes is not None else None, "note": str(note or "")[:200], "at": _now()}
    except (TypeError, ValueError):
        raise LockerError(422, "price_usd must be a number, eta_minutes an integer")
    i["bids"] = [x for x in i.get("bids") or [] if x["worker_id"] != b["worker_id"]] + [b]
    i["bids"] = i["bids"][-30:]
    _event(i, "bid", worker_id, price_usd=b["price_usd"], eta_minutes=b["eta_minutes"])
    _save(qid, q)
    return {"item_id": item_id, "bids": len(i["bids"])}


def award(qid, key, item_id, worker_id):
    q = _load(qid, key, "owner")
    i = _item(q, item_id)
    if i["state"] != "bidding":
        raise LockerError(409, f"item is {i['state']}, not in bidding")
    if not any(b["worker_id"] == worker_id for b in i.get("bids") or []):
        raise LockerError(422, "that worker didn't bid on this item")
    i.update({"state": "leased", "holder": worker_id, "lease_until": _now() + q["lease_seconds"]})
    _event(i, "awarded", "owner", to=worker_id)
    _save(qid, q)
    return {"item_id": item_id, "state": "leased", "holder": worker_id, "lease_until": i["lease_until"]}


def status(qid, key, item_id=None):
    q = _load(qid, key, "worker")
    _save(qid, q)  # persists sweep results
    if item_id:
        return {"item": _public(_item(q, item_id))}
    counts = {s: 0 for s in STATES}
    for i in q["items"]:
        counts[i["state"]] = counts.get(i["state"], 0) + 1
    now = _now()
    return {"queue_id": qid, "name": q["name"], "counts": counts,
            "responsible_now": [{"item_id": i["id"], "title": i["title"], "holder": i["holder"], "lease_left_s": i["lease_until"] - now}
                                for i in q["items"] if i["state"] == "leased"],
            "escalated": [{"item_id": i["id"], "title": i["title"], "reason": (i.get("escalation") or {}).get("reason")}
                          for i in q["items"] if i["state"] == "escalated"],
            "roster": [{"worker_id": k, **{x: v.get(x) for x in ("available", "last_seen", "current", "status")}} for k, v in q["roster"].items()],
            "scheduled": [{"item_id": i["id"], "title": i["title"], "not_before": i["not_before"]}
                          for i in q["items"] if i["state"] == "queued" and i.get("not_before") and i["not_before"] > now][:20]}
