"""OMENZ Token Check (Base): is this token safe to hold or accept before an agent buys, swaps or takes it as payment?
(chore hunt 2026-11-21: an x402 "Token Verdict" seller grew 774 -> 3,332 paying wallets in 7 days; OMENZ's version is
deterministic, no AI grades, no price predictions.)

Reads public chain data only (never signs, never moves money):
  contract      code present? (no code = not a token)
  metadata      name / symbol / decimals / totalSupply (ERC-20 calls answer?)
  proxy         EIP-1967 implementation / admin / beacon slots -> upgradeable = code can change under you
  owner powers  owner() set (not renounced) + powerful functions in the bytecode: mint, pause, blacklist/freeze, fees
  sanctions     owner / proxy admin on the OFAC SDN list
Verdict: SAFE_TO_HOLD / CAUTION / RED_FLAGS with every reason. Known regulated stablecoins are labeled: their issuer
can freeze/pause by design (normal for USDC/EURC), which is a CAUTION fact, not a red flag.
"""
import time

import sanctions
import wallet

VERSION = "0.2.0"
SLOT_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
SLOT_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
SLOT_BEACON = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
SLOT_ZOS_IMPL = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"  # older OpenZeppelin (zos) proxies, e.g. USDC
SLOT_ZOS_ADMIN = "0x10d6a54a4754c8869d6886b5f5d7fbfa5b4522237ea5c60d11bc4e7a1ff9390b"
ZERO = "0x" + "0" * 40
# 4-byte selectors searched for as PUSH4 operands (0x63 + selector) in runtime bytecode
POWERS = {
    "mint": ["40c10f19", "a0712d68", "4e6ec247"],          # mint(address,uint256), mint(uint256), _mint-style
    "pause": ["8456cb59", "3f4ba83a"],                      # pause(), unpause()
    "blacklist": ["f9f92be4", "44337ea1", "e4997dc5", "537df3b6", "0ecb93c0", "1a895266"],  # blacklist/addBlackList/removeBlackList/...
    "set_fees": ["8ee88c53", "c0246668", "61d027b3"],  # setFee-style (best effort)
    "max_tx_limits": ["ec28438a", "e01af92c", "6ddd1713"],
}
KNOWN = {  # regulated stablecoins on Base: issuer freeze/pause is by design
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC (Circle)",
    "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": "EURC (Circle)",
}


def _call(to, data):
    try:
        return wallet._rpc("eth_call", [{"to": to, "data": data}, "latest"])
    except Exception:
        return None


def _str(raw):
    """ABI string or bytes32 -> text."""
    if not raw or raw == "0x":
        return None
    h = raw[2:]
    try:
        if len(h) >= 128 and int(h[:64], 16) == 32:
            n = int(h[64:128], 16)
            return bytes.fromhex(h[128:128 + 2 * n]).decode("utf-8", "replace").strip("\x00") or None
        return bytes.fromhex(h[:64]).decode("utf-8", "replace").strip("\x00").strip() or None
    except Exception:
        return None


def _addr_slot(token, slot):
    try:
        v = wallet._rpc("eth_getStorageAt", [token, slot, "latest"])
        a = "0x" + v[-40:]
        return None if int(a, 16) == 0 else a.lower()
    except Exception:
        return None


def _powers(code):
    c = (code or "").lower()
    return sorted(k for k, sels in POWERS.items() if any(s and ("63" + s) in c for s in sels))


def _sourcify(addr):
    """Public source verification (Sourcify, Base 8453). Returns 'exact'/'partial'/'unverified'/None(unavailable)."""
    import json as _j
    import urllib.request as _u
    try:
        r = _u.urlopen(_u.Request(f"https://sourcify.dev/server/v2/contract/8453/{addr}", headers={"User-Agent": "OMENZ Token Check"}), timeout=5)
        d = _j.load(r)
        m = d.get("match") or d.get("runtimeMatch")
        return {"exact_match": "exact", "match": "partial", "partial": "partial", "perfect": "exact"}.get(str(m), "partial" if m else "unverified")
    except _u.HTTPError as e:
        return "unverified" if e.code == 404 else None
    except Exception:
        return None


