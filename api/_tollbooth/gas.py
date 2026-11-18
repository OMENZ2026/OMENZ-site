"""OMENZ Settlement Cost Check: what moving money on Base costs RIGHT NOW, and whether a payment this small is worth
settling on its own.

Measured 2026-11-18: an x402 'exact' settlement (EIP-3009 transferWithAuthorization) used ~86,550 gas on Base, about
8.7e-7 ETH ~ $0.0016 at the time: MORE than a $0.001 x402 payment. Whoever pays gas (usually the facilitator) loses on
tiny single settlements; batching (Circle Gateway nanopayments, deferred schemes) or prepaid credits fix it.
Chore hunt: gas price 3,333 payers / 762 sellers. Live public chain data (Base RPC + Chainlink ETH/USD on Base). No AI.
"""
import time

import wallet

VERSION = "0.1.0"
CHAINLINK_ETH_USD_BASE = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"
GAS = {"x402_exact_settlement": 86550, "usdc_transfer": 62000, "eth_transfer": 21000, "erc20_approve": 46000}
STALE_S = 3 * 3600


def _eth_usd():
    r = wallet._rpc("eth_call", [{"to": CHAINLINK_ETH_USD_BASE, "data": "0xfeaf968c"}, "latest"])
    price = int(r[2 + 64:2 + 128], 16) / 1e8
    updated = int(r[2 + 192:2 + 256], 16)
    return price, updated


def _l1_fee_eth():
    """L1 data fee from the newest USDC transfer receipt we can find (Base is an OP-stack L2)."""
    try:
        head = int(wallet._rpc("eth_blockNumber", []), 16)
        logs = wallet._rpc("eth_getLogs", [{"address": wallet.USDC, "topics": [wallet.TRANSFER], "fromBlock": hex(head - 3), "toBlock": hex(head)}])
        for lg in logs[:3]:
            rc = wallet._rpc("eth_getTransactionReceipt", [lg["transactionHash"]])
            if rc and rc.get("l1Fee"):
                return int(rc["l1Fee"], 16) / 1e18
    except Exception:
        pass
    return 2.5e-9  # measured median 2026-11-18


def settlement_cost(amount_usd=None, payments_per_day=None):
    out = {"version": VERSION, "network": "base", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        gp = int(wallet._rpc("eth_gasPrice", []), 16)
        eth_usd, updated = _eth_usd()
    except wallet.WalletError as e:
        return {**out, "status": "UNAVAILABLE", "reason": str(e)}
    l1 = _l1_fee_eth()
    costs = {}
    for k, g in GAS.items():
        eth = g * gp / 1e18 + l1
        costs[k] = {"gas": g, "eth": round(eth, 12), "usd": round(eth * eth_usd, 6)}
    out.update({"gas_price_gwei": round(gp / 1e9, 6), "l1_data_fee_eth": l1, "eth_usd": eth_usd,
                "eth_usd_source": "Chainlink ETH/USD on Base", "eth_usd_stale": time.time() - updated > STALE_S, "costs": costs})
    s = costs["x402_exact_settlement"]["usd"]
    out["break_even"] = {"payment_usd_for_5pct_overhead": round(s / 0.05, 6), "payment_usd_for_1pct_overhead": round(s / 0.01, 6)}
    if amount_usd not in (None, ""):
        try:
            amt = float(amount_usd)
        except (TypeError, ValueError):
            return {**out, "status": "BAD_INPUT", "reason": "amount_usd must be a number"}
        if amt <= 0:
            return {**out, "status": "BAD_INPUT", "reason": "amount_usd must be above 0"}
        ratio = s / amt
        if ratio <= 0.05:
            verdict, why = "SETTLE", "on-chain cost is 5% of the payment or less"
        elif ratio <= 0.5:
            verdict, why = "BATCH_OR_CREDITS", "settlement eats a large share of the payment: batch it or use prepaid credits"
        else:
            verdict, why = "DONT_SETTLE_SINGLY", "settling this payment on its own costs about as much as (or more than) the payment"
        out["payment"] = {"amount_usd": amt, "settlement_cost_usd": s, "overhead_pct": round(ratio * 100, 2), "verdict": verdict, "why": why}
        if payments_per_day not in (None, ""):
            try:
                n = max(0, int(payments_per_day))
                out["payment"]["daily"] = {"payments": n, "volume_usd": round(n * amt, 6), "gas_if_settled_singly_usd": round(n * s, 6),
                                           "cdp_facilitator_fees_usd": round(max(0, n - 1000 / 30) * 0.001, 6)}
            except (TypeError, ValueError):
                pass
        out["options"] = [
            {"option": "Coinbase CDP facilitator", "cost": "free verify; first 1,000 settlements/month free, then $0.001 each (gas included)"},
            {"option": "Circle Gateway nanopayments", "cost": "signed authorizations batched into one settlement; buyer pays no per-payment gas (Circle docs)"},
            {"option": "OMENZ prepaid credits", "cost": "one $1/$5 settlement, then checks draw from the balance (e.g. checkout/*/credit at 1%, min $0.0002)"},
            {"option": "self-hosted facilitator", "cost": f"you pay the ~${s} gas per settlement yourself"}]
    out["status"] = "OK"
    return out
