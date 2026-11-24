"""OMENZ Address Screen: is this crypto address sanctioned, and what is it? One GET, any chain (2026-11-24).

Demand (market index 11-24): sanctions / OFAC / AML address screening = 418 endpoints, 226 sellers, 844 payers in 30 days.
OMENZ already screened payees inside Send Check / Authorize (EVM only, POST); buyers call a simple GET for one address.
This screens ANY chain's address against every digital-currency address on the US Treasury OFAC SDN list (refreshed
weekly), detects the address format, and for EVM addresses says what it is on Base (plain wallet, contract, EIP-7702).
Exact-match list screening, not a risk model. Not legal advice.
"""
import json
import os
import re
import time

VERSION = "0.1.0"
_DATA = None
FORMATS = [  # (name, regex) checked in order
    ("evm", re.compile(r"^0x[0-9a-fA-F]{40}$")),
    ("bitcoin", re.compile(r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")),
    ("tron", re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")),
    ("litecoin", re.compile(r"^(ltc1[02-9ac-hj-np-z]{11,71}|[LM][1-9A-HJ-NP-Za-km-z]{26,33})$")),
    ("monero", re.compile(r"^[48][1-9A-HJ-NP-Za-km-z]{94,105}$")),
    ("solana", re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")),
]


def _load():
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ofac_all.json"), encoding="utf-8"))
        except Exception:
            _DATA = {"addresses": {}, "fetched_at": None, "count": 0}
    return _DATA


def screen(address):
    a = str(address or "").strip()
    out = {"service": "OMENZ Address Screen", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not a or len(a) > 120 or not re.match(r"^[A-Za-z0-9]+$", a):
        return {**out, "error": "send address= (one crypto address, letters and digits only)"}
    fmt = next((n for n, rx in FORMATS if rx.match(a)), "unknown")
    d = _load()
    key = a.lower() if fmt == "evm" else a
    hit = d["addresses"].get(key)
    res = {**out, "address": a, "format": fmt, "sanctioned": bool(hit),
           "verdict": "BLOCK" if hit else "CLEAR",
           "match": {"list": "OFAC SDN (US Treasury)", "entity": hit["name"], "listed_as": hit["chains"]} if hit else None,
           "list": {"source": "OFAC SDN digital currency addresses, all chains", "addresses_screened": d.get("count", 0), "list_date": d.get("fetched_at")}}
    if fmt == "evm":
        try:
            import chain_tools as ct
            code = ct._rpc(ct.BASE_RPCS, "eth_getCode", [a, "latest"])
            res["on_base"] = {"kind": "plain wallet (EOA)" if code in ("0x", "0x0", None) else
                              ("EIP-7702 delegated account" if str(code).startswith("0xef0100") else "contract")}
        except Exception:
            res["on_base"] = {"kind": "unknown (Base RPC unavailable)"}
    if fmt == "unknown":
        res["note"] = "address format not recognised; screened by exact match anyway"
    res["limits"] = "Exact match against OFAC's published addresses only: CLEAR is not a clean bill of health (no cluster or exposure analysis). Not legal advice."
    return res
