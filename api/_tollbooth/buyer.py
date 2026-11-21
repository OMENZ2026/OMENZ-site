"""OMENZ Buyer Kit: tools for agents that BUY things with micropayments (founder 2026-11-17: "more tools for agents who
are going to be buying stuff"). They fill the gaps around the existing pre-pay checks (market/find, quote, tx-preflight,
authorize, spend-gate):

- Shared Budget   one spending cap that a whole team of agents draws from. Spend Gate is stateless: each agent sends
                  its own running totals, so five agents can each "stay under" $1 and spend $5 together. A Shared Budget
                  keeps the one running total. Bookkeeping only: OMENZ never holds or moves money.
- Payment Verify  did this x402 payment actually settle on Base? Who paid whom, how much USDC, in which block, how many
                  confirmations. Takes a tx hash or the seller's PAYMENT-RESPONSE header. Public chain data, never needs a key.
- Delivery Check  after paying: did the response match what the seller advertised? We read the seller's own x402
                  discovery output example (unpaid probe) or a JSON Schema you send, and compare fields and types.
                  MATCH / PARTIAL / MISMATCH / NO_CONTRACT, with exactly what's missing. Pairs with finance/refund-request.

Deterministic, no AI calls. Budgets live in the OMENZ Apify key-value store (<= 90 days).
Honest limit (Shared Budget): storage has no atomic compare-and-set, so two spends landing in the same instant can both
pass. per_tx_max_usd bounds that overshoot; spends are idempotent by idempotency_key.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from locker import LockerError, _kv

VERSION = "0.1.0"
TTL_MAX_DAYS = 90
MAX_SPENDS = 1000
PERIODS = ("total", "day", "month")
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
TXH = re.compile(r"^0x[0-9a-fA-F]{64}$")


# ---------------------------------------------------------------- Shared Budget
def _kh(kind, key):
    return hashlib.sha256(f"omenz-budget|{kind}|{key}".encode()).hexdigest()


def _money(v, name, required=False):
    if v is None or v == "":
        if required:
            raise LockerError(400, f"{name} is required")
        return None
    try:
        f = round(float(v), 6)
    except (TypeError, ValueError):
        raise LockerError(400, f"{name} must be a number")
    if f < 0 or f != f or f > 1e9:
        raise LockerError(400, f"{name} must be a non-negative number")
    return f


def _addrs(v, name):
    if v in (None, "", []):
        return []
    if not isinstance(v, list):
        raise LockerError(400, f"{name} must be a list of 0x addresses")
    out = []
    for a in v[:200]:
        if not ADDR.match(str(a)):
            raise LockerError(400, f"{name}: {str(a)[:50]!r} is not a 0x address")
        out.append(str(a).lower())
    return out


def _window(period, ts):
    g = time.gmtime(ts)
    return {"total": "all", "day": time.strftime("%Y-%m-%d", g), "month": time.strftime("%Y-%m", g)}[period]


def budget_create(body, ttl_days=None):
    body = body if isinstance(body, dict) else {}
    cap = _money(body.get("cap_usd"), "cap_usd", required=True)
    if cap <= 0:
        raise LockerError(400, "cap_usd must be above 0")
    period = str(body.get("period") or "total").lower()
    if period not in PERIODS:
        raise LockerError(400, f"period must be one of {list(PERIODS)}")
    days = int(ttl_days or body.get("ttl_days") or 30)
    days = max(1, min(TTL_MAX_DAYS, days))
    bid, owner, spender = "bg_" + secrets.token_hex(12), secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    now = int(time.time())
    rec = {"v": 0, "name": str(body.get("name") or "")[:120], "cap_usd": cap, "period": period,
           "per_tx_max_usd": _money(body.get("per_tx_max_usd"), "per_tx_max_usd"),
           "escalate_above_usd": _money(body.get("escalate_above_usd"), "escalate_above_usd"),
           "allowed_recipients": _addrs(body.get("allowed_recipients"), "allowed_recipients"),
           "blocked_recipients": _addrs(body.get("blocked_recipients"), "blocked_recipients"),
           "owner_hash": _kh("owner", owner), "spender_hash": _kh("spender", spender),
           "created": now, "expires": now + days * 86400, "frozen": False, "spends": [],
           "velocity_max_per_hour": int(body["velocity_max_per_hour"]) if body.get("velocity_max_per_hour") not in (None, "") else None}
    _kv("PUT", bid, rec)
    return {"budget_id": bid, "owner_key": owner, "spender_key": spender, "cap_usd": cap, "period": period,
            "expires_at": rec["expires"],
            "note": "Give spender_key to every agent on the team (header X-Budget-Key) so they draw from one cap. "
                    "Keep owner_key yourself: it can also read, release and freeze. Both are shown once. "
                    "OMENZ keeps the count only; it never holds or moves your money."}


def _load(bid, key):
    if not str(bid or "").startswith("bg_") or not key:
        raise LockerError(400, "budget_id and header X-Budget-Key are required")
    rec = _kv("GET", bid)
    if rec is None or rec["expires"] < time.time():
        raise LockerError(404, "no such budget (or expired)")
    if hmac.compare_digest(rec["owner_hash"], _kh("owner", key)):
        return rec, "owner"
    if hmac.compare_digest(rec["spender_hash"], _kh("spender", key)):
        return rec, "spender"
    raise LockerError(403, "wrong budget key")


def _spent(rec, now):
    w = _window(rec["period"], now)
    return round(sum(s["amount_usd"] for s in rec["spends"]
                     if s["status"] == "spent" and _window(rec["period"], s["at"]) == w), 6)


def _summary(rec, now):
    spent = _spent(rec, now)
    return {"cap_usd": rec["cap_usd"], "period": rec["period"], "window": _window(rec["period"], now),
            "spent_usd": spent, "remaining_usd": round(max(0.0, rec["cap_usd"] - spent), 6), "frozen": rec["frozen"]}


def budget_spend(bid, key, body):
    """Ask to spend: ALLOW (recorded against the cap), DENY or ESCALATE (nothing recorded)."""
    body = body if isinstance(body, dict) else {}
    rec, role = _load(bid, key)
    now = int(time.time())
    amt = _money(body.get("amount_usd"), "amount_usd", required=True)
    rcpt = str(body.get("recipient") or "").strip().lower()
    if rcpt and not ADDR.match(rcpt):
        raise LockerError(400, "recipient must be a 0x address")
    idem = str(body.get("idempotency_key") or "")[:80]
    if idem:
        for s in rec["spends"]:
            if s.get("idempotency_key") == idem:
                return {"decision": "ALLOW" if s["status"] in ("spent", "released") else s["status"].upper(),
                        "spend_id": s["id"], "replayed": True, **_summary(rec, now)}
    reasons = _rules(rec, amt, rcpt, now)
    s = _summary(rec, now)
    if reasons:
        return {"decision": "DENY", "reasons": reasons, **s}
    ancestors = _ancestors(rec, now)
    for label, anc in ancestors:
        r2 = _rules(anc, amt, rcpt, now)
        if r2:
            return {"decision": "DENY", "reasons": [f"{label}: {r}" for r in r2], **s}
    for label, b in [("this budget", rec)] + ancestors:
        if b["escalate_above_usd"] is not None and amt > b["escalate_above_usd"]:
            return {"decision": "ESCALATE", "reasons": [f"amount ${amt} is above the escalate line ${b['escalate_above_usd']} of {label}: ask its owner"], **s}
    sid = "sp_" + secrets.token_hex(6)
    entry = {"id": sid, "at": now, "amount_usd": amt, "recipient": rcpt or None, "status": "spent",
             "agent": str(body.get("agent") or "")[:60] or None, "memo": str(body.get("memo") or "")[:200] or None,
             "url": str(body.get("url") or "")[:300] or None, "idempotency_key": idem or None, "by": role}
    _append(bid, rec, entry)
    for _, anc in ancestors:
        _append(anc["_id"], anc, {**entry, "idempotency_key": None, "by": "child:" + bid})
    return {"decision": "ALLOW", "spend_id": sid, **_summary(rec, now),
            **({"counted_against": [a["_id"] for _, a in ancestors]} if ancestors else {}),
            "next": "Pay now. If the purchase fails or you don't pay, POST budget/release with this spend_id to give the money back to the cap."}


def _rules(rec, amt, rcpt, now):
    reasons = []
    if rec["frozen"]:
        reasons.append("budget is frozen by its owner")
    if rec["per_tx_max_usd"] is not None and amt > rec["per_tx_max_usd"]:
        reasons.append(f"amount ${amt} is above the per-purchase max ${rec['per_tx_max_usd']}")
    if rcpt and rcpt in rec["blocked_recipients"]:
        reasons.append("recipient is on the blocked list")
    if rec["allowed_recipients"] and rcpt not in rec["allowed_recipients"]:
        reasons.append("recipient is not on the allowed list" if rcpt else "recipient required (budget has an allowed list)")
    if rec.get("velocity_max_per_hour"):
        n = sum(1 for x in rec["spends"] if x["status"] == "spent" and now - x["at"] < 3600)
        if n >= rec["velocity_max_per_hour"]:
            reasons.append(f"velocity limit: {n} purchases in the last hour (max {rec['velocity_max_per_hour']})")
    sm = _summary(rec, now)
    if amt > sm["remaining_usd"] + 1e-9:
        reasons.append(f"amount ${amt} is above what's left (${sm['remaining_usd']} of ${rec['cap_usd']} this {rec['period']})")
    return reasons


def _append(bid, rec, entry):
    if len(rec["spends"]) >= MAX_SPENDS:
        rec["spends"] = rec["spends"][-(MAX_SPENDS - 1):]
    rec["spends"].append(entry)
    _kv("PUT", bid, {k: v for k, v in rec.items() if k != "_id"})


def _ancestors(rec, now, max_depth=4):
    out, cur, seen = [], rec, set()
    while cur.get("parent") and len(out) < max_depth:
        pid = cur["parent"]
        if pid in seen:
            break
        seen.add(pid)
        p = _kv("GET", pid)
        if p is None or p["expires"] < now:
            raise LockerError(409, f"parent budget {pid} is gone or expired: this delegated budget can no longer spend")
        p["_id"] = pid
        out.append((f"parent budget {pid}" + (f" ({p['name']})" if p.get("name") else ""), p))
        cur = p
    return out


def budget_delegate(parent_id, key, body):
    """The parent's OWNER gives a child agent its own bounded allowance. The child can only narrow the parent's rules,
    and every child spend is also checked against and counted in every ancestor."""
    body = body if isinstance(body, dict) else {}
    parent, role = _load(parent_id, key)
    if role != "owner":
        raise LockerError(403, "only the parent's owner_key can delegate")
    depth = len(_ancestors(parent, int(time.time()))) + 1
    if depth > 4:
        raise LockerError(400, "delegation tree is limited to 4 levels")
    cap = _money(body.get("cap_usd"), "cap_usd", required=True)
    if cap > parent["cap_usd"] + 1e-9:
        raise LockerError(400, f"child cap ${cap} can't exceed the parent's ${parent['cap_usd']}")
    ptx = _money(body.get("per_tx_max_usd"), "per_tx_max_usd")
    if parent["per_tx_max_usd"] is not None:
        ptx = min(ptx, parent["per_tx_max_usd"]) if ptx is not None else parent["per_tx_max_usd"]
    allowed = _addrs(body.get("allowed_recipients"), "allowed_recipients")
    if parent["allowed_recipients"]:
        bad = [a for a in allowed if a not in parent["allowed_recipients"]]
        if bad:
            raise LockerError(400, "child allowed_recipients must be a subset of the parent's")
        allowed = allowed or list(parent["allowed_recipients"])
    blocked = sorted(set(_addrs(body.get("blocked_recipients"), "blocked_recipients")) | set(parent["blocked_recipients"]))
    left_days = max(1, int((parent["expires"] - time.time()) // 86400))
    days = min(int(body.get("ttl_days") or left_days), left_days)
    period = str(body.get("period") or parent["period"]).lower()
    c = budget_create({"name": body.get("name"), "cap_usd": cap, "period": period, "per_tx_max_usd": ptx,
                       "escalate_above_usd": body.get("escalate_above_usd") if body.get("escalate_above_usd") is not None else parent["escalate_above_usd"],
                       "allowed_recipients": allowed, "blocked_recipients": blocked}, ttl_days=days)
    child = _kv("GET", c["budget_id"])
    child["parent"] = parent_id
    child["expires"] = min(child["expires"], parent["expires"])
    v = body.get("velocity_max_per_hour")
    child["velocity_max_per_hour"] = int(v) if v not in (None, "") else parent.get("velocity_max_per_hour")
    _kv("PUT", c["budget_id"], child)
    return {**c, "parent": parent_id, "depth": depth, "expires_at": child["expires"],
            "inherited": {"per_tx_max_usd": ptx, "allowed_recipients": allowed, "blocked_recipients": blocked,
                          "velocity_max_per_hour": child["velocity_max_per_hour"]},
            "note": "Every spend from this child is also checked against and counted in its parent(s). The parent's owner sees it as by_child in budget/status."}


def budget_release(bid, key, spend_id, reason=None):
    """Give a recorded spend back to the cap (the purchase failed, was refunded, or never happened)."""
    rec, role = _load(bid, key)
    for s in rec["spends"]:
        if s["id"] == spend_id:
            if s["status"] == "released":
                return {"released": True, "already": True, "spend_id": spend_id, **_summary(rec, int(time.time()))}
            s.update({"status": "released", "released_at": int(time.time()), "release_reason": str(reason or "")[:200] or None,
                      "released_by": role})
            _kv("PUT", bid, rec)
            try:
                for _, anc in _ancestors(rec, int(time.time())):
                    for x in anc["spends"]:
                        if x["id"] == spend_id and x["status"] == "spent":
                            x.update({"status": "released", "released_at": int(time.time()), "released_by": "child:" + bid})
                    _kv("PUT", anc["_id"], {k: v for k, v in anc.items() if k != "_id"})
            except LockerError:
                pass
            return {"released": True, "spend_id": spend_id, "amount_usd": s["amount_usd"], **_summary(rec, int(time.time()))}
    raise LockerError(404, "no such spend_id in this budget")


def budget_freeze(bid, key, frozen=True):
    rec, role = _load(bid, key)
    if role != "owner":
        raise LockerError(403, "only the owner_key can freeze or unfreeze")
    rec["frozen"] = bool(frozen)
    _kv("PUT", bid, rec)
    return {"frozen": rec["frozen"], **_summary(rec, int(time.time()))}


def budget_status(bid, key, limit=50):
    rec, role = _load(bid, key)
    now = int(time.time())
    w = _window(rec["period"], now)
    cur = [s for s in rec["spends"] if _window(rec["period"], s["at"]) == w and s["status"] == "spent"]
    by_agent, by_rcpt = {}, {}
    by_child = {}
    for s in cur:
        if str(s.get("by") or "").startswith("child:"):
            c = s["by"][6:]
            by_child[c] = round(by_child.get(c, 0) + s["amount_usd"], 6)
        by_agent[s.get("agent") or "?"] = round(by_agent.get(s.get("agent") or "?", 0) + s["amount_usd"], 6)
        by_rcpt[s.get("recipient") or "?"] = round(by_rcpt.get(s.get("recipient") or "?", 0) + s["amount_usd"], 6)
    lim = max(1, min(200, int(limit or 50)))
    return {"budget_id": bid, "name": rec["name"], "role": role, **_summary(rec, now),
            "per_tx_max_usd": rec["per_tx_max_usd"], "escalate_above_usd": rec["escalate_above_usd"],
            "purchases_this_window": len(cur), "by_agent": by_agent, "by_recipient": by_rcpt, "by_child": by_child,
            "parent": rec.get("parent"), "velocity_max_per_hour": rec.get("velocity_max_per_hour"),
            "recent": [{k: v for k, v in s.items() if k != "idempotency_key"} for s in rec["spends"][-lim:]][::-1],
            "expires_at": rec["expires"]}


# ---------------------------------------------------------------- Payment Verify
def _decode_payment_response(h):
    h = (h or "").strip()
    try:
        d = json.loads(base64.b64decode(h + "=" * (-len(h) % 4)))
    except Exception:
        try:
            d = json.loads(h)
        except Exception:
            return None, None
    if not isinstance(d, dict):
        return None, None
    return (d.get("transaction") or d.get("txHash") or d.get("transactionHash")), d


GATEWAY = "https://gateway-api.circle.com/v1/x402/transfers"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NONCE_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
GW_VERDICT = {"received": "PENDING", "batched": "PENDING", "confirmed": "CONFIRMED", "completed": "SETTLED", "failed": "FAILED"}


def _gateway_verify(body, nonce=None, transfer_id=None):
    """Circle Gateway batched x402 payments (scheme exact / extra.name GatewayWalletBatched) have no per-payment tx:
    look the payment up in Circle's public transfer record by EIP-3009 nonce or transfer id (11-21; ~12% of Bazaar
    payment options use Gateway batching). Circle: credit on 'confirmed', act onchain on 'completed', 'failed' was never charged."""
    import urllib.request
    url = f"{GATEWAY}/{transfer_id}" if transfer_id else f"{GATEWAY}?nonce={nonce}"
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "OMENZ Payment Verify"}), timeout=20))
    except Exception as e:
        return {"verdict": "UNAVAILABLE", "reasons": [f"Circle Gateway lookup failed ({type(e).__name__})"]}
    rows = [d] if transfer_id and d.get("id") else (d.get("transfers") or [])
    out = {"rail": "circle_gateway_batched", "lookup": {"nonce": nonce, "transfer_id": transfer_id},
           "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not rows:
        return {**out, "verdict": "NOT_FOUND", "reasons": ["Circle Gateway has no transfer with this nonce/id (not submitted, wrong id, or not a Gateway batched payment)"]}
    t = rows[0]
    amt = round(int(t.get("amount") or 0) / 1e6, 6)
    out.update(status=t.get("status"), transfer_id=t.get("id"), payer=(t.get("fromAddress") or "").lower(), payee=(t.get("toAddress") or "").lower(),
               amount_usd=amt, token=t.get("token"), network=t.get("sendingNetwork"), recipient_network=t.get("recipientNetwork"),
               batch_tx_hash=t.get("txHash"), created_at=t.get("createdAt"), updated_at=t.get("updatedAt"))
    verdict = GW_VERDICT.get(t.get("status"), "UNKNOWN")
    mism = []
    exp_to = str(body.get("expected_pay_to") or "").strip().lower() or None
    exp_from = str(body.get("expected_payer") or "").strip().lower() or None
    if exp_to and exp_to != out["payee"]:
        mism.append(f"payee {out['payee']} is not the expected {exp_to}")
    if exp_from and exp_from != out["payer"]:
        mism.append(f"payer {out['payer']} is not the expected {exp_from}")
    try:
        if body.get("expected_amount_usd") not in (None, "") and abs(float(body["expected_amount_usd"]) - amt) > 1e-6:
            mism.append(f"amount ${amt:g} is not the expected ${float(body['expected_amount_usd']):g}")
        if body.get("max_amount_usd") not in (None, "") and amt > float(body["max_amount_usd"]) + 1e-9:
            mism.append(f"amount ${amt:g} is above your max ${float(body['max_amount_usd']):g}")
    except (TypeError, ValueError):
        return {"verdict": "BAD_INPUT", "reasons": ["expected_amount_usd / max_amount_usd must be numbers"]}
    if mism and verdict in ("SETTLED", "CONFIRMED", "PENDING"):
        verdict = "MISMATCH"
    nxt = {"SETTLED": "settled onchain in a batch: safe for dependent onchain actions", "CONFIRMED": "Circle confirmed it: safe to credit; batch tx not final yet",
           "PENDING": "accepted by Gateway, waiting for the next batch: don't pay again; check later", "FAILED": "failed: Circle says it was never charged",
           "MISMATCH": "the payment exists but does not match what you expected", "UNKNOWN": "unrecognized status"}
    return {**out, "verdict": verdict, "mismatches": mism, "next": nxt.get(verdict)}


def pay_verify(body):
    """SETTLED / MISMATCH / PENDING / FAILED / NOT_FOUND / NO_USDC_TRANSFER for one x402 payment on Base."""
    import wallet
    body = body if isinstance(body, dict) else {}
    tx = str(body.get("tx_hash") or "").strip()
    decoded = None
    if not tx and body.get("payment_response"):
        tx, decoded = _decode_payment_response(body.get("payment_response"))
        tx = str(tx or "")
    gw_nonce = str(body.get("gateway_nonce") or body.get("nonce") or "").strip()
    gw_id = str(body.get("gateway_transfer_id") or "").strip().lower()
    if not gw_id and decoded and UUID_RE.match(str(decoded.get("transaction") or "").lower()):
        gw_id = str(decoded.get("transaction")).lower()   # Gateway settle responses carry a transfer UUID, not a tx hash
    if gw_id and UUID_RE.match(gw_id):
        return _gateway_verify(body, transfer_id=gw_id)
    if gw_nonce and NONCE_RE.match(gw_nonce) and not TXH.match(tx):
        return _gateway_verify(body, nonce=gw_nonce.lower())
    if not TXH.match(tx):
        return {"verdict": "BAD_INPUT", "reasons": ["send tx_hash (0x + 64 hex) or payment_response (the seller's PAYMENT-RESPONSE / X-PAYMENT-RESPONSE header); for Circle Gateway batched payments send gateway_nonce (the EIP-3009 nonce you signed) or gateway_transfer_id"]}
    exp_to = str(body.get("expected_pay_to") or "").strip().lower() or None
    exp_from = str(body.get("expected_payer") or "").strip().lower() or None
    for a, n in ((exp_to, "expected_pay_to"), (exp_from, "expected_payer")):
        if a and not ADDR.match(a):
            return {"verdict": "BAD_INPUT", "reasons": [f"{n} must be a 0x address"]}
    try:
        exp_amt = None if body.get("expected_amount_usd") in (None, "") else round(float(body["expected_amount_usd"]), 6)
        max_amt = None if body.get("max_amount_usd") in (None, "") else round(float(body["max_amount_usd"]), 6)
        min_conf = max(0, min(1000, int(body.get("min_confirmations") or 1)))
    except (TypeError, ValueError):
        return {"verdict": "BAD_INPUT", "reasons": ["expected_amount_usd / min_confirmations must be numbers"]}
    out = {"tx_hash": tx, "network": "base", "asset": "USDC", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "from_payment_response": decoded is not None}
    if decoded:
        out["payment_response"] = {k: decoded.get(k) for k in ("success", "network", "payer") if k in decoded}
    try:
        rcpt = wallet._rpc("eth_getTransactionReceipt", [tx])
        if rcpt is None:
            seen = wallet._rpc("eth_getTransactionByHash", [tx])
            return {**out, "verdict": "PENDING" if seen else "NOT_FOUND",
                    "reasons": ["transaction is known but not in a block yet" if seen else "no such transaction on Base (wrong network, or never broadcast)"]}
        head = int(wallet._rpc("eth_blockNumber", []), 16)
    except wallet.WalletError as e:
        return {**out, "verdict": "UNAVAILABLE", "reasons": [str(e)]}
    blk = int(rcpt["blockNumber"], 16)
    out.update({"block": blk, "confirmations": head - blk + 1, "tx_status": "success" if rcpt.get("status") == "0x1" else "reverted"})
    try:
        b = wallet._rpc("eth_getBlockByNumber", [rcpt["blockNumber"], False])
        out["settled_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(b["timestamp"], 16)))
    except Exception:
        pass
    if out["tx_status"] != "success":
        return {**out, "verdict": "FAILED", "reasons": ["the transaction reverted: no money moved"]}
    transfers = []
    for lg in rcpt.get("logs") or []:
        t = lg.get("topics") or []
        if (lg.get("address") or "").lower() == wallet.USDC and len(t) == 3 and t[0] == wallet.TRANSFER:
            transfers.append({"from": "0x" + t[1][-40:], "to": "0x" + t[2][-40:], "amount_usd": int(lg["data"], 16) / 1e6})
    out["usdc_transfers"] = transfers
    if not transfers:
        return {**out, "verdict": "NO_USDC_TRANSFER", "reasons": ["the transaction succeeded but moved no USDC on Base"]}
    cand = [x for x in transfers if (not exp_to or x["to"] == exp_to) and (not exp_from or x["from"] == exp_from)]
    reasons = []
    if not cand:
        reasons.append("no USDC transfer matches the expected payer/payee")
        cand = transfers
    pick = cand[0]
    if exp_amt is not None and abs(pick["amount_usd"] - exp_amt) > 1e-6:
        better = [x for x in cand if abs(x["amount_usd"] - exp_amt) <= 1e-6]
        if better:
            pick = better[0]
        else:
            reasons.append(f"amount {pick['amount_usd']} USDC, expected {exp_amt}")
    if max_amt is not None and pick["amount_usd"] > max_amt + 1e-6:
        reasons.append(f"amount {pick['amount_usd']} USDC is above the authorized maximum {max_amt} (upto scheme)")
    if out["confirmations"] < min_conf:
        return {**out, "payment": pick, "verdict": "PENDING", "reasons": [f"{out['confirmations']} confirmations, want {min_conf}"] + reasons}
    try:
        names = wallet._payee_names([pick["to"]])
        if names.get(pick["to"]):
            out["payee_runs"] = names[pick["to"]]
    except Exception:
        pass
    return {**out, "payment": pick, "verdict": "MISMATCH" if reasons else "SETTLED",
            "reasons": reasons or [f"{pick['amount_usd']} USDC moved from {pick['from']} to {pick['to']}"]}


# ---------------------------------------------------------------- Delivery Check
def _type(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _cmp_example(ex, got, path, out, depth=0):
    """Compare delivered JSON against the seller's example: same keys present, same kinds of values."""
    if depth > 8:
        return
    te, tg = _type(ex), _type(got)
    if te == "null":
        return
    if tg != te:
        out["type_mismatch"].append({"field": path or "$", "advertised": te, "delivered": tg})
        return
    if te == "object":
        for k, v in ex.items():
            p = f"{path}.{k}" if path else k
            if k not in got:
                out["missing"].append(p)
            else:
                out["checked"] += 1
                _cmp_example(v, got[k], p, out, depth + 1)
        out["extra"].extend((f"{path}.{k}" if path else k) for k in got if k not in ex)
    elif te == "array" and ex and isinstance(ex[0], (dict, list)):
        if not got:
            out["empty"].append(path or "$")
        else:
            _cmp_example(ex[0], got[0], f"{path}[0]", out, depth + 1)


