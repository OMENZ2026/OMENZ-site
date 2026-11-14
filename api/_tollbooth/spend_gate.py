"""OMENZ Spend Gate: ALLOW / DENY / ESCALATE before an agent spends money, against its owner's policy.

Signals: Hayes (agents move capital through protocols under guardrails) + Matt Cole (spend must clear a hurdle rate),
and our own rule set (spend caps, founder-only approvals, recipient checks) turned outward.

Stateless and deterministic: the agent sends its policy and the proposed spend each call (it keeps its own running
totals, e.g. in the Agent Locker or Receipt Locker). Nothing is stored. No AI calls.

policy (all optional):
  max_per_tx_usd, daily_cap_usd, monthly_cap_usd, escalate_above_usd,
  allowed_recipients[], blocked_recipients[], allowed_categories[], blocked_categories[],
  allowed_networks[], require_known_recipient (bool),
  hurdle: {min_return_multiple (e.g. 1.5 = expected value >= 1.5x cost), escalate_if_unknown (bool)}
spend: amount_usd (required), recipient, category, network, purpose, expected_value_usd,
  spent_today_usd, spent_month_usd
"""
import time

VERSION = "0.1.0"


def _num(v, name, errors):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        errors.append(f"{name} must be a number")
        return None
    if f < 0:
        errors.append(f"{name} must not be negative")
        return None
    return f


def _low(xs):
    return {str(x).strip().lower() for x in (xs or []) if str(x).strip()}


def check(policy, spend):
    policy, spend = policy or {}, spend or {}
    out = {"version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stored": False}
    errors = []
    amt = _num(spend.get("amount_usd"), "spend.amount_usd", errors)
    if amt is None and not errors:
        errors.append("spend.amount_usd is required")
    lim = {k: _num(policy.get(k), "policy." + k, errors)
           for k in ("max_per_tx_usd", "daily_cap_usd", "monthly_cap_usd", "escalate_above_usd")}
    today = _num(spend.get("spent_today_usd"), "spend.spent_today_usd", errors) or 0.0
    month = _num(spend.get("spent_month_usd"), "spend.spent_month_usd", errors) or 0.0
    ev = _num(spend.get("expected_value_usd"), "spend.expected_value_usd", errors)
    hurdle = policy.get("hurdle") or {}
    mult = _num(hurdle.get("min_return_multiple"), "policy.hurdle.min_return_multiple", errors)
    if errors:
        return {**out, "decision": "ERROR", "errors": errors}

    deny, esc, passed = [], [], []
    rec = str(spend.get("recipient") or "").strip().lower()
    cat = str(spend.get("category") or "").strip().lower()
    net = str(spend.get("network") or "").strip().lower()

    if lim["max_per_tx_usd"] is not None:
        (deny.append(f"${amt:g} is over the per-transaction cap ${lim['max_per_tx_usd']:g}")
         if amt > lim["max_per_tx_usd"] + 1e-12 else passed.append("per-transaction cap"))
    if lim["daily_cap_usd"] is not None:
        left = lim["daily_cap_usd"] - today
        (deny.append(f"would bring today to ${today + amt:g}, over the daily cap ${lim['daily_cap_usd']:g}")
         if amt > left + 1e-12 else passed.append("daily cap"))
        if "spent_today_usd" not in spend:
            esc.append("daily cap set but spent_today_usd not provided")
    if lim["monthly_cap_usd"] is not None:
        left = lim["monthly_cap_usd"] - month
        (deny.append(f"would bring this month to ${month + amt:g}, over the monthly cap ${lim['monthly_cap_usd']:g}")
         if amt > left + 1e-12 else passed.append("monthly cap"))
        if "spent_month_usd" not in spend:
            esc.append("monthly cap set but spent_month_usd not provided")

    blocked_r, allowed_r = _low(policy.get("blocked_recipients")), _low(policy.get("allowed_recipients"))
    if rec and rec in blocked_r:
        deny.append("recipient is on the blocked list")
    elif allowed_r:
        if not rec:
            esc.append("policy has a recipient allowlist but no recipient was given")
        elif rec in allowed_r:
            passed.append("recipient allowlist")
        elif policy.get("require_known_recipient"):
            deny.append("recipient is not on the allowlist")
        else:
            esc.append("recipient is not on the allowlist")
    blocked_c, allowed_c = _low(policy.get("blocked_categories")), _low(policy.get("allowed_categories"))
    if cat and cat in blocked_c:
        deny.append(f"category '{cat}' is blocked")
    elif allowed_c:
        if cat in allowed_c:
            passed.append("category allowlist")
        else:
            esc.append(f"category '{cat or 'none'}' is not on the allowed list")
    nets = _low(policy.get("allowed_networks"))
    if nets:
        (passed.append("network") if net in nets else deny.append(f"network '{net or 'none'}' is not allowed"))

    if mult is not None:
        if ev is None:
            (esc if hurdle.get("escalate_if_unknown", True) else passed).append(
                "no expected_value_usd given for the hurdle check" if hurdle.get("escalate_if_unknown", True) else "hurdle (skipped: no value given)")
        elif amt > 0 and ev / amt + 1e-12 < mult:
            deny.append(f"expected return {ev / amt:.2f}x is below the hurdle {mult:g}x")
        else:
            passed.append("hurdle")
    if lim["escalate_above_usd"] is not None and amt > lim["escalate_above_usd"] + 1e-12:
        esc.append(f"${amt:g} is above the owner's approval threshold ${lim['escalate_above_usd']:g}")

    decision = "DENY" if deny else "ESCALATE" if esc else "ALLOW"
    res = {**out, "decision": decision, "amount_usd": amt, "deny_reasons": deny, "escalate_reasons": esc, "passed": passed}
    if lim["daily_cap_usd"] is not None:
        res["remaining_today_usd"] = round(max(0.0, lim["daily_cap_usd"] - today - (amt if decision == "ALLOW" else 0)), 6)
    if lim["monthly_cap_usd"] is not None:
        res["remaining_month_usd"] = round(max(0.0, lim["monthly_cap_usd"] - month - (amt if decision == "ALLOW" else 0)), 6)
    if not any(policy.get(k) for k in ("max_per_tx_usd", "daily_cap_usd", "monthly_cap_usd", "allowed_recipients",
                                       "allowed_categories", "allowed_networks", "hurdle", "escalate_above_usd")):
        res["warning"] = "policy sets no limits: everything not blocked is allowed"
    return res
