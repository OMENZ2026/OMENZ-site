"""OMENZ chain chores for paying agents: decode a Base transaction in plain English, resolve names <-> addresses.

Chore hunt 2026-11-18 (market index, payers per seller): tx decode 639 payers / 81 sellers (median $0.01),
ENS/address resolve 771 payers / 79 sellers. Both sit on the money path: "what did that payment actually do?",
"who am I paying?". Public chain data via public RPCs, never needs a key, never signs. Deterministic, no AI calls.
"""
import json
import re
import time
import urllib.request

from eth_utils import keccak, to_checksum_address

VERSION = "0.1.0"
BASE_RPCS = ["https://mainnet.base.org", "https://base-rpc.publicnode.com"]
ETH_RPCS = ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"]
TXH = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
T_APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
T_AUTH_USED = "0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5"
SELECTORS = {
    "a9059cbb": "transfer(to, amount)", "095ea7b3": "approve(spender, amount)", "23b872dd": "transferFrom(from, to, amount)",
    "e3ee160e": "transferWithAuthorization (EIP-3009: the x402 'exact' payment)", "ef55bec6": "receiveWithAuthorization (EIP-3009)",
    "ac9650d8": "multicall", "5ae401dc": "multicall(deadline, data)", "3593564c": "Uniswap execute", "b6f9de95": "swapExactETHForTokens",
    "7ff36ab5": "swapExactETHForTokens", "38ed1739": "swapExactTokensForTokens", "d0e30db0": "deposit (wrap ETH)", "2e1a7d4d": "withdraw (unwrap)",
    "a22cb465": "setApprovalForAll(operator, approved)", "42842e0e": "safeTransferFrom (NFT)", "b88d4fde": "safeTransferFrom (NFT, data)",
    "1626ba7e": "isValidSignature", "6a761202": "Safe execTransaction",
}
KNOWN_TOKENS = {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": ("USDC", 6), "0x4200000000000000000000000000000000000006": ("WETH", 18),
                "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": ("DAI", 18), "0xfde4c96c8593536e31f229ea8f37b2ada2699bb2": ("USDT", 6)}
UNLIMITED = 2 ** 255


class ChainError(Exception):
    pass


def _rpc(rpcs, method, params):
    last = None
    for url in rpcs:
        try:
            req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "OMENZ-chain/0.1"})
            d = json.load(urllib.request.urlopen(req, timeout=15))
            if "result" in d:
                return d["result"]
            last = (d.get("error") or {}).get("message")
        except Exception as e:
            last = type(e).__name__
    raise ChainError(f"RPC unavailable ({last})")


def _a(topic):
    return to_checksum_address("0x" + topic[-40:])


def _token(addr, cache, rpcs=None):
    rpcs = rpcs or BASE_RPCS
    a = addr.lower()
    if a in KNOWN_TOKENS and rpcs is BASE_RPCS:
        return KNOWN_TOKENS[a]
    if a in cache:
        return cache[a]
    sym, dec = None, None
    try:
        raw = _rpc(rpcs, "eth_call", [{"to": a, "data": "0x95d89b41"}, "latest"])
        b = bytes.fromhex(raw[2:])
        if len(b) >= 96:
            n = int.from_bytes(b[32:64], "big")
            sym = b[64:64 + n].decode("utf-8", "ignore") or None
        elif len(b) == 32:
            sym = b.rstrip(b"\0").decode("utf-8", "ignore") or None
        dec = int(_rpc(rpcs, "eth_call", [{"to": a, "data": "0x313ce567"}, "latest"]), 16)
    except Exception:
        pass
    cache[a] = (sym, dec)
    return cache[a]


def _amt(raw, dec):
    return raw / 10 ** dec if dec is not None else None


