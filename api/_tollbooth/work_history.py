"""OMENZ Work History: an agent's portable, signed work record across OMENZ tools (founder 11-24: "portable work receipts";
"do not create reputation from unsupported claims; distinguish reported vs verified vs test-only vs paid-use vs failed vs unknown").

record(agent, kind, ...) appends one event to ONE KV record per agent ("wh_" + sha256(agent)[:24]): the last 200 events plus
all-time counters. Hooks live in workforce (queue), contracts (acceptance) and checkpoint (milestones); every hook is wrapped
so a history failure never breaks the job call.

Evidence classes (each event has exactly one):
- verified: OMENZ itself evaluated the outcome (contract/accept and checkpoint/submit acceptance tests).
- reported: the worker or queue owner said so through the queue (claim/complete/fail/escalate/rejoin). OMENZ did not check the work.
- test:     AYNE sandbox calls, or objects created in AYNE. Never counted in any rate.
Channel (how the call arrived): paid (x402 route), ayne (sandbox), direct (in-process / unknown).
Privacy: object ids and counterparties are stored only as salted hashes; no queue keys, payloads, results, reasons or secrets.
v0 limit: last-write-wins if the same agent's record is written concurrently from two places.
"""
import contextlib
import contextvars
import hashlib
import threading
import time

from locker import LockerError, _kv

VERSION = "0.1.0"
SCHEMA = "omenz.work-history.v0"
MAX_EVENTS, MAX_SEEN, MAX_CPS = 200, 600, 200
WRITE_BUDGET_S = 2.5  # a job call never waits longer than this on history storage

KINDS = {  # kind -> (source, evidence class when live)
    "job_claimed": ("queue", "reported"), "job_completed": ("queue", "reported"), "job_failed": ("queue", "reported"),
    "job_escalated": ("queue", "reported"), "rejoined": ("queue", "reported"), "stand_down": ("queue", "reported"),
    "late_contribution": ("queue", "reported"),
    "milestone_released": ("checkpoint", "verified"), "milestone_refunded": ("checkpoint", "verified"),
    "milestone_retry": ("checkpoint", "verified"),
    "contract_pass": ("contract", "verified"), "contract_fail": ("contract", "verified"),
}
VERIFIED_OK, VERIFIED_BAD = ("contract_pass", "milestone_released"), ("contract_fail", "milestone_refunded")

_CHANNEL = contextvars.ContextVar("omenz_work_history_channel", default="direct")


@contextlib.contextmanager
def channel(name):
    """Route handlers wrap job calls: `with work_history.channel("ayne" if request.state.ayne else "paid"):`."""
    tok = _CHANNEL.set(name if name in ("paid", "ayne", "direct") else "direct")
    try:
        yield
    finally:
        _CHANNEL.reset(tok)


def in_sandbox():
    return _CHANNEL.get() == "ayne"


def _norm(agent):
    a = str(agent or "").strip()[:120]
    if not a:
        raise LockerError(422, "agent required: a worker id, contract/checkpoint seller name, or 0x wallet")
    return a


def _rkey(agent):
    return "wh_" + hashlib.sha256(("omenz-wh|" + _norm(agent).lower()).encode()).hexdigest()[:24]


def _hid(x):
    return hashlib.sha256(("omenz-wh-obj|" + str(x)).encode()).hexdigest()[:16] if x else None


def _write(agent, kind, object_id, counterparty, test, dedupe, ch, now):
    k = _rkey(agent)
    rec = _kv("GET", k) or {"v": 0, "agent": _norm(agent), "first_seen": now, "events": [], "counts": {}, "channels": {},
                            "seen": [], "cps": {}, "events_total": 0}
    source, cls = KINDS[kind]
    if test or ch == "ayne":
        cls = "test"
    if dedupe:
        d = _hid(f"{kind}|{cls}|{dedupe}")
        if d in rec["seen"]:
            return False  # same outcome for the same object is counted once (re-running accept can't inflate a record)
        rec["seen"] = (rec["seen"] + [d])[-MAX_SEEN:]
    cp = _hid(counterparty)
    ev = {"at": now, "kind": kind, "source": source, "object": _hid(object_id), "evidence_class": cls, "channel": ch}
    if cp:
        ev["counterparty"] = cp
        lst = rec["cps"].setdefault(cls, [])
        if cp not in lst:
            rec["cps"][cls] = (lst + [cp])[-MAX_CPS:]
    rec["events"] = (rec["events"] + [ev])[-MAX_EVENTS:]
    c = rec["counts"].setdefault(kind, {})
    c[cls] = c.get(cls, 0) + 1
    rec["channels"][ch] = rec["channels"].get(ch, 0) + 1
    rec["events_total"] = rec.get("events_total", 0) + 1
    rec["last_seen"] = now
    _kv("PUT", k, rec)
    return True


def record(agent, kind, object_id=None, counterparty=None, test=False, dedupe=None):
    """Append one event. Never raises (returns True/False/None); bounded to WRITE_BUDGET_S so storage trouble can't stall a job."""
    try:
        if kind not in KINDS or not str(agent or "").strip():
            return None
        ch, now, out = _CHANNEL.get(), int(time.time()), {}

        def run():
            try:
                out["r"] = _write(agent, kind, object_id, counterparty, bool(test), dedupe, ch, now)
            except Exception as e:  # noqa: BLE001
                out["e"] = type(e).__name__

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(WRITE_BUDGET_S)
        return out.get("r")
    except Exception:  # noqa: BLE001
        return None