def _cmp_schema(sc, got, path, out, depth=0):
    """Small JSON Schema subset: type, required, properties, items, enum, minItems, minLength."""
    if depth > 8 or not isinstance(sc, dict):
        return
    t = sc.get("type")
    tg = _type(got)
    ok_types = t if isinstance(t, list) else [t] if t else []
    ok_types = ["number" if x == "integer" else x for x in ok_types]
    if ok_types and tg not in ok_types:
        out["type_mismatch"].append({"field": path or "$", "advertised": t, "delivered": tg})
        return
    if "enum" in sc and got not in sc["enum"]:
        out["type_mismatch"].append({"field": path or "$", "advertised": f"one of {sc['enum'][:10]}", "delivered": got})
    if tg == "object":
        props = sc.get("properties") or {}
        for k in sc.get("required") or []:
            if k not in got:
                out["missing"].append(f"{path}.{k}" if path else k)
        for k, sub in props.items():
            if k in got:
                out["checked"] += 1
                _cmp_schema(sub, got[k], f"{path}.{k}" if path else k, out, depth + 1)
    elif tg == "array":
        if sc.get("minItems") and len(got) < sc["minItems"]:
            out["empty"].append(path or "$")
        if isinstance(sc.get("items"), dict) and got:
            _cmp_schema(sc["items"], got[0], f"{path}[0]", out, depth + 1)
    elif tg == "string" and sc.get("minLength") and len(got) < sc["minLength"]:
        out["empty"].append(path or "$")


