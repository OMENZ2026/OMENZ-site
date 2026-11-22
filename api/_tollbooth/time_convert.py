"""OMENZ Time Zones: what time is it there, and is it a good time to reach them? (2026-11-22)

Evidence (11-22 category scan): timezone x402 services, 389 paying wallets. Deterministic: IANA time zone database
(python zoneinfo + tzdata), daylight-saving aware. Converts a time between zones, gives "now" anywhere, UTC offsets,
whether DST is in effect, and whether the local time falls inside business hours (default 09:00-17:00, Mon-Fri).
"""
import datetime as dt
import time

VERSION = "0.1.0"
ALIASES = {"PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PT": "America/Los_Angeles", "MST": "America/Denver",
           "MT": "America/Denver", "CST": "America/Chicago", "CT": "America/Chicago", "EST": "America/New_York", "EDT": "America/New_York",
           "ET": "America/New_York", "GMT": "Europe/London", "BST": "Europe/London", "CET": "Europe/Paris", "IST": "Asia/Kolkata",
           "JST": "Asia/Tokyo", "AEST": "Australia/Sydney", "UTC": "UTC", "Z": "UTC"}


def _zone(name):
    from zoneinfo import ZoneInfo
    n = str(name or "UTC").strip()
    return ZoneInfo(ALIASES.get(n.upper(), n)), ALIASES.get(n.upper(), n)


def _info(t, label, start=9, end=17):
    off = t.utcoffset()
    h = off.total_seconds() / 3600 if off is not None else 0
    return {"zone": label, "local": t.strftime("%Y-%m-%d %H:%M"), "weekday": t.strftime("%a"), "utc_offset": f"{'+' if h >= 0 else '-'}{abs(int(h)):02d}:{int(round(abs(h) % 1 * 60)):02d}",
            "dst": bool(t.dst()), "abbreviation": t.tzname(),
            "business_hours": t.weekday() < 5 and start <= t.hour < end}


def convert(time_str=None, from_tz="UTC", to_tz=None, start=9, end=17):
    out = {"service": "OMENZ Time Zones", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "IANA time zone database"}
    try:
        fz, fl = _zone(from_tz)
        tzs = [_zone(z) for z in str(to_tz).split(",")[:10]] if to_tz else []
    except Exception:
        return {**out, "error": "unknown time zone: use IANA names like America/Los_Angeles, Europe/London, Asia/Tokyo (or PT/ET/UTC)"}
    try:
        start, end = int(start), int(end)
    except (TypeError, ValueError):
        start, end = 9, 17
    if time_str:
        try:
            naive = dt.datetime.fromisoformat(str(time_str).strip().replace("Z", "+00:00"))
        except ValueError:
            return {**out, "error": "time must be ISO format, e.g. 2026-11-25 14:30 or 2026-11-25T14:30"}
        t = naive.astimezone(fz) if naive.tzinfo else naive.replace(tzinfo=fz)
        src = "given"
        warn = None
        if not naive.tzinfo:
            norm = t.astimezone(dt.timezone.utc).astimezone(fz)
            if norm.replace(tzinfo=None) != naive.replace(tzinfo=None):
                warn = "that local time does not exist (clocks jumped forward for DST); shown as the next valid time"
                t = norm
            elif t.replace(fold=1).utcoffset() != t.replace(fold=0).utcoffset():
                warn = "that local time happens twice (clocks fall back for DST); the first occurrence is used"
    else:
        t = dt.datetime.now(dt.timezone.utc).astimezone(fz)
        src = "now"
    res = {**out, "time_source": src, "utc": t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "from": _info(t, fl, start, end), "business_hours_def": f"{start:02d}:00-{end:02d}:00 Mon-Fri local"}
    if tzs:
        res["to"] = [_info(t.astimezone(z), l, start, end) for z, l in tzs]
        res["all_in_business_hours"] = all(x["business_hours"] for x in [res["from"]] + res["to"])
    if time_str and warn:
        res["warning"] = warn
    return res
