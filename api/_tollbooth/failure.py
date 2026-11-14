"""OMENZ Failure Receipt + Dead-Letter Queue: when an agent's job fails, write down WHY in a standard,
machine-readable form so the next agent (or a retry) doesn't start blind and doesn't repeat what was already tried.

Built on the Agent Locker (encrypted, key shown once) and the Agent PO Box (sealed drop = dead-letter queue).
- put: validate an omenz.failure.v0 record, secret-scan it (BLOCK = refused, not stored, not charged),
  store it in a Locker addressed to the next agent; optionally drop a sealed pointer into a PO Box you use as a DLQ.
Deterministic, no AI calls.
"""
import hashlib
import json

import locker
import pobox
import secret_scan
from locker import LockerError

SCHEMA = "omenz.failure.v0"
ERROR_CLASSES = ["timeout", "rate_limited", "auth_failed", "payment_failed", "payment_taken_no_result", "bad_input",
                 "upstream_error", "not_found", "blocked_by_bot_protection", "budget_exceeded", "policy_denied",
                 "tool_unavailable", "parse_error", "dependency_missing", "unknown"]
RETRYABLE = {"timeout", "rate_limited", "upstream_error", "tool_unavailable"}
TEXT = ("job_id", "objective", "failed_step", "error_detail", "suggested_next", "agent", "tool", "deadline")
LISTS = ("attempts", "receipts", "partial_artifacts", "dependencies")


def _clip(v, n):
    return str(v)[:n] if v is not None else None


def normalize(data):
    if not isinstance(data, dict):
        raise LockerError(400, "JSON object required")
    rec = {"schema": SCHEMA}
    for k in TEXT:
        if data.get(k) not in (None, ""):
            rec[k] = _clip(data[k], 2000 if k == "error_detail" else 400)
    for k in ("objective", "failed_step"):
        if k not in rec:
            raise LockerError(422, f"{k} is required")
    ec = str(data.get("error_class") or "unknown").strip().lower()
    warnings = []
    if ec not in ERROR_CLASSES:
        warnings.append(f"error_class '{ec}' not in the standard list; recorded as 'unknown'")
        rec["error_class_given"] = _clip(ec, 60)
        ec = "unknown"
    rec["error_class"] = ec
    rec["retryable"] = bool(data["retryable"]) if isinstance(data.get("retryable"), bool) else ec in RETRYABLE
    try:
        rec["spent_usd"] = round(float(data.get("spent_usd") or 0), 6)
    except (TypeError, ValueError):
        raise LockerError(422, "spent_usd must be a number")
    if rec["spent_usd"] < 0:
        raise LockerError(422, "spent_usd must not be negative")
    for k in LISTS:
        v = data.get(k)
        if v is None:
            continue
        if not isinstance(v, list):
            raise LockerError(422, f"{k} must be a list")
        rec[k] = v[:25]
    if ec == "payment_taken_no_result" and not rec.get("receipts"):
        warnings.append("payment_taken_no_result without receipts: add receipt ids or tx hashes so a refund can be argued")
    if not rec.get("attempts"):
        warnings.append("no attempts listed: the next agent can't tell what was already tried")
    raw = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    if len(raw) > 32 * 1024:
        raise LockerError(413, f"failure record is {len(raw)} bytes; max 32768")
    return rec, warnings, raw


def put(data, to=None, frm=None, dlq_box_id=None, ttl_days=14):
    rec, warnings, raw = normalize(data)
    scan = secret_scan.scan(rec)
    if scan["verdict"] == "BLOCK":
        raise LockerError(422, "failure record contains secrets (" + ", ".join(sorted(scan["counts"])) +
                          "); remove them and resend. Nothing was stored.")
    if scan["verdict"] == "REVIEW":
        warnings.append("possible sensitive data: " + ", ".join(sorted(scan["counts"])))
    stored = locker.put(rec, ttl_days, to=to, frm=frm)
    out = {**stored, "schema": SCHEMA, "error_class": rec["error_class"], "retryable": rec["retryable"],
           "sha256": hashlib.sha256(raw).hexdigest(), "warnings": warnings, "dlq": None}
    if dlq_box_id:
        try:
            pobox.drop(dlq_box_id, {"type": "dead_letter", "schema": SCHEMA, "locker_id": stored["locker_id"],
                                    "access_key": stored["access_key"], "objective": rec["objective"][:200],
                                    "failed_step": rec["failed_step"][:200], "error_class": rec["error_class"],
                                    "retryable": rec["retryable"], "job_id": rec.get("job_id")},
                       sender=frm or "failure-receipt", subject="dead letter: " + rec["error_class"])
            out["dlq"] = {"box_id": dlq_box_id, "dropped": True}
        except LockerError as e:
            out["dlq"] = {"box_id": dlq_box_id, "dropped": False, "reason": e.msg}
    return out
