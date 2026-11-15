"""Coinbase CDP facilitator auth (minimal, no cdp-sdk: that package pulls web3 + solana, too heavy for Vercel).

Why (2026-11-15): Coinbase's agents (Coinbase for Agents, Agentic Wallet MCP) discover paid tools in the CDP Bazaar,
and a resource is indexed there only after a settlement through the CDP Facilitator (docs.cdp.coinbase.com/x402/bazaar).
OMENZ settled through PayAI, so our 67 routes were invisible to Coinbase's agents.

Same JWT shape as cdp-sdk's cdp.auth.utils.jwt.generate_jwt (ES256 for EC PEM keys, EdDSA for base64 Ed25519 keys):
header {alg, kid, typ, nonce}; claims {sub, iss:"cdp", nbf, exp(+120s), uris:["METHOD host/path"]}.
Keys come ONLY from env vars the founder sets in Vercel (CDP_API_KEY_ID / CDP_API_KEY_SECRET). Never logged.
"""
import base64
import json
import os
import secrets
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

HOST = "api.cdp.coinbase.com"
ROUTE = "/platform/v2/x402"
URL = "https://" + HOST + ROUTE


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _key(secret):
    s = secret.strip().replace("\\n", "\n")
    if "BEGIN" in s:
        return serialization.load_pem_private_key(s.encode(), password=None)
    raw = base64.b64decode(s)
    if len(raw) not in (32, 64):
        raise ValueError("CDP key secret is neither a PEM EC key nor a base64 Ed25519 key")
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32])


def jwt(key_id, secret, method, path):
    k = _key(secret)
    alg = "ES256" if isinstance(k, ec.EllipticCurvePrivateKey) else "EdDSA"
    now = int(time.time())
    head = {"alg": alg, "kid": key_id, "typ": "JWT", "nonce": secrets.token_hex(8)}
    claims = {"sub": key_id, "iss": "cdp", "nbf": now, "exp": now + 120, "uris": [f"{method} {HOST}{path}"]}
    msg = (_b64(json.dumps(head, separators=(",", ":")).encode()) + "." +
           _b64(json.dumps(claims, separators=(",", ":")).encode())).encode()
    if alg == "ES256":
        r, s = decode_dss_signature(k.sign(msg, ec.ECDSA(hashes.SHA256())))
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        sig = k.sign(msg)
    return msg.decode() + "." + _b64(sig)


def configured():
    return bool(os.environ.get("CDP_API_KEY_ID") and os.environ.get("CDP_API_KEY_SECRET"))


def create_headers():
    kid, sec = os.environ["CDP_API_KEY_ID"], os.environ["CDP_API_KEY_SECRET"]
    corr = {"Correlation-Context": "sdk_language=python,source=x402,source_version=2.0.0"}

    def h(method, op):
        return {"Content-Type": "application/json", "Authorization": "Bearer " + jwt(kid, sec, method, f"{ROUTE}/{op}"), **corr}

    return {"verify": h("POST", "verify"), "settle": h("POST", "settle"), "supported": h("GET", "supported"), "list": corr}
