"""OMENZ Handoff Packager v0: give a job to another agent with only what it needs.
Founder "Build all" 2026-11-11 (agent utilities family #2). Built on the Agent Locker.

pack: send your packet plus `include` (fields to pass on) and `required` (fields the receiver must get).
- Drops everything not in `include` (if given), so your full context never leaves.
- Refuses (422, no charge) if any required field is missing or empty, and lists what's missing.
- Stores the result in a Locker addressed `to` the receiving agent; returns locker_id + access_key to hand over,
  plus a manifest (fields, bytes, sha256) the receiver can check.
Standard handoff fields (omenz.handoff.v0): objective, context_summary, decisions, open_items, constraints,
prohibited, permissions, artifacts, next_action, deadline.
"""
import hashlib
import json

import locker
from locker import LockerError

STANDARD = ["objective", "context_summary", "decisions", "open_items", "constraints", "prohibited", "permissions",
            "artifacts", "next_action", "deadline"]
DEFAULT_REQUIRED = ["objective", "next_action"]


def _empty(v):
    return v is None or v == "" or v == [] or v == {}


def pack(packet, include=None, required=None, to=None, frm=None, ttl_days=7):
    if not isinstance(packet, dict) or not packet:
        raise LockerError(400, "packet must be a non-empty JSON object")
    req = required if isinstance(required, list) and required else DEFAULT_REQUIRED
    missing = [f for f in req if _empty(packet.get(f))]
    if missing:
        raise LockerError(422, "handoff incomplete; missing required: " + ", ".join(missing))
    keep = include if isinstance(include, list) and include else list(packet.keys())
    keep = list(dict.fromkeys(list(keep) + list(req)))
    out = {k: packet[k] for k in keep if k in packet}
    out["_handoff"] = {"schema": "omenz.handoff.v0", "from": (frm or "")[:80], "to": (to or "")[:80],
                       "dropped_fields": sorted(set(packet) - set(out))}
    raw = json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    stored = locker.put(out, ttl_days, to=to, frm=frm)
    return {**stored, "manifest": {"schema": "omenz.handoff.v0", "fields": sorted(k for k in out if k != "_handoff"),
                                   "dropped": out["_handoff"]["dropped_fields"], "bytes": len(raw),
                                   "sha256": hashlib.sha256(raw).hexdigest(),
                                   "nonstandard_fields": sorted(k for k in out if k not in STANDARD and k != "_handoff")}}
