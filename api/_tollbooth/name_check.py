"""OMENZ Name Resolve: which wallet does this name really point to, and does it match? (2026-11-22)

Evidence (11-22 category scan): ENS/name services 715 paying wallets. The agent risk is paying the wrong address:
a typo'd or look-alike name, a stale name, or an address someone pasted. Deterministic, on-chain only:
  *.base.eth  -> Base registry (Basenames)      other names -> Ethereum ENS registry (public RPC)
  address     -> reverse name (ENS primary name, forward-verified; Basename primary name on Base, forward-verified)
Extras: expected_address match, contract vs wallet on Base, OFAC screen of the resolved address, non-ASCII look-alike warning.

  MATCH / MISMATCH  when expected_address is given
  RESOLVED / NOT_FOUND / OFFCHAIN_UNSUPPORTED / SANCTIONED otherwise
"""
import json
import re
import time
import urllib.request

import wallet

VERSION = "0.1.0"
ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
BASE_REGISTRY = "0xb94704422c2a1e396835a571837aa5ae53285a95"
ETH_RPCS = ["https://ethereum-rpc.publicnode.com", "https://eth.llamarpc.com"]
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
NAME_RE = re.compile(r"^(?=.{3,255}$)([^.\s]{1,63}\.)+[a-z]{2,}$")


def _nh(name):
    from eth_utils import keccak
    n = b"\0" * 32
    for label in reversed(name.split(".")):
        n = keccak(n + keccak(label.encode()))
    return n.hex()


def _eth_call(to, data):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]}).encode()
    for rpc in ETH_RPCS:
        try:
            r = urllib.request.urlopen(urllib.request.Request(rpc, data=body, headers={"Content-Type": "application/json", "User-Agent": "OMENZ Name Resolve"}), timeout=8)
            d = json.load(r)
            if "result" in d:
                return d["result"]
        except Exception:
            continue
    raise RuntimeError("Ethereum RPC unavailable")


def _base_call(to, data):
    return wallet._rpc("eth_call", [{"to": to, "data": data}, "latest"])


def _addr(raw):
    if not raw or len(raw) < 66 or int(raw, 16) == 0:
        return None
    return "0x" + raw[-40:]


def _string(raw):
    try:
        b = bytes.fromhex(raw[2:])
        off = int.from_bytes(b[:32], "big")
        ln = int.from_bytes(b[off:off + 32], "big")
        return b[off + 32:off + 32 + ln].decode("utf-8") or None
    except Exception:
        return None


def _forward(name):
    """name -> (address|None, chain, resolver|None)."""
    base = name.endswith(".base.eth")
    call, reg = (_base_call, BASE_REGISTRY) if base else (_eth_call, ENS_REGISTRY)
    node = _nh(name)
    resolver = _addr(call(reg, "0x0178b8bf" + node))
    if not resolver:
        return None, "base" if base else "ethereum", None
    try:
        a = _addr(call(resolver, "0x3b3b57de" + node))
    except Exception:
        a = None
    return a, "base" if base else "ethereum", resolver


def _reverse(address):
    a = address.lower()[2:]
    out = {}
    try:  # ENS primary name (Ethereum)
        node = _nh(a + ".addr.reverse")
        r = _addr(_eth_call(ENS_REGISTRY, "0x0178b8bf" + node))
        nm = _string(_eth_call(r, "0x691f3431" + node)) if r else None
        if nm:
            fwd, _, _ = _forward(nm)
            out["ens"] = {"name": nm, "forward_verified": bool(fwd and fwd.lower() == address.lower())}
    except Exception:
        out["ens_error"] = "unavailable"
    try:  # Basename primary name (Base, ENSIP-19 coin type 0x80002105)
        node = _nh(a + ".80002105.reverse")
        r = _addr(_base_call(BASE_REGISTRY, "0x0178b8bf" + node))
        nm = _string(_base_call(r, "0x691f3431" + node)) if r else None
        if nm:
            fwd, _, _ = _forward(nm)
            out["basename"] = {"name": nm, "forward_verified": bool(fwd and fwd.lower() == address.lower())}
    except Exception:
        pass
    return out


