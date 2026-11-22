"""OMENZ Business Days: is this a working day here, and when is N business days from now? (2026-11-22)

Evidence (11-22 category scan): holiday / business-day x402 services, 516 paying wallets. Deterministic and offline:
python `holidays` library (MIT; public holidays for 200+ countries and their states/provinces). Weekends follow the
country's own weekend (e.g. Fri-Sat in some Gulf states) when the library knows it, else Sat-Sun.
Useful for deadlines, delivery promises, SLA clocks, payment settlement dates, scheduling.
"""
import datetime as dt
import time

VERSION = "0.1.0"


def check(country="US", date=None, add=None, subdiv=None):
    out = {"service": "OMENZ Business Days", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    import holidays
    cc = str(country or "US").strip().upper()
    sd = str(subdiv).strip().upper() if subdiv else None
    try:
        d = dt.date.fromisoformat(str(date)[:10]) if date else dt.datetime.now(dt.timezone.utc).date()
    except ValueError:
        return {**out, "error": "date must be YYYY-MM-DD"}
    try:
        n = int(add) if add not in (None, "") else None
    except (TypeError, ValueError):
        return {**out, "error": "add must be a whole number of business days (negative counts backwards)"}
    if n is not None and abs(n) > 400:
        return {**out, "error": "add must be between -400 and 400"}
    try:
        cal = holidays.country_holidays(cc, subdiv=sd, years=range(d.year - 1, d.year + 3))
    except (NotImplementedError, KeyError):
        return {**out, "error": f"unsupported country {cc}" + (f" / subdivision {sd}" if sd else ""),
                "supported_countries": sorted(holidays.list_supported_countries())}
    weekend = set(getattr(cal, "weekend", None) or {5, 6})

    def is_bd(x):
        return x.weekday() not in weekend and x not in cal

    def step(x, k):
        s = 1 if k >= 0 else -1
        left = abs(k)
        while left:
            x += dt.timedelta(days=s)
            if is_bd(x):
                left -= 1
        return x
    nxt = d + dt.timedelta(days=1)
    while not is_bd(nxt):
        nxt += dt.timedelta(days=1)
    upcoming = sorted((h, nm) for h, nm in cal.items() if d <= h <= d + dt.timedelta(days=120))[:6]
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    res = {**out, "country": cc, "subdivision": sd, "date": d.isoformat(), "weekday": names[d.weekday()],
           "is_business_day": is_bd(d), "holiday": cal.get(d), "is_weekend": d.weekday() in weekend,
           "weekend_days": [names[w] for w in sorted(weekend)], "next_business_day": nxt.isoformat(),
           "upcoming_holidays": [{"date": h.isoformat(), "name": nm} for h, nm in upcoming],
           "source": "python holidays library (public holidays; regional/bank-only closures may differ)"}
    if n is not None:
        res["add_business_days"] = n
        res["result_date"] = step(d, n).isoformat()
    return res