def check(token):
    out = {"service": "OMENZ Token Check", "version": VERSION, "network": "base",
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "never_moves_money": True}
    try:
        t = wallet._check(str(token or "").strip()).lower()
    except Exception:
        return {**out, "verdict": "BAD_INPUT", "reasons": ["token must be a 0x contract address on Base"]}
    try:
        code = wallet._rpc("eth_getCode", [t, "latest"])
    except Exception as e:
        return {**out, "verdict": "UNAVAILABLE", "reasons": [f"Base RPC unavailable ({type(e).__name__})"]}
    red, caution, passed, facts = [], [], [], {"token": t}
    if not code or code in ("0x", "0x0"):
        return {**out, **facts, "verdict": "RED_FLAGS", "red_flags": ["no contract code at this address: it is not a token (wallet or wrong network)"],
                "caution": [], "passed": []}
    name, symbol = _str(_call(t, "0x06fdde03")), _str(_call(t, "0x95d89b41"))
    dec_raw, sup_raw = _call(t, "0x313ce567"), _call(t, "0x18160ddd")
    decimals = int(dec_raw, 16) if dec_raw and dec_raw != "0x" else None
    supply = int(sup_raw, 16) if sup_raw and sup_raw != "0x" else None
    facts.update(name=name, symbol=symbol, decimals=decimals,
                 total_supply=(supply / 10 ** decimals) if (supply is not None and decimals is not None and decimals <= 36) else supply)
    if decimals is None or supply is None:
        red.append("does not answer standard ERC-20 calls (decimals/totalSupply): not a normal token")
    else:
        passed.append(f"standard ERC-20: {symbol or '?'} ({name or '?'}), {decimals} decimals")
    impl, admin, beacon = _addr_slot(t, SLOT_IMPL), _addr_slot(t, SLOT_ADMIN), _addr_slot(t, SLOT_BEACON)
    if not (impl or beacon):
        impl, admin = _addr_slot(t, SLOT_ZOS_IMPL), admin or _addr_slot(t, SLOT_ZOS_ADMIN)
    scan = code
    if impl or beacon:
        facts["proxy"] = {"implementation": impl, "admin": admin, "beacon": beacon}
        caution.append("upgradeable proxy: whoever controls the admin can change how this token works")
        if impl:
            try:
                scan = code + (wallet._rpc("eth_getCode", [impl, "latest"]) or "")
            except Exception:
                pass
    else:
        passed.append("not an upgradeable proxy (no EIP-1967 or OpenZeppelin proxy slots)")
    owner_raw = _call(t, "0x8da5cb5b")
    owner = ("0x" + owner_raw[-40:]).lower() if owner_raw and len(owner_raw) >= 42 and int(owner_raw, 16) != 0 else None
    facts["owner"] = owner
    powers = _powers(scan)
    facts["owner_powers_in_code"] = powers
    if owner:
        if powers:
            caution.append(f"active owner {owner} with powerful functions in the code: {', '.join(powers)}")
        else:
            passed.append("owner set, but no mint/pause/blacklist/fee functions found in the code")
    else:
        passed.append("no owner (renounced or ownerless)" + (f"; code still contains: {', '.join(powers)}" if powers else ""))
        if powers and "mint" in powers and not (impl or admin):
            caution.append("mint function present: check who is allowed to call it (role-based access, not owner())")
    for who, label in ((owner, "owner"), (admin, "proxy admin")):
        if who:
            s = sanctions.check(who)
            if s.get("listed"):
                red.append(f"{label} {who} is on the OFAC SDN list ({s.get('entity')})")
    # 11-22: is the source code public and verified? (unverified = you cannot read what it does)
    targets = [("token", t)] + ([("implementation", impl)] if impl else [])
    ver = {label: _sourcify(a) for label, a in targets}
    facts["source_verified"] = {**ver, "source": "sourcify.dev"}
    for label, v in ver.items():
        if v == "unverified":
            caution.append(f"{label} source code is not verified on Sourcify: nobody can read what it really does"
                           + " (it may be verified on Basescan instead)")
        elif v in ("exact", "partial"):
            passed.append(f"{label} source code verified on Sourcify ({v} match)")
    if t in KNOWN:
        facts["known_stablecoin"] = KNOWN[t]
        caution = [c for c in caution if not c.startswith("active owner")] + [
            f"{KNOWN[t]}: regulated stablecoin; the issuer can freeze addresses or pause by design (normal for this asset)"]
    verdict = "RED_FLAGS" if red else "CAUTION" if caution else "SAFE_TO_HOLD"
    return {**out, **facts, "verdict": verdict, "red_flags": red, "caution": caution, "passed": passed,
            "limits": "Checks code and control, not price, liquidity or the team. Selector scan is best-effort (obfuscated code can hide functions). Pair with Authorize before paying.",
            "next": {"SAFE_TO_HOLD": "no control red flags found", "CAUTION": "read the cautions; fine for known assets, think twice for unknown tokens",
                     "RED_FLAGS": "do not accept or buy this token"}[verdict]}
