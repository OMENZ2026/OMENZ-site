"""OMENZ Permission Passport: job-scoped, signed, expiring permission tickets for agents.

Signal: Nate B. Jones (2026-11-10): attackers pivoted through a company's internal AI agent across privilege
boundaries. Fix pattern: an agent carries only the permissions THIS job needs, for a short time, and every tool can
check them. Our own practice (keys never in handoffs, per-item approvals) turned outward.

- issue(scope)  -> token (Ed25519-signed, base64url payload.signature). Max 7 days.
- check(token, action) -> ALLOW / DENY with reasons; spend left. Anyone can also verify offline with key().
Nothing is stored. The passport carries NO secrets: it says what is allowed, it doesn't grant credentials.
Deterministic, no AI calls.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION = "0.1.0"
SCHEMA = "omenz.passport.v0"
MAX_MINUTES = 7 * 24 * 60


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key():
    seed = os.environ.get("PASSPORT_SIGNING_SEED")
    if seed:
        raw = hashlib.sha256(("omenz-passport|" + seed).encode()).digest()
    else:  # derived from the deployment's storage secret; rotating it retires old passports (they're short-lived anyway)
        base = os.environ.get("APIFY_LOG_TOKEN", "")
        if not base:
            raise RuntimeError("signing key not configured")
        raw = hashlib.sha256(("omenz-passport-v0|" + base).encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(raw)


def key():
    pub = _key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {"schema": SCHEMA, "alg": "Ed25519", "public_key_b64url": _b64(pub), "kid": hashlib.sha256(pub).hexdigest()[:16],
            "verify": "signature = Ed25519 over the ASCII payload part (before the dot) of the token"}


def _host(u):
    u = str(u or "").strip().lower()
    if "://" not in u:
        u = "https://" + u
    return (urllib.parse.urlparse(u).hostname or "").removeprefix("www.")


def _list(v, n=50):
    return sorted({str(x).strip().lower() for x in (v or []) if str(x).strip()})[:n] if isinstance(v, list) else []


def issue(scope):
    if not isinstance(scope, dict):
        return {"error": "scope object required"}
    try:
        minutes = int(scope.get("expires_in_minutes") or 60)
        spend = float(scope["max_spend_usd"]) if scope.get("max_spend_usd") is not None else None
    except (TypeError, ValueError):
        return {"error": "expires_in_minutes must be an integer and max_spend_usd a number"}
    if minutes < 1 or minutes > MAX_MINUTES:
        return {"error": f"expires_in_minutes must be 1..{MAX_MINUTES}"}
    if spend is not None and spend < 0:
        return {"error": "max_spend_usd must not be negative"}
    tools, hosts = _list(scope.get("allow_tools")), [_host(h) for h in _list(scope.get("allow_hosts"))]
    if not (tools or hosts or spend is not None):
        return {"error": "a passport must limit something: allow_tools, allow_hosts or max_spend_usd"}
    now = int(time.time())
    payload = {"schema": SCHEMA, "jti": "pp_" + secrets.token_hex(10), "iat": now, "exp": now + minutes * 60,
               "agent": str(scope.get("agent") or "")[:80], "job_id": str(scope.get("job_id") or "")[:80],
               "purpose": str(scope.get("purpose") or "")[:200], "allow_tools": tools, "allow_hosts": hosts,
               "deny_hosts": [_host(h) for h in _list(scope.get("deny_hosts"))], "max_spend_usd": spend,
               "issuer": "omenz.org"}
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = _b64(_key().sign(body.encode()))
    return {"token": body + "." + sig, "passport": payload, "kid": key()["kid"],
            "note": "Carries permissions, not credentials. Anyone can verify it offline with GET /v1/passport/key."}


def check(token, action=None):
    action = action or {}
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stored": False}
    try:
        body, sig = str(token).split(".")
        _key().public_key().verify(_unb64(sig), body.encode())
        p = json.loads(_unb64(body))
    except Exception:
        return {**out, "decision": "DENY", "valid": False, "reasons": ["passport signature invalid or token malformed"]}
    if p.get("schema") != SCHEMA:
        return {**out, "decision": "DENY", "valid": False, "reasons": ["unknown passport schema"]}
    now = int(time.time())
    deny, ok = [], []
    if now >= p["exp"]:
        deny.append("passport expired")
    tool = str(action.get("tool") or "").strip().lower()
    if tool:
        if p["allow_tools"] and tool not in p["allow_tools"]:
            deny.append(f"tool '{tool}' not allowed by this passport")
        else:
            ok.append("tool")
    elif p["allow_tools"]:
        deny.append("passport limits tools but no action.tool was given")
    host = _host(action.get("url") or action.get("host")) if (action.get("url") or action.get("host")) else ""
    if host:
        hit = lambda h: host == h or host.endswith("." + h)
        if any(hit(h) for h in p.get("deny_hosts", [])):
            deny.append(f"host {host} is explicitly denied")
        elif p["allow_hosts"] and not any(hit(h) for h in p["allow_hosts"]):
            deny.append(f"host {host} not allowed by this passport")
        else:
            ok.append("host")
    elif p["allow_hosts"]:
        deny.append("passport limits hosts but no action.url/host was given")
    left = None
    if p.get("max_spend_usd") is not None:
        try:
            amt = float(action.get("amount_usd") or 0)
            spent = float(action.get("spent_so_far_usd") or 0)
        except (TypeError, ValueError):
            return {**out, "decision": "DENY", "valid": True, "reasons": ["amount_usd / spent_so_far_usd must be numbers"]}
        left = round(p["max_spend_usd"] - spent, 6)
        if amt > left + 1e-12:
            deny.append(f"${amt:g} would exceed the passport's spend limit (${max(left, 0):g} left)")
        else:
            ok.append("spend")
    return {**out, "decision": "DENY" if deny else "ALLOW", "valid": True, "reasons": deny or ["all checks passed"],
            "passed": ok, "jti": p["jti"], "agent": p["agent"], "job_id": p["job_id"], "expires_at": p["exp"],
            "seconds_left": max(0, p["exp"] - now), "spend_left_usd": left}