def _advertised(url, method):
    import capability_card
    import x402_probe
    r = x402_probe._request(x402_probe._public_url(url), method)
    if r["status"] != 402:
        return None, None, f"HTTP {r['status']} (no 402 to read the seller's advertised output from)"
    d = capability_card._ext_from_402(r)
    baz = (d.get("extensions") or {}).get("bazaar") or {}
    info_out = (baz.get("info") or {}).get("output") or {}
    acc = (d.get("accepts") or [{}])[0] if isinstance(d.get("accepts"), list) else {}
    os_ = acc.get("outputSchema") if isinstance(acc, dict) else None
    schema = None
    if isinstance(os_, dict):
        cand = os_.get("output") if isinstance(os_.get("output"), dict) else os_
        if cand.get("type") or cand.get("properties"):
            schema = cand
    example = info_out.get("example") if isinstance(info_out, dict) else None
    return example, schema, None


def delivery_check(body):
    body = body if isinstance(body, dict) else {}
    got = body.get("delivered")
    if isinstance(got, str):
        try:
            got = json.loads(got)
        except Exception:
            pass
    if got is None:
        return {"verdict": "BAD_INPUT", "reasons": ["send delivered: the JSON the seller returned after you paid"]}
    schema, example, src = body.get("schema"), body.get("example"), "caller"
    if not isinstance(schema, dict):
        schema = None
    if schema is None and example is None:
        url = str(body.get("url") or "").strip()
        if not url:
            return {"verdict": "BAD_INPUT", "reasons": ["send url (+ method) of the paid endpoint, or your own schema / example"]}
        import x402_probe
        try:
            example, schema, why = _advertised(url, str(body.get("method") or "GET").upper())
        except x402_probe.Refused as e:
            return {"verdict": "BAD_INPUT", "reasons": [f"url refused: {e}"]}
        if why:
            return {"verdict": "NO_CONTRACT", "reasons": [why]}
        src = "seller_x402_discovery"
        if schema is None and example is None:
            return {"verdict": "NO_CONTRACT", "source": src,
                    "reasons": ["the seller's 402 advertises no output example or schema, so there is nothing to hold them to; send your own schema"]}
    out = {"missing": [], "type_mismatch": [], "empty": [], "extra": [], "checked": 0}
    if schema is not None:
        _cmp_schema(schema, got, "", out)
        basis = "schema"
    else:
        _cmp_example(example, got, "", out)
        basis = "example"
    err_like = isinstance(got, dict) and any(k in got for k in ("error", "errors")) and \
        (not isinstance(example, dict) or not any(k in example for k in ("error", "errors")))
    must = body.get("must_have") if isinstance(body.get("must_have"), list) else []
    for f in must[:50]:
        cur, ok = got, True
        for part in str(f).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if not ok and str(f) not in out["missing"]:
            out["missing"].append(str(f))
        elif ok and cur in (None, "", [], {}):
            out["empty"].append(str(f))
    problems = len(out["missing"]) + len(out["type_mismatch"]) + len(out["empty"]) + (3 if err_like else 0)
    total = max(1, out["checked"] + len(out["missing"]))
    if problems == 0:
        verdict = "MATCH"
    elif err_like or not out["checked"] or problems >= total / 2:
        verdict = "MISMATCH"
    else:
        verdict = "PARTIAL"
    reasons = []
    if err_like:
        reasons.append("the response looks like an error body, not the advertised result")
    if out["missing"]:
        reasons.append(f"missing {len(out['missing'])} advertised field(s): {', '.join(out['missing'][:10])}")
    if out["type_mismatch"]:
        reasons.append(f"{len(out['type_mismatch'])} field(s) of the wrong kind")
    if out["empty"]:
        reasons.append(f"empty: {', '.join(out['empty'][:10])}")
    return {"verdict": verdict, "basis": basis, "source": src, "fields_checked": out["checked"],
            "missing": out["missing"][:50], "type_mismatch": out["type_mismatch"][:50], "empty": out["empty"][:50],
            "extra_fields": out["extra"][:30], "reasons": reasons or ["the response has every advertised field, with the advertised kinds of values"],
            "next": None if verdict == "MATCH" else "Keep this as evidence: finance/refund-request turns it into a structured refund ask; receipt/put stores it."}


