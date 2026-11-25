"""OMENZ Checkpoint: milestone verdicts for agent jobs (bigger-bag lane, founder handoff 11-20 sec 7 'ESCROW / CHECKPOINT').

A job paid in tranches. Each milestone carries its own acceptance tests (same test types as contract/build) and deadline.
Submitting a milestone runs its tests and returns a signed PASS/FAIL with an escrow verdict for THAT tranche
(RELEASE / REFUND / RETRY) plus running totals. State lives in KV so a milestone can't be passed (or counted) twice.
OMENZ never holds funds: the payer releases or refunds per verdict; anyone can verify receipts offline (/v1/passport/key).
"""
import hashlib
import time

import contracts
from locker import LockerError, _kv

VERSION = "0.1.0"
MAX_MILESTONES = 12


def _key(cid):
    return f"checkpoint:{cid}"


def create(body):
    body = body if isinstance(body, dict) else {}
    ms = body.get("milestones")
    if not isinstance(ms, list) or not 1 <= len(ms) <= MAX_MILESTONES:
        raise LockerError(422, f"milestones: a list of 1-{MAX_MILESTONES} items, each {{name, amount_usd, acceptance:[tests], deadline_hours?}}")
    try:
        total = round(float(body.get("total_usd") or sum(float(m.get("amount_usd") or 0) for m in ms)), 6)
    except (TypeError, ValueError):
        raise LockerError(422, "total_usd / amount_usd must be numbers")
    now = int(time.time())
    clean = []
    for i, m in enumerate(ms):
        if not isinstance(m, dict) or not m.get("name"):
            raise LockerError(422, f"milestone {i}: needs a name")
        tests = m.get("acceptance") or []
        if not isinstance(tests, list) or not tests or any(not isinstance(t, dict) or t.get("type") not in contracts.TEST_TYPES for t in tests):
            raise LockerError(422, f"milestone {i}: acceptance must be a non-empty list of tests; types: {contracts.TEST_TYPES}")
        try:
            amt = round(float(m.get("amount_usd")), 6)
        except (TypeError, ValueError):
            raise LockerError(422, f"milestone {i}: amount_usd must be a number")
        dl = m.get("deadline_hours")
        clean.append({"i": i, "name": str(m["name"])[:120], "amount_usd": amt, "acceptance": tests[:20],
                      "deadline": now + int(float(dl) * 3600) if dl else None})
    if abs(sum(m["amount_usd"] for m in clean) - total) > 1e-6:
        raise LockerError(422, f"milestone amounts add up to {sum(m['amount_usd'] for m in clean)}, not total_usd {total}")
    cid = "ck_" + hashlib.sha256(f"{body.get('buyer')}{body.get('seller')}{now}{total}{len(clean)}".encode()).hexdigest()[:18]
    plan = {"schema": "omenz.checkpoint.v0", "checkpoint_id": cid, "buyer": str(body.get("buyer") or "")[:120],
            "seller": str(body.get("seller") or "")[:120], "job": str(body.get("job") or "")[:300], "total_usd": total,
            "milestones": clean, "iat": now, "issuer": "omenz.org"}
    st = {"plan": plan, "results": {}}
    try:
        import work_history
        if work_history.in_sandbox():
            st["ayne"] = True  # created in AYNE: milestone verdicts stay test-class in Work History
    except Exception:  # noqa: BLE001
        pass
    _kv("PUT", _key(cid), st)
    return {"checkpoint_id": cid, "plan": plan, "plan_token": contracts._sign(plan),
            "next": "Seller delivers each milestone: POST /v1/checkpoint/submit {checkpoint_id, milestone, delivered}. "
                    "OMENZ holds no funds; the buyer pays each tranche on RELEASE."}


def _summary(st):
    plan, res = st["plan"], st["results"]
    released = sum(m["amount_usd"] for m in plan["milestones"] if res.get(str(m["i"]), {}).get("escrow_verdict") == "RELEASE")
    refunded = sum(m["amount_usd"] for m in plan["milestones"] if res.get(str(m["i"]), {}).get("escrow_verdict") == "REFUND")
    rows = [{"milestone": m["i"], "name": m["name"], "amount_usd": m["amount_usd"],
             "state": (res.get(str(m["i"])) or {}).get("escrow_verdict", "PENDING"),
             "attempts": (res.get(str(m["i"])) or {}).get("attempts", 0)} for m in plan["milestones"]]
    done = all(r["state"] in ("RELEASE", "REFUND") for r in rows)
    return {"checkpoint_id": plan["checkpoint_id"], "total_usd": plan["total_usd"], "released_usd": round(released, 6),
            "refunded_usd": round(refunded, 6), "pending_usd": round(plan["total_usd"] - released - refunded, 6),
            "milestones": rows, "complete": done}


