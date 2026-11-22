"""OMENZ FX Rates: convert money between currencies at the official reference rate (2026-11-22).

Evidence (11-22 category scan): FX / currency-conversion x402 services, 808 paying wallets (~5 calls each).
Source: European Central Bank euro foreign exchange reference rates (free, official, ~30 currencies, published
around 16:00 CET on TARGET business days). Deterministic: same date + amount = same answer; rate date always shown.
Not a trading quote: ECB rates are for information, not live market prices.
"""
import time
import urllib.request
import xml.etree.ElementTree as ET

VERSION = "0.1.0"
DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
HIST = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
_CACHE = {}


def _load(url):
    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    xml = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "OMENZ FX Rates"}), timeout=10).read()
    days = {}
    for day in ET.fromstring(xml).iter("{%s}Cube" % NS["e"]):
        t = day.get("time")
        if t:
            days[t] = {"EUR": 1.0, **{c.get("currency"): float(c.get("rate")) for c in day}}
    _CACHE[url] = (time.time(), days)
    return days


def convert(amount=None, from_cur="USD", to_cur="EUR", date=None):
    out = {"service": "OMENZ FX Rates", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "European Central Bank euro reference rates", "not_a_trading_quote": True}
    f, t = str(from_cur or "").strip().upper(), str(to_cur or "").strip().upper()
    try:
        amt = float(amount) if amount not in (None, "") else 1.0
    except (TypeError, ValueError):
        return {**out, "error": "amount must be a number"}
    if not (0 <= amt <= 1e12):
        return {**out, "error": "amount must be between 0 and 1e12"}
    try:
        days = _load(HIST if date else DAILY)
    except Exception as e:
        return {**out, "error": f"ECB feed unavailable ({type(e).__name__}); try again shortly"}
    if not days:
        return {**out, "error": "no rates published"}
    if date:
        d = str(date)[:10]
        use = max((k for k in days if k <= d), default=None)
        if not use:
            return {**out, "error": "date must be within the last ~90 days (YYYY-MM-DD)"}
    else:
        use = max(days)
    rates = days[use]
    bad = [c for c in (f, t) if c not in rates]
    if bad:
        return {**out, "error": f"unsupported currency {', '.join(bad)}", "supported": sorted(rates)}
    rate = rates[t] / rates[f]
    res = {**out, "amount": amt, "from": f, "to": t, "rate": round(rate, 8), "result": round(amt * rate, 6),
           "inverse_rate": round(1 / rate, 8), "rate_date": use, "supported": sorted(rates)}
    if date and use != str(date)[:10]:
        res["note"] = f"no ECB rate on {str(date)[:10]} (weekend/holiday); used the previous business day {use}"
    if not date:
        age = (time.time() - time.mktime(time.strptime(use, "%Y-%m-%d"))) / 86400
        if age > 4:
            res["note"] = f"latest ECB rate is from {use}"
    return res