def _rate(ok, bad):
    return round(ok / (ok + bad), 3) if ok + bad else None


def history(agent):
    import contracts
    import passport
    agent = _norm(agent)
    rec = _kv("GET", _rkey(agent))
    now = int(time.time())
    if not rec:
        s = {"schema": SCHEMA, "issuer": "omenz.org", "agent": agent, "status": "NO_HISTORY", "as_of": now}
        return {**s, "token": contracts._sign(s), "kid": passport.key()["kid"],
                "note": "OMENZ has no recorded work for this agent. Unknown is not bad: it only means no evidence either way. "
                        "Ids are matched exactly (case-insensitive); try the worker_id, contract/checkpoint seller name or wallet it uses."}
    cnt = rec.get("counts", {})

    def n(kind, cls):
        return cnt.get(kind, {}).get(cls, 0)

    by_class = {"verified": 0, "reported": 0, "test": 0}
    for v in cnt.values():
        for cls, x in v.items():
            by_class[cls] = by_class.get(cls, 0) + x
    v_ok, v_bad = sum(n(k, "verified") for k in VERIFIED_OK), sum(n(k, "verified") for k in VERIFIED_BAD)
    r_ok, r_bad = n("job_completed", "reported"), n("job_failed", "reported")
    cps = rec.get("cps", {})
    v_cp, r_cp = len(cps.get("verified", [])), len(cps.get("reported", []))
    warnings = []
    if v_ok + v_bad < 5:
        warnings.append(f"fewer than 5 verified jobs ({v_ok + v_bad}): weak evidence")
    if v_ok + v_bad and v_cp < 2:
        warnings.append("verified jobs come from fewer than 2 distinct counterparties: could be self-dealing")
    if by_class["reported"] and not (v_ok + v_bad):
        warnings.append("only reported events: the worker/owner's own word through the queue; OMENZ did not check the work")
    if r_ok + r_bad and r_ok + r_bad < 5:
        warnings.append(f"fewer than 5 reported job outcomes ({r_ok + r_bad}): weak evidence")
    if by_class["test"] and not (by_class["verified"] or by_class["reported"]):
        warnings.append("test-only: every event came from the AYNE sandbox; nothing live yet")
    status = ("HAS_VERIFIED" if by_class["verified"] else "REPORTED_ONLY" if by_class["reported"] else "TEST_ONLY")
    recent = rec.get("events", [])[-20:][::-1]
    s = {"schema": SCHEMA, "issuer": "omenz.org", "agent": rec.get("agent") or agent, "status": status, "as_of": now,
         "first_seen": rec.get("first_seen"), "last_seen": rec.get("last_seen"),
         "events_total": rec.get("events_total", 0), "events_kept": len(rec.get("events", [])),
         "counts_by_kind": {k: dict(v) for k, v in sorted(cnt.items())}, "counts_by_class": by_class,
         "counts_by_channel": dict(rec.get("channels", {})),
         "verified": {"passed": v_ok, "failed": v_bad, "sample_size": v_ok + v_bad, "completion_rate": _rate(v_ok, v_bad),
                      "retries": n("milestone_retry", "verified"), "distinct_counterparties": v_cp},
         "reported": {"claimed": n("job_claimed", "reported"), "completed": r_ok, "failed": r_bad,
                      "escalated": n("job_escalated", "reported"), "rejoined": n("rejoined", "reported"),
                      "stood_down": n("stand_down", "reported"), "late_contributions": n("late_contribution", "reported"),
                      "sample_size": r_ok + r_bad, "completion_rate": _rate(r_ok, r_bad), "distinct_counterparties": r_cp},
         "paid_use_events": rec.get("channels", {}).get("paid", 0),
         "warnings": warnings,
         "recent_sha256": hashlib.sha256(contracts._canon(recent).encode()).hexdigest()}
    return {**s, "recent": recent, "token": contracts._sign(s), "kid": passport.key()["kid"],
            "evidence_ladder": {"verified": "OMENZ ran the acceptance tests itself (contract/accept, checkpoint/submit)",
                                "reported": "the worker or queue owner said so via the queue; not checked by OMENZ",
                                "test": "AYNE sandbox; excluded from every rate",
                                "paid_use": "events that arrived through a paid x402 call (counts_by_channel.paid)",
                                "failed": "contract_fail / milestone_refunded (verified) and job_failed (reported)",
                                "unknown": "NO_HISTORY: no evidence either way"},
            "how_rates_work": "verified.completion_rate = (contract_pass + milestone_released) / (those + contract_fail + milestone_refunded); "
                              "reported.completion_rate = job_completed / (job_completed + job_failed). Test events never count. "
                              "The same contract/milestone outcome is counted once.",
            "verify": "token = base64url(canonical summary JSON).Ed25519 signature; key at /v1/passport/key. recent_sha256 binds the recent list. "
                      "Object ids and counterparties are salted hashes; worker ids are self-chosen labels."}