def submit(body, max_attempts=3):
    body = body if isinstance(body, dict) else {}
    cid = str(body.get("checkpoint_id") or "")
    st = _kv("GET", _key(cid)) if cid.startswith("ck_") else None
    if not st:
        raise LockerError(404, "unknown checkpoint_id")
    plan = st["plan"]
    sel = body.get("milestone")
    m = next((x for x in plan["milestones"] if str(x["i"]) == str(sel) or x["name"] == sel), None)
    if m is None:
        raise LockerError(422, "milestone: its index or name from the plan")
    prev = st["results"].get(str(m["i"])) or {}
    if prev.get("escrow_verdict") in ("RELEASE", "REFUND"):
        return {"already_decided": True, "milestone": m["i"], "escrow_verdict": prev["escrow_verdict"], "receipt_token": prev.get("receipt_token"),
                "summary": _summary(st)}
    d = body.get("delivered")
    if not isinstance(d, (dict, list)):
        raise LockerError(422, "delivered must be the milestone's JSON deliverable")
    d = d if isinstance(d, dict) else {"items": d}
    results = []
    for t in m["acceptance"]:
        ok, detail = contracts._run(t, d)
        results.append({"type": t["type"], "pass": bool(ok), "detail": detail})
    passed = all(r["pass"] for r in results)
    now = int(time.time())
    late = bool(m["deadline"] and now > m["deadline"])
    attempts = prev.get("attempts", 0) + 1
    escrow = "RELEASE" if passed and not late else "REFUND" if (late or attempts >= max_attempts) else "RETRY"
    rec = {"schema": "omenz.checkpoint-receipt.v0", "checkpoint_id": cid, "milestone": m["i"], "name": m["name"], "amount_usd": m["amount_usd"],
           "verdict": "PASS" if passed else "FAIL", "escrow_verdict": escrow, "late": late, "attempt": attempts,
           "tests": len(results), "passed_tests": sum(r["pass"] for r in results),
           "deliverable_sha256": hashlib.sha256(contracts._canon(d).encode()).hexdigest(), "at": now, "issuer": "omenz.org"}
    token = contracts._sign(rec)
    st["results"][str(m["i"])] = {"escrow_verdict": escrow, "attempts": attempts, "receipt_token": token}
    _kv("PUT", _key(cid), st)
    if escrow in ("RELEASE", "REFUND") and plan.get("seller"):
        try:
            contracts._record(plan["seller"], {"schema": "omenz.attestation.v0", "contract_id": cid, "seller": plan["seller"], "buyer": plan["buyer"],
                                               "verdict": rec["verdict"], "late": late, "tests": rec["tests"], "passed_tests": rec["passed_tests"],
                                               "at": now, "issuer": "omenz.org"})
        except Exception:
            pass
    if plan.get("seller"):
        try:  # 11-24 Work History: verified evidence. Never breaks submit.
            import work_history
            work_history.record(plan["seller"], {"RELEASE": "milestone_released", "REFUND": "milestone_refunded", "RETRY": "milestone_retry"}[escrow],
                                f"{cid}:{m['i']}", counterparty=plan.get("buyer"), test=bool(st.get("ayne")),
                                dedupe=f"{cid}:{m['i']}:{attempts if escrow == 'RETRY' else 'final'}")
        except Exception:  # noqa: BLE001
            pass
    return {"milestone": m["i"], "verdict": rec["verdict"], "escrow_verdict": escrow, "late": late, "results": results,
            "receipt": rec, "receipt_token": token, "summary": _summary(st),
            "note": {"RELEASE": "Buyer: pay this tranche now.", "REFUND": "Buyer: this tranche is not owed (failed or late).",
                     "RETRY": f"Seller: fix and resubmit ({max_attempts - attempts} attempt(s) left)."}[escrow]}


def status(cid):
    st = _kv("GET", _key(str(cid))) if str(cid).startswith("ck_") else None
    if not st:
        raise LockerError(404, "unknown checkpoint_id")
    return _summary(st)