def tx_decode(tx_hash, chain=None):
    """11-24: chain= adds ethereum/arbitrum/optimism/polygon/bsc/avalanche (market: raw tx receipts by hash = 271 payers on
    Ethereum alone). Default base, unchanged for existing callers."""
    tx_hash = str(tx_hash or "").strip()
    chain = str(chain or "base").strip().lower()
    import gas_compare
    if chain not in gas_compare.CHAINS:
        return {"status": "BAD_INPUT", "reason": f"chain must be one of {', '.join(gas_compare.CHAINS)}"}
    rpcs = BASE_RPCS if chain == "base" else gas_compare.CHAINS[chain][1]
    native = gas_compare.CHAINS[chain][2]
    if not TXH.match(tx_hash):
        return {"status": "BAD_INPUT", "reason": "tx_hash must be 0x + 64 hex"}
    try:
        tx = _rpc(rpcs, "eth_getTransactionByHash", [tx_hash])
        if tx is None:
            return {"status": "NOT_FOUND", "tx_hash": tx_hash, "chain": chain, "reason": f"no such transaction on {chain}"}
        rc = _rpc(rpcs, "eth_getTransactionReceipt", [tx_hash])
        head = int(_rpc(rpcs, "eth_blockNumber", []), 16)
    except ChainError as e:
        return {"status": "UNAVAILABLE", "reason": str(e)}
    out = {"version": VERSION, "network": chain, "native": native, "tx_hash": tx_hash, "from": to_checksum_address(tx["from"]),
           "to": to_checksum_address(tx["to"]) if tx.get("to") else None, "eth_value": int(tx["value"], 16) / 1e18}
    data = tx.get("input") or "0x"
    sel = data[2:10]
    out["function"] = SELECTORS.get(sel, f"unknown selector 0x{sel}" if sel else "plain ETH transfer (no calldata)")
    if rc is None:
        return {**out, "status": "PENDING", "summary": "sent, not in a block yet"}
    blk = int(rc["blockNumber"], 16)
    out.update({"block": blk, "confirmations": head - blk + 1, "status": "SUCCESS" if rc.get("status") == "0x1" else "REVERTED",
                "gas_used": int(rc["gasUsed"], 16), "fee_native": int(rc["gasUsed"], 16) * int(rc.get("effectiveGasPrice") or "0x0", 16) / 1e18})
    if native == "ETH":
        out["fee_eth"] = out["fee_native"]
    try:
        b = _rpc(rpcs, "eth_getBlockByNumber", [rc["blockNumber"], False])
        out["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(b["timestamp"], 16)))
    except ChainError:
        pass
    cache, transfers, approvals, auth_used = {}, [], [], 0
    for lg in (rc.get("logs") or [])[:200]:
        t = lg.get("topics") or []
        if not t:
            continue
        tok = lg["address"].lower()
        if t[0] == T_TRANSFER and len(t) == 3:
            sym, dec = _token(tok, cache, rpcs)
            raw = int(lg["data"], 16) if lg.get("data") not in (None, "0x") else 0
            transfers.append({"token": sym or tok, "token_address": to_checksum_address(tok), "from": _a(t[1]), "to": _a(t[2]),
                              "amount": _amt(raw, dec)})
        elif t[0] == T_TRANSFER and len(t) == 4:
            transfers.append({"token": "NFT", "token_address": to_checksum_address(tok), "from": _a(t[1]), "to": _a(t[2]), "token_id": int(t[3], 16)})
        elif t[0] == T_APPROVAL and len(t) == 3:
            sym, dec = _token(tok, cache, rpcs)
            raw = int(lg["data"], 16) if lg.get("data") not in (None, "0x") else 0
            approvals.append({"token": sym or tok, "owner": _a(t[1]), "spender": _a(t[2]),
                              "amount": "UNLIMITED" if raw >= UNLIMITED else _amt(raw, dec)})
        elif t[0] == T_AUTH_USED:
            auth_used += 1
    out.update({"token_transfers": transfers, "approvals": approvals})
    flags = []
    if any(a["amount"] == "UNLIMITED" for a in approvals):
        flags.append("UNLIMITED_APPROVAL: a spender can move all of this token from the owner; revoke if not intended")
    if out["status"] == "REVERTED":
        flags.append("REVERTED: nothing moved except the gas fee")
    is_x402 = auth_used > 0 or sel in ("e3ee160e", "ef55bec6")
    out["kind"] = "x402_payment (EIP-3009 authorization)" if is_x402 else \
        "token_transfer" if transfers and not approvals else "approval" if approvals and not transfers else \
        "contract_call" if sel else "eth_transfer"
    parts = []
    if out["status"] == "REVERTED":
        parts.append("Reverted.")
    for x in transfers[:5]:
        if "amount" in x:
            parts.append(f"{x['amount']} {x['token']} from {x['from'][:8]}... to {x['to'][:8]}...")
        else:
            parts.append(f"NFT #{x['token_id']} from {x['from'][:8]}... to {x['to'][:8]}...")
    for x in approvals[:3]:
        parts.append(f"{x['owner'][:8]}... approved {x['spender'][:8]}... for {x['amount']} {x['token']}")
    if is_x402:
        parts.insert(0, "x402-style payment:")
    if out["eth_value"]:
        parts.append(f"{out['eth_value']} {out['native']} sent")
    out["summary"] = " ".join(parts) or f"{out['function']} with no token movement"
    out["flags"] = flags
    return out


# ---------------------------------------------------------------- names
ENS_REGISTRY = "0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e"
BASENAME_REGISTRY = "0xb94704422c2a1e396835a571837aa5ae53285a95"


def namehash(name):
    node = b"\0" * 32
    if name:
        for label in reversed(name.split(".")):
            node = keccak(node + keccak(label.encode()))
    return node


def _call(rpcs, to, sig, args_hex=""):
    return _rpc(rpcs, "eth_call", [{"to": to, "data": "0x" + keccak(text=sig)[:4].hex() + args_hex}, "latest"])


def _addr_from(word):
    a = "0x" + word[-40:]
    return None if int(a, 16) == 0 else to_checksum_address(a)


def _resolve(name):
    base = name.endswith(".base.eth")
    rpcs, reg = (BASE_RPCS, BASENAME_REGISTRY) if base else (ETH_RPCS, ENS_REGISTRY)
    node = namehash(name).hex()
    resolver = _addr_from(_call(rpcs, reg, "resolver(bytes32)", node))
    if not resolver:
        return None, None, ("basenames" if base else "ens")
    addr = _addr_from(_call(rpcs, resolver, "addr(bytes32)", node))
    return addr, resolver, ("basenames" if base else "ens")


def _reverse(addr):
    """Primary name via ENS reverse (mainnet). Forward-verified so a spoofed reverse record is not trusted."""
    node = namehash(addr.lower()[2:] + ".addr.reverse").hex()
    resolver = _addr_from(_call(ETH_RPCS, ENS_REGISTRY, "resolver(bytes32)", node))
    if not resolver:
        return None, False
    raw = _call(ETH_RPCS, resolver, "name(bytes32)", node)
    b = bytes.fromhex(raw[2:])
    if len(b) < 96:
        return None, False
    n = int.from_bytes(b[32:64], "big")
    name = b[64:64 + n].decode("utf-8", "ignore")
    if not name:
        return None, False
    fwd, _, _ = _resolve(name)
    return name, bool(fwd and fwd.lower() == addr.lower())


def name_resolve(q):
    q = str(q or "").strip()
    out = {"version": VERSION, "query": q, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        if ADDR.match(q):
            name, verified = _reverse(q)
            return {**out, "kind": "address", "address": to_checksum_address(q), "primary_name": name,
                    "forward_verified": verified if name else None,
                    "note": None if name else "no ENS primary name set for this address",
                    "warning": "reverse name does not resolve back to this address: do not trust it" if name and not verified else None}
        if "." not in q or len(q) > 255 or not re.match(r"^[a-z0-9\-_.]+$", q.lower()):
            return {**out, "status": "BAD_INPUT", "reason": "send an ENS name (vitalik.eth), a Basename (name.base.eth) or a 0x address"}
        addr, resolver, system = _resolve(q.lower())
        return {**out, "kind": "name", "system": system, "address": addr, "resolver": resolver,
                "status": "RESOLVED" if addr else "UNRESOLVED", "chain": "base" if system == "basenames" else "ethereum",
                "note": "Pay this address only if it matches what the seller's own 402 says (authorize checks payTo)." if addr else "name has no address record"}
    except ChainError as e:
        return {**out, "status": "UNAVAILABLE", "reason": str(e)}


# ---- Token Balance + Allowance Check (chore hunt 2026-11-20: erc20-balance 785 payers, allowance 301 payers in the
# x402 market at $0.003; OMENZ at the $0.002 floor. Allowance is on the money path: "can this spender drain me?") ----

def _word(addr):
    return addr.lower()[2:].rjust(64, "0")


def _bad(name, v):
    return None if v and ADDR.match(v) else {"status": "BAD_INPUT", "reasons": [f"{name} must be a 0x address (40 hex)"]}


def token_balance(address, token=None):
    """ERC-20 (or native ETH when token omitted / 'eth') balance on Base."""
    err = _bad("address", address)
    if err:
        return err
    out = {"service": "OMENZ Token Balance", "version": VERSION, "chain": "base", "address": to_checksum_address(address),
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        if not token or token.lower() in ("eth", "native"):
            raw = int(_rpc(BASE_RPCS, "eth_getBalance", [address, "latest"]), 16)
            return {**out, "status": "OK", "token": "ETH (native)", "symbol": "ETH", "decimals": 18, "raw": str(raw), "balance": raw / 1e18}
        err = _bad("token", token)
        if err:
            return err
        sym, dec = _token(token, {})
        if dec is None:
            return {**out, "status": "NOT_A_TOKEN", "token": token, "reasons": ["no ERC-20 decimals() at this address on Base"]}
        raw = int(_call(BASE_RPCS, token, "balanceOf(address)", _word(address)), 16)
        return {**out, "status": "OK", "token": to_checksum_address(token), "symbol": sym, "decimals": dec, "raw": str(raw), "balance": _amt(raw, dec)}
    except ChainError as e:
        return {**out, "status": "UNAVAILABLE", "reason": str(e)}


def allowance_check(owner, token, spender, intended_usd=None):
    """How much `spender` may move from `owner` right now. UNLIMITED / EXCEEDS_BALANCE flagged, with a safe next action."""
    for n, v in (("owner", owner), ("token", token), ("spender", spender)):
        err = _bad(n, v)
        if err:
            return err
    out = {"service": "OMENZ Allowance Check", "version": VERSION, "chain": "base", "owner": to_checksum_address(owner),
           "token": to_checksum_address(token), "spender": to_checksum_address(spender), "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        sym, dec = _token(token, {})
        if dec is None:
            return {**out, "status": "NOT_A_TOKEN", "reasons": ["no ERC-20 decimals() at this address on Base"]}
        raw = int(_call(BASE_RPCS, token, "allowance(address,address)", _word(owner) + _word(spender)), 16)
        bal = int(_call(BASE_RPCS, token, "balanceOf(address)", _word(owner)), 16)
        flags, risk = [], "NONE"
        if raw == 0:
            verdict, nxt = "NO_ALLOWANCE", "Spender cannot move this token from the owner. Nothing to revoke."
        elif raw >= UNLIMITED:
            verdict, risk, nxt = "UNLIMITED", "HIGH", "Spender can move the owner's ENTIRE balance, now and later. Revoke (approve spender 0) unless this is a contract you trust."
            flags.append("unlimited approval")
        elif raw >= bal and bal > 0:
            verdict, risk, nxt = "COVERS_FULL_BALANCE", "MEDIUM", "Allowance covers everything the owner holds. Lower it to what the next payment needs."
            flags.append("allowance >= balance")
        else:
            verdict, risk, nxt = "LIMITED", "LOW", "Spender can move at most the allowance shown."
        res = {**out, "status": "OK", "verdict": verdict, "risk": risk, "symbol": sym, "decimals": dec,
               "allowance_raw": str(raw), "allowance": None if raw >= UNLIMITED else _amt(raw, dec), "owner_balance": _amt(bal, dec),
               "flags": flags, "next_action": nxt, "revoke_call": {"to": to_checksum_address(token), "function": "approve(spender, 0)"} if raw else None}
        if intended_usd is not None and sym in ("USDC", "USDT", "DAI") and raw < UNLIMITED:
            res["covers_intended"] = _amt(raw, dec) >= float(intended_usd)
        return res
    except ChainError as e:
        return {**out, "status": "UNAVAILABLE", "reason": str(e)}