def check(name=None, address=None, expected_address=None):
    out = {"service": "OMENZ Name Resolve", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    import sanctions
    warnings = []
    if expected_address and not ADDR_RE.match(str(expected_address)):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["expected_address must be a 0x address (40 hex characters)"]}
    if address:
        if not ADDR_RE.match(str(address)):
            return {**out, "verdict": "BAD_INPUT", "reasons": ["address must be a 0x address (40 hex characters)"]}
        rev = _reverse(address)
        names = list(dict.fromkeys(v["name"] for k, v in rev.items() if isinstance(v, dict) and v.get("forward_verified")))
        for k, v in rev.items():
            if isinstance(v, dict) and not v.get("forward_verified"):
                warnings.append(f"{k} primary name {v['name']} does NOT point back to this address: do not trust it")
        s = sanctions.check(address)
        res = {**out, "address": address, "reverse": rev, "names": names, "warnings": warnings,
               "sanctioned": bool(s.get("listed"))}
        res["verdict"] = "SANCTIONED" if s.get("listed") else "RESOLVED" if names else "NOT_FOUND"
        return res
    n = str(name or "").strip().rstrip(".")
    if any(ord(c) > 127 for c in n):
        warnings.append("name contains non-ASCII characters: it may be a look-alike of a familiar name (homoglyph attack)")
    n = n.lower()
    if not NAME_RE.match(n) or " " in n:
        return {**out, "verdict": "BAD_INPUT", "reasons": ["send name (e.g. vitalik.eth, jesse.base.eth) or address"]}
    try:
        a, chain, resolver = _forward(n)
    except Exception as e:
        return {**out, "verdict": "UNAVAILABLE", "name": n, "reasons": [f"name lookup unavailable ({type(e).__name__})"]}
    res = {**out, "name": n, "registry_chain": chain, "resolver": resolver, "address": a}
    if not resolver:
        return {**res, "verdict": "NOT_FOUND", "warnings": warnings, "reasons": ["name is not registered or has no resolver"]}
    if not a:
        return {**res, "verdict": "OFFCHAIN_UNSUPPORTED", "warnings": warnings,
                "reasons": ["name has a resolver but no on-chain address (offchain/CCIP-read names like *.cb.id are not supported yet)"]}
    try:
        code = wallet._rpc("eth_getCode", [a, "latest"])
        if code and code.lower().startswith("0xef0100"):
            res["base_account_type"] = f"wallet with EIP-7702 delegation to 0x{code[8:48]}"
        else:
            res["base_account_type"] = "contract (smart wallet or app)" if code and code != "0x" else "wallet (no code on Base)"
    except Exception:
        pass
    rev = _reverse(a)
    res["reverse"] = rev
    prim = [v["name"] for v in rev.values() if isinstance(v, dict) and v.get("forward_verified")]
    if prim and n not in prim:
        warnings.append(f"this address's own primary name is {prim[0]}, not {n}")
    s = sanctions.check(a)
    res["sanctioned"] = bool(s.get("listed"))
    if expected_address:
        res["expected_address"] = expected_address
        res["verdict"] = "MATCH" if expected_address.lower() == a.lower() else "MISMATCH"
        if res["verdict"] == "MISMATCH":
            warnings.append(f"{n} points to {a}, NOT to the address you were given: do not pay the given address on the strength of this name")
    else:
        res["verdict"] = "RESOLVED"
    if s.get("listed"):
        res["verdict"] = "SANCTIONED"
        warnings.append(f"resolved address is on the OFAC SDN list ({s.get('entity')})")
    res["warnings"] = warnings
    res["limits"] = "Reads current on-chain records. Names can be transferred or re-pointed later: resolve right before each payment."
    return res
