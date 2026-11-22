"""OMENZ Weather: what will the weather do at this place, in a form an agent can act on? (2026-11-22)

Evidence (11-22 category scan): weather x402 services, 1,431 paying wallets at ~18 calls each (the largest repeat-use
data category). Source: MET Norway Locationforecast 2.0 (global, free incl. commercial use with attribution,
CC BY 4.0 / NLOD; "Data from The Norwegian Meteorological Institute"). Coordinates rounded to 4 decimals per MET's
terms; responses cached per location until MET's own expiry (~30 min) so we never hammer the source.

Returns: now (temp °C/°F, wind, humidity, cloud, pressure, condition), next 12/24 hours (high/low, rain total,
max wind), daily outlook up to 5 days, plus plain flags an agent can branch on: rain_next_6h, freezing, high_wind, heat.
"""
import json
import time
import urllib.request

VERSION = "0.1.0"
UA = "OMENZ-Weather/0.1 (https://www.omenz.org; hello@omenz.org)"
_CACHE = {}


def _f(c):
    return None if c is None else round(c * 9 / 5 + 32, 1)


def forecast(lat, lon, days=3):
    out = {"service": "OMENZ Weather", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "source": "Data from The Norwegian Meteorological Institute (MET Norway), CC BY 4.0"}
    try:
        la, lo = round(float(lat), 4), round(float(lon), 4)
    except (TypeError, ValueError):
        return {**out, "error": "lat and lon must be numbers (e.g. lat=34.1478&lon=-118.1445)"}
    if not (-90 <= la <= 90 and -180 <= lo <= 180):
        return {**out, "error": "lat must be -90..90 and lon -180..180"}
    try:
        days = max(1, min(5, int(days or 3)))
    except (TypeError, ValueError):
        days = 3
    key = (la, lo)
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time():
        d = hit[1]
    else:
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                f"https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={la}&lon={lo}", headers={"User-Agent": UA}), timeout=10)
            d = json.load(r)
        except Exception as e:
            return {**out, "error": f"forecast source unavailable ({type(e).__name__}); try again shortly"}
        _CACHE[key] = (time.time() + 1800, d)
        if len(_CACHE) > 500:
            _CACHE.pop(next(iter(_CACHE)))
    ts = (d.get("properties") or {}).get("timeseries") or []
    if not ts:
        return {**out, "error": "no forecast for this location"}

    def det(t):
        return (t.get("data") or {}).get("instant", {}).get("details", {})

    def sym(t, k="next_1_hours"):
        return ((t.get("data") or {}).get(k) or {}).get("summary", {}).get("symbol_code")

    def rain(t):
        return ((t.get("data") or {}).get("next_1_hours") or {}).get("details", {}).get("precipitation_amount")

    now = ts[0]
    n = det(now)
    hourly = [t for t in ts if t.get("data", {}).get("next_1_hours")]

    def window(hours):
        tl = hourly[:hours]
        temps = [det(t).get("air_temperature") for t in tl if det(t).get("air_temperature") is not None]
        rains = [rain(t) or 0 for t in tl]
        winds = [det(t).get("wind_speed") or 0 for t in tl]
        return {"high_c": max(temps) if temps else None, "low_c": min(temps) if temps else None,
                "high_f": _f(max(temps)) if temps else None, "low_f": _f(min(temps)) if temps else None,
                "rain_mm": round(sum(rains), 1), "max_wind_ms": max(winds) if winds else None, "hours_covered": len(tl)}
    daily = {}
    for t in ts:
        day = t["time"][:10]
        v = det(t).get("air_temperature")
        p = ((t.get("data") or {}).get("next_6_hours") or {}).get("details", {}).get("precipitation_amount") if t["time"][11:13] in ("00", "06", "12", "18") else None
        e = daily.setdefault(day, {"date": day, "temps": [], "rain_mm": 0.0, "symbol": None})
        if v is not None:
            e["temps"].append(v)
        if p:
            e["rain_mm"] += p
        if t["time"][11:13] == "12":
            e["symbol"] = sym(t, "next_6_hours") or sym(t, "next_12_hours")
    outlook = [{"date": e["date"], "high_c": max(e["temps"]), "low_c": min(e["temps"]), "high_f": _f(max(e["temps"])),
                "low_f": _f(min(e["temps"])), "rain_mm": round(e["rain_mm"], 1), "condition": e["symbol"]}
               for e in list(daily.values())[:days] if e["temps"]]
    n6 = window(6)
    n24 = window(24)
    flags = {"rain_next_6h": n6["rain_mm"] >= 0.5, "freezing_next_24h": (n24["low_c"] is not None and n24["low_c"] <= 0),
             "high_wind_next_24h": (n24["max_wind_ms"] or 0) >= 13.9, "heat_next_24h": (n24["high_c"] is not None and n24["high_c"] >= 35)}
    return {**out, "lat": la, "lon": lo, "elevation_m": (d.get("geometry") or {}).get("coordinates", [None, None, None])[2],
            "updated_at": (d.get("properties") or {}).get("meta", {}).get("updated_at"),
            "now": {"time": now["time"], "temp_c": n.get("air_temperature"), "temp_f": _f(n.get("air_temperature")),
                    "wind_ms": n.get("wind_speed"), "wind_from_deg": n.get("wind_from_direction"), "humidity_pct": n.get("relative_humidity"),
                    "cloud_pct": n.get("cloud_area_fraction"), "pressure_hpa": n.get("air_pressure_at_sea_level"), "condition": sym(now)},
            "next_6h": n6, "next_24h": n24, "outlook": outlook, "flags": flags,
            "outlook_dates": "UTC calendar days; the first day only covers its remaining hours",
            "limits": "Model forecast for the coordinates given (not an official warning service). For severe weather, follow your local meteorological authority."}