# ---------------------------------------------------------------- Cheapest Working Tool
def cheapest_working(q, max_price_usd=None, network=None, want=3, exclude=None, min_match=0.75):
    """Cheapest providers that ANSWER right now: matches sorted by price, live-probed (unpaid) in that order."""
    import market
    import x402_probe
    try:
        want = max(1, min(int(want or 3), 5))
        min_match = max(0.5, min(float(min_match or 0.75), 1.0))
    except (TypeError, ValueError):
        return {"error": "want must be an integer, min_match a number 0.5-1"}
    f = market.find(q, max_price_usd=max_price_usd, network=network, exclude=exclude, limit=25, live_check=0)
    if f.get("error"):
        return f
    cands = sorted([r for r in f["results"] if r.get("price_usd") is not None and r.get("match", 0) >= min_match],
                   key=lambda r: (r["price_usd"], -(r.get("payers_30d") or 0)))
    working, dead, probes = [], [], 0
    for r in cands:
        if len(working) >= want or probes >= 8:
            break
        probes += 1
        qt = x402_probe.quote(r["url"], r["method"])
        live = qt.get("cheapest_usd")
        if qt["status"] == "quoted" and live is not None and (max_price_usd in (None, "") or live <= float(max_price_usd) + 1e-12):
            working.append({**r, "live_price_usd": live, "price_drift": abs(live - r["price_usd"]) > 1e-9,
                            "latency_ms": qt.get("latency_ms"), "pay_to": (qt.get("options") or [{}])[0].get("pay_to")})
        else:
            dead.append({"url": r["url"], "listed_price_usd": r["price_usd"], "why": qt.get("status") if live is None else f"live price {live} over your max"})
    working.sort(key=lambda r: (r["live_price_usd"], r.get("latency_ms") or 9e9))
    return {"version": VERSION, "query": q, "checked_at": f["checked_at"], "paid_targets": False,
            "pick": working[0] if working else None, "runners_up": working[1:], "skipped_not_working": dead,
            "candidates_matched": len(cands), "probed": probes,
            "note": "sorted by LIVE price (unpaid probe just now), then latency; listed-but-dead providers are skipped and shown. "
                    "Next: authorize (GO/STOP + signed authorization) before paying the pick."}


