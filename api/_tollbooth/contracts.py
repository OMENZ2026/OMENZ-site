"""OMENZ Agent Contracts: terms two agents can hold each other to, checked by a neutral party.

- build(terms)              A2A Contract Builder: deliverable, deterministic acceptance tests, max spend, deadline,
                            parties -> signed contract token (Ed25519, OMENZ key at /v1/passport/key).
- accept(token, delivered)  Acceptance Test as a Service: run the contract's tests on what was delivered -> PASS/FAIL per
                            test, overall verdict, escrow verdict (RELEASE / REFUND / WAIT) and a signed attestation.
                            OMENZ never holds funds: escrow here = the conditions + a neutral verdict the payer acts on.
- attestations feed Reputation Receipts: per-seller history of signed PASS/FAIL results (reputation(agent)).
- bundle(items)             Machine Evidence Bundle: package receipts, ledger heads, attestations, claims into one
                            signed, hash-listed bundle anyone can verify offline.
Tests (deterministic): required_fields, field_types, regex, min_items, max_bytes, equals, url_alive, claim_evidence.
"""
import base64
import hashlib
import json
import re
import secrets
import time

import passport
from locker import LockerError, _kv

VERSION = "0.1.0"
TEST_TYPES = ["required_fields", "field_types", "regex", "min_items", "max_bytes", "equals", "url_alive", "claim_evidence"]
TYPES = {"string": str, "number": (int, float), "integer": int, "boolean": bool, "object": dict, "array": list}


def _canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _sign(obj):
    body = _b64(_canon(obj).encode())
    return body + "." + _b64(passport._key().sign(body.encode()))


def _open(token):
    try:
        body, sig = str(token).split(".")
        passport._key().public_key().verify(passport._unb64(sig), body.encode())
        return json.loads(passport._unb64(body))
    except Exception:
        return None


def _get(d, path):
    cur = d
    for p in str(path).split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and int(p) < len(cur):
            cur = cur[int(p)]
        else:
            return None, False
    return cur, True


def build(terms):
    if not isinstance(terms, dict):
        raise LockerError(422, "terms object required")
    deliverable = str(terms.get("deliverable") or "").strip()
    tests = terms.get("acceptance") or []
    if not deliverable or not isinstance(tests, list) or not tests:
        raise LockerError(422, "deliverable (text) and acceptance (list of tests) are required")
    for t in tests:
        if not isinstance(t, dict) or t.get("type") not in TEST_TYPES:
            raise LockerError(422, f"each acceptance test needs type in {TEST_TYPES}")
    try:
        max_spend = float(terms["max_spend_usd"]) if terms.get("max_spend_usd") is not None else None
        deadline = int(terms["deadline"]) if terms.get("deadline") else None
    except (TypeError, ValueError):
        raise LockerError(422, "max_spend_usd must be a number, deadline a unix timestamp")
    c = {"schema": "omenz.contract.v0", "contract_id": "ct_" + secrets.token_hex(10), "issued": int(time.time()),
         "buyer": str(terms.get("buyer") or "")[:80], "seller": str(terms.get("seller") or "")[:80],
         "deliverable": deliverable[:1000], "acceptance": tests[:20], "max_spend_usd": max_spend, "deadline": deadline,
         "payment": str(terms.get("payment") or "")[:200], "issuer": "omenz.org"}
    return {"contract": c, "token": _sign(c), "kid": passport.key()["kid"],
            "note": "Both parties keep the token. Deliveries are checked with POST /v1/contract/accept."}


def _run(t, d):
    typ = t["type"]
    try:
        if typ == "required_fields":
            miss = [f for f in t.get("fields", []) if _get(d, f)[1] is False or _get(d, f)[0] in (None, "", [], {})]
            return not miss, f"missing: {miss}" if miss else "all present"
        if typ == "field_types":
            bad = [f for f, ty in (t.get("types") or {}).items()
                   if not (_get(d, f)[1] and isinstance(_get(d, f)[0], TYPES.get(ty, object)) and not (ty in ("number", "integer") and isinstance(_get(d, f)[0], bool)))]
            return not bad, f"wrong/missing type: {bad}" if bad else "types ok"
        if typ == "regex":
            v, ok = _get(d, t.get("field"))
            good = ok and isinstance(v, str) and re.fullmatch(t.get("pattern", ""), v) is not None
            return good, "matches" if good else f"{t.get('field')} doesn't match"
        if typ == "min_items":
            v, ok = _get(d, t.get("field"))
            n = len(v) if ok and isinstance(v, (list, dict)) else 0
            return n >= int(t.get("n", 1)), f"{n} items (need {t.get('n', 1)})"
        if typ == "max_bytes":
            n = len(_canon(d).encode())
            return n <= int(t.get("n", 0)), f"{n} bytes (max {t.get('n')})"
        if typ == "equals":
            v, ok = _get(d, t.get("field"))
            return ok and v == t.get("value"), f"{t.get('field')} = {str(v)[:80]!r}"
        if typ == "url_alive":
            import x402_probe
            v, ok = _get(d, t.get("field"))
            if not ok or not isinstance(v, str):
                return False, "no url"
            a = x402_probe.alive(v)
            return a["verdict"] in ("up", "paywalled"), f"{a['verdict']}"
        if typ == "claim_evidence":
            import claim_evidence
            cl, ok1 = _get(d, t.get("claim_field"))
            u, ok2 = _get(d, t.get("url_field"))
            if not (ok1 and ok2):
                return False, "claim or url missing"
            r = claim_evidence.check(str(cl), str(u))
            return r["verdict"] == "SUPPORTED", r["verdict"]
    except Exception as e:
        return False, f"test error: {type(e).__name__}"
    return False, "unknown test"


