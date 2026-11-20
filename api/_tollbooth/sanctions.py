"""Sanctions screening for payees (competitive response 2026-11-20). OFAC SDN EVM addresses, refreshed weekly by
omenz-stack/scripts/ofac_refresh.py into ofac_evm.json. A listed payTo makes Authorize/Guard DECLINE. Not legal advice."""
import json
import os

_DATA = None


def _load():
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ofac_evm.json"), encoding="utf-8"))
        except Exception:
            _DATA = {"addresses": {}, "fetched_at": None, "count": 0}
    return _DATA


def check(address):
    d = _load()
    a = str(address or "").lower()
    hit = d["addresses"].get(a)
    return {"listed": bool(hit), "list": "OFAC SDN (US Treasury)", "entity": hit["name"] if hit else None,
            "chains": hit["chains"] if hit else None, "list_date": d.get("fetched_at"), "addresses_screened": d.get("count", 0)}
