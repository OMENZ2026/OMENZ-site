"""OMENZ Agent Trust: should my agent deal with this wallet? A deterministic know-your-agent check (2026-11-24).

Demand (market index 11-24): KYA / agent identity / trust score = 57 endpoints, 32 sellers, 175 payers in 30 days, median
$0.01 (top sellers: 7-component trust scores). Big Bro 11-23 list: "merchant/agent identity checks". This scores a wallet
from evidence anyone can re-check, every point with its reason:
  OFAC SDN (all chains) - hard BLOCK | activity on Base + Ethereum (transactions sent) | wallet kind | USDC on Base |
  x402 seller footprint (listed services paying out here, their real payers) | OMENZ-checked job history.
No AI, no opinions, nothing stored.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor

import address_screen
import chain_tools as ct
import gas_compare

VERSION = "0.1.0"
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def _nonce(rpcs, a):
    return int(ct._rpc(rpcs, "eth_getTransactionCount", [a, "latest"]), 16)


def _auths_7d(a):
    """Gasless USDC payments this wallet signed on Base in the last ~7 days (EIP-3009 AuthorizationUsed, the x402 'exact'
    payment). x402 buyers never send transactions themselves (the facilitator does), so nonce alone calls them 'new'."""
    rpcs = ["https://base-rpc.publicnode.com", "https://mainnet.base.org"]
    head = int(ct._rpc(rpcs, "eth_blockNumber", []), 16)
    t1 = "0x" + a.lower()[2:].rjust(64, "0")
    spans = [(head - (i + 1) * 43200, head - i * 43200) for i in range(7)]

    def one(sp):
        return len(ct._rpc(rpcs, "eth_getLogs", [{"address": USDC_BASE, "topics": [ct.T_AUTH_USED, t1], "fromBlock": hex(sp[0] + 1), "toBlock": hex(sp[1])}]))
    with ThreadPoolExecutor(7) as ex:
        return sum(ex.map(one, spans))


def check(address):
    a = str(address or "").strip()
    out = {"service": "OMENZ Agent Trust", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "stored": False}
    if not re.match(r"^0x[0-9a-fA-F]{40}$", a):
        return {**out, "error": "address must be an EVM wallet address (0x + 40 hex)"}
    if a.lower() in ("0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"):
        return {**out, "address": a, "score": 0, "verdict": "NOT_A_WALLET", "reasons": ["burn address: funds sent here are destroyed, never pay it"]}
    scr = address_screen.screen(a)
    if scr.get("sanctioned"):
        return {**out, "address": a, "score": 0, "verdict": "BLOCK", "reasons": [f"on the OFAC SDN list ({scr['match']['entity']})"],
                "sanctions": scr["match"]}
    jobs = {"base_tx": lambda: _nonce(ct.BASE_RPCS, a), "eth_tx": lambda: _nonce(gas_compare.CHAINS["ethereum"][1], a),
            "usdc": lambda: int(ct._call(ct.BASE_RPCS, USDC_BASE, "balanceOf(address)", ct._word(a)), 16) / 1e6,
            "code": lambda: ct._rpc(ct.BASE_RPCS, "eth_getCode", [a, "latest"]),
            "auths7": lambda: _auths_7d(a)}
    with ThreadPoolExecutor(5) as ex:
        fut = {k: ex.submit(f) for k, f in jobs.items()}
    sig = {}
    for k, f in fut.items():
        try:
            sig[k] = f.result()
        except Exception:
            sig[k] = None
    score, reasons = 50, []

    def pt(n, why):
        nonlocal score
        score += n
        reasons.append(f"{'+' if n >= 0 else ''}{n}: {why}")

    seller = None
    try:
        import market
        p = market.payee(a)
        if p.get("x402_endpoints"):
            payers = max((s["payers_30d"] for s in p.get("services", [])), default=0)
            seller = {"verdict": p["verdict"], "endpoints": p["x402_endpoints"], "top_service": (p.get("services") or [{}])[0].get("host"),
                      "max_payers_30d": payers}
            if p["verdict"] == "SHARED_ADDRESS":
                pt(0, f"payout address shared by {len(p['services'])}+ services (platform/facilitator wallet): judge the endpoint, not the wallet")
            elif payers >= 10:
                pt(15, f"payout wallet of a listed x402 seller with {payers} real payers in 30 days")
            else:
                pt(5, f"payout wallet of a listed x402 seller ({payers} payers in 30 days)")
    except Exception:
        pass
    sent = (sig["base_tx"] or 0) + (sig["eth_tx"] or 0)
    if sig["base_tx"] is None and sig["eth_tx"] is None:
        reasons.append("0: chain data unavailable right now")
    elif sent == 0 and sig.get("auths7"):
        pt(0, "sends no transactions itself: pays gasless through x402 (normal for agents)")
    elif sent == 0 and seller:
        pt(0, "receive-only wallet: normal for a seller's payout address")
    elif sent == 0:
        pt(-20, "has never sent a transaction on Base or Ethereum (brand-new or receive-only)")
    elif sent < 10:
        pt(0, f"light history: {sent} transactions sent")
    elif sent < 100:
        pt(8, f"active: {sent} transactions sent")
    else:
        pt(15, f"long history: {sent} transactions sent")
    code = sig["code"]
    kind = None if code is None else ("plain wallet (EOA)" if code in ("0x", "0x0") else
                                      "EIP-7702 delegated account" if str(code).startswith("0xef0100") else "smart contract / smart wallet")
    a7 = sig.get("auths7")
    if a7:
        pt(15 if a7 >= 20 else 8, f"active x402 buyer: {a7} gasless USDC payments signed on Base in the last 7 days")
    if sig["usdc"] and sig["usdc"] >= 1:
        pt(5, f"holds {sig['usdc']:.2f} USDC on Base (can pay)")
    rep = None
    try:
        import contracts
        r = contracts.reputation(a)
        if r.get("jobs_checked"):
            rep = {k: r[k] for k in ("jobs_checked", "passed", "failed", "distinct_buyers")}
            if r["failed"] > r["passed"]:
                pt(-15, f"OMENZ-checked jobs: more failed ({r['failed']}) than passed ({r['passed']})")
            elif r["distinct_buyers"] >= 3:
                pt(10, f"OMENZ-checked jobs: {r['passed']} passed for {r['distinct_buyers']} different buyers")
            else:
                pt(3, f"OMENZ-checked jobs: {r['passed']} passed (few distinct buyers = weak evidence)")
    except Exception:
        pass
    score = max(0, min(100, score))
    verdict = "TRUSTED" if score >= 70 else "ESTABLISHED" if score >= 58 else "LIMITED_HISTORY" if score >= 40 else "NEW_OR_UNKNOWN"
    return {**out, "address": a, "score": score, "verdict": verdict, "reasons": reasons,
            "signals": {"transactions_sent": {"base": sig["base_tx"], "ethereum": sig["eth_tx"]}, "wallet_kind_on_base": kind,
                        "usdc_base": sig["usdc"], "x402_payments_signed_7d": sig.get("auths7"), "x402_seller": seller, "omenz_jobs": rep, "sanctions": "not listed (OFAC SDN, all chains)"},
            "how_to_use": "BLOCK: never pay. NEW_OR_UNKNOWN / LIMITED_HISTORY: small amounts, escrow or checkpoints (POST /v1/checkpoint/create). ESTABLISHED / TRUSTED: normal limits.",
            "limits": "Evidence about the WALLET, not who controls it; a score is a starting point, not a guarantee. Base + Ethereum only."}
