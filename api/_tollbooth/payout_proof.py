"""x402 payout proofs (draft spec x402payto1, benmcalillycreative/x402-trust-board; raised in x402-foundation/wg-domain-discovery#17).
Does the payTo an agent is about to pay really belong to the domain? (2026-11-22, OMENZ ecosystem watch find.)

Checks, per the draft: DNS TXT at _x402-payto.<host> and each parent up to the registrable domain (shared-hosting
parents ignored), and https://<host>/.well-known/x402-payto.json (no redirects, 64 KB cap, 20 entries). EVM signatures
(EIP-191 personal_sign, EOA ecrecover) verified when present; smart-wallet (ERC-1271) signatures reported as unverified.
A missing proof never counts against a seller; a proof that EXCLUDES the address being paid is the red flag.
"""
import json
import urllib.request

import domain_check

SHARED = {"onrender.com", "workers.dev", "vercel.app", "netlify.app", "herokuapp.com", "github.io", "pages.dev", "fly.dev",
          "railway.app", "web.app", "firebaseapp.com", "azurewebsites.net", "cloudfront.net", "deno.dev", "replit.app", "glitch.me"}


def _parse(txt):
    kv = {}
    for part in txt.replace('" "', "").strip('"').split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k.strip().lower()] = v.strip()
    return kv if kv.get("v") == "x402payto1" and kv.get("a") else None


def _sig_ok(domain, addr, issued, sig):
    if not (sig and issued and addr.startswith("0x")):
        return None
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
        msg = f"x402 payout verification\n\nDomain: {domain.lower()}\nPay-to: {addr.lower()}\nIssued: {issued}"
        rec = Account.recover_message(encode_defunct(text=msg), signature=sig)
        return rec.lower() == addr.lower()
    except Exception:
        return None  # unverifiable here (e.g. ERC-1271 smart wallet): not counted as invalid


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def check(host, pay_to=None):
    host = (host or "").lower().strip(".")
    pay = (pay_to or "").strip()
    found = []
    labels = host.split(".")
    base = domain_check._registrable(host)
    names = [".".join(labels[i:]) for i in range(len(labels)) if len(".".join(labels[i:])) >= len(base)]
    for name in names:
        if name in SHARED or any(name.endswith("." + s) and name.count(".") <= s.count(".") for s in SHARED):
            continue
        if any(name == s for s in SHARED):
            continue
        for t in domain_check._dns("_x402-payto." + name, "TXT") or []:
            kv = _parse(t)
            if kv:
                found.append({"where": "dns", "domain": name, "address": kv["a"], "issued": kv.get("d"),
                              "signed": bool(kv.get("s")), "signature_valid": _sig_ok(name, kv["a"], kv.get("d"), kv.get("s"))})
    try:
        op = urllib.request.build_opener(_NoRedirect)
        r = op.open(urllib.request.Request(f"https://{host}/.well-known/x402-payto.json", headers={"User-Agent": "OMENZ payout-proof check"}), timeout=5)
        if r.status == 200:
            d = json.loads(r.read(65536))
            if str(d.get("domain", "")).lower() == host:
                for e in (d.get("payTo") or [])[:20]:
                    a = e if isinstance(e, str) else e.get("address")
                    if a:
                        iss, sg = (None, None) if isinstance(e, str) else (e.get("issued"), e.get("signature"))
                        found.append({"where": "site", "domain": host, "address": a, "issued": iss, "signed": bool(sg),
                                      "signature_valid": _sig_ok(host, a, iss, sg)})
    except Exception:
        pass
    if not found:
        return {"verdict": "NO_PROOF", "proofs": [], "note": "no payout proof published (optional; not a negative signal)"}
    if not pay:
        return {"verdict": "PROOFS_PUBLISHED", "proofs": found}
    match = [f for f in found if f["address"].lower() == pay.lower()]
    if not match:
        return {"verdict": "MISMATCH", "proofs": found,
                "note": "the domain publishes payout addresses and this payTo is NOT one of them: possible hijacked server or wrong address"}
    best = sorted(match, key=lambda f: (f["where"] != "dns", f["signature_valid"] is not True))[0]
    level = best["where"] + ("_signed" if best["signature_valid"] else "")
    return {"verdict": "PROVEN", "level": level, "proofs": found}