# ---------------------------------------------------------------- Spend Receipt
def spend_receipt(body):
    """One signed receipt for one purchase: what was bought, why, what it cost (verified on-chain), what came back."""
    import contracts
    body = body if isinstance(body, dict) else {}
    url = str(body.get("url") or "").strip()
    if not url:
        return {"verdict": "BAD_INPUT", "reasons": ["send url (+ method) of what you bought"]}
    pv = pay_verify({k: body.get(k) for k in ("tx_hash", "payment_response", "expected_pay_to", "expected_payer",
                                                 "expected_amount_usd", "max_amount_usd", "min_confirmations")})
    if pv["verdict"] == "BAD_INPUT":
        return pv
    dc = delivery_check({k: body.get(k) for k in ("url", "method", "delivered", "schema", "example", "must_have")}) \
        if body.get("delivered") is not None else {"verdict": "NOT_SUBMITTED", "reasons": ["no delivered response sent"]}
    paid_ok = pv["verdict"] == "SETTLED"
    got_ok = dc["verdict"] in ("MATCH", "NO_CONTRACT")
    if not paid_ok:
        verdict = "PAYMENT_NOT_CONFIRMED"
    elif dc["verdict"] in ("MISMATCH", "PARTIAL"):
        verdict = "PAID_NOT_DELIVERED" if dc["verdict"] == "MISMATCH" else "PAID_PARTLY_DELIVERED"
    elif got_ok:
        verdict = "GOOD_BUY" if dc["verdict"] == "MATCH" else "PAID_DELIVERY_UNCHECKED"
    else:
        verdict = "PAID_DELIVERY_UNCHECKED"
    delivered = body.get("delivered")
    receipt = {"schema": "omenz.spend-receipt.v0", "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "issuer": "OMENZ (www.omenz.org)", "agent": str(body.get("agent") or "")[:80] or None,
               "bought": {"url": url[:500], "method": str(body.get("method") or "GET").upper()},
               "why": str(body.get("purpose") or "")[:300] or None, "job_id": str(body.get("job_id") or "")[:120] or None,
               "payment": {"verdict": pv["verdict"], "tx_hash": pv.get("tx_hash"), "network": "base", "asset": "USDC",
                           **({k: pv["payment"][k] for k in ("from", "to", "amount_usd")} if pv.get("payment") else {}),
                           "confirmations": pv.get("confirmations"), "settled_at": pv.get("settled_at")},
               "delivery": {"verdict": dc["verdict"], "missing": dc.get("missing", [])[:20], "type_mismatch": len(dc.get("type_mismatch") or []),
                            "delivered_sha256": hashlib.sha256(json.dumps(delivered, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                            if delivered is not None else None},
               "verdict": verdict}
    try:
        token = contracts._sign(receipt)
    except Exception:
        token = None
    return {**receipt, "reasons": (pv.get("reasons") or [])[:3] + (dc.get("reasons") or [])[:3], "signed": token,
            "verify": "Ed25519 over the token body; public key at GET /api/tollbooth/v1/passport/key",
            "next": {"GOOD_BUY": "File it: receipt/put or ledger/append.",
                     "PAID_NOT_DELIVERED": "This receipt is your evidence: finance/refund-request.",
                     "PAID_PARTLY_DELIVERED": "Evidence for a partial refund: finance/refund-request.",
                     "PAYMENT_NOT_CONFIRMED": "Don't count this as spent yet; re-check later or budget/release it."}.get(verdict)}