def accept(token, delivered, record=True):
    c = _open(token)
    if not c or c.get("schema") != "omenz.contract.v0":
        raise LockerError(422, "contract token invalid or forged")
    if not isinstance(delivered, (dict, list)):
        raise LockerError(422, "delivered must be the JSON deliverable")
    d = delivered if isinstance(delivered, dict) else {"items": delivered}
    results = []
    for t in c["acceptance"]:
        ok, detail = _run(t, d)
        results.append({"type": t["type"], "pass": bool(ok), "detail": detail})
    passed = all(r["pass"] for r in results)
    now = int(time.time())
    late = bool(c.get("deadline") and now > c["deadline"])
    escrow = "RELEASE" if passed and not late else "REFUND" if (late or not passed) else "WAIT"
    att = {"schema": "omenz.attestation.v0", "contract_id": c["contract_id"], "seller": c["seller"], "buyer": c["buyer"],
           "verdict": "PASS" if passed else "FAIL", "late": late, "tests": len(results), "passed_tests": sum(r["pass"] for r in results),
           "deliverable_sha256": hashlib.sha256(_canon(d).encode()).hexdigest(), "at": now, "issuer": "omenz.org"}
    att_token = _sign(att)
    if record and c["seller"]:
        _record(c["seller"], att)
    return {"verdict": att["verdict"], "escrow_verdict": escrow, "late": late, "results": results, "attestation": att,
            "attestation_token": att_token,
            "note": "OMENZ holds no funds: the payer releases or refunds per escrow_verdict. Verify the attestation offline with /v1/passport/key."}


def _rkey(agent):
    return "rep_" + hashlib.sha256(("omenz-rep|" + agent.lower()).encode()).hexdigest()[:32]


def _record(agent, att):
    k = _rkey(agent)
    rec = _kv("GET", k) or {"agent": agent, "items": []}
    rec["items"] = (rec["items"] + [{x: att[x] for x in ("contract_id", "verdict", "late", "tests", "passed_tests", "at", "buyer")}])[-200:]
    _kv("PUT", k, rec)


def reputation(agent):
    if not agent:
        raise LockerError(422, "agent required")
    rec = _kv("GET", _rkey(agent)) or {"agent": agent, "items": []}
    it = rec["items"]
    p = sum(1 for i in it if i["verdict"] == "PASS")
    buyers = len({i["buyer"] for i in it if i.get("buyer")})
    return {"agent": agent, "jobs_checked": len(it), "passed": p, "failed": len(it) - p, "late": sum(1 for i in it if i.get("late")),
            "pass_rate": round(p / len(it), 3) if it else None, "distinct_buyers": buyers, "recent": it[-20:][::-1],
            "note": "Only jobs checked by OMENZ Acceptance Test count. Few distinct buyers = weak evidence (could be self-dealing)."}


def bundle(items, label=None):
    if not isinstance(items, list) or not items or len(items) > 100:
        raise LockerError(422, "items: list of 1-100 objects (receipts, ledger heads, attestation tokens, claims, ...)")
    listed = [{"i": n, "sha256": hashlib.sha256(_canon(x).encode()).hexdigest(), "kind": (x.get("kind") if isinstance(x, dict) else None) or type(x).__name__}
              for n, x in enumerate(items)]
    b = {"schema": "omenz.evidence-bundle.v0", "bundle_id": "eb_" + secrets.token_hex(10), "label": str(label or "")[:200],
         "created": int(time.time()), "items": listed, "root": hashlib.sha256("".join(x["sha256"] for x in listed).encode()).hexdigest(),
         "issuer": "omenz.org"}
    return {"bundle": b, "token": _sign(b), "items": items,
            "verify": "check each item's sha256 against bundle.items, then the Ed25519 signature on the token with /v1/passport/key"}
