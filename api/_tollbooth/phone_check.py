"""OMENZ Phone Check: is this a real, dialable phone number, and what kind? (2026-11-22)

Evidence: x402 phone-validation services had 43 paying wallets at ~217 calls each (the strongest repeat use of any
utility category in the 11-22 market scan). Runs fully offline on Google's libphonenumber data (python `phonenumbers`):
no external calls, no data leaves OMENZ, nothing stored.

Returns: VALID / POSSIBLE_BUT_INVALID / INVALID, E.164 + international + national formats, country, number type
(mobile, fixed line, toll free, premium rate, VoIP, ...), region description, original carrier (mobile, where known),
time zones, and warnings an agent should know before calling or texting (premium-rate cost, VoIP, toll-free cannot SMS).
"""
import time

VERSION = "0.1.0"
TYPES = {0: "fixed_line", 1: "mobile", 2: "fixed_line_or_mobile", 3: "toll_free", 4: "premium_rate", 5: "shared_cost",
         6: "voip", 7: "personal_number", 8: "pager", 9: "uan", 10: "voicemail", 27: "emergency", 28: "short_code", 99: "unknown"}


def check(number, country=None):
    out = {"service": "OMENZ Phone Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "offline": True, "stored": False}
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone, NumberParseException
    raw = str(number or "").strip()
    cc = (str(country or "").strip().upper() or None)
    if not raw or len(raw) > 40:
        return {**out, "verdict": "BAD_INPUT", "reasons": ["send number (e.g. +1 650 253 0000) and, for local formats, country (ISO code like US)"]}
    if cc and (len(cc) != 2 or not cc.isalpha()):
        return {**out, "verdict": "BAD_INPUT", "reasons": ["country must be a 2-letter ISO code like US, GB, MX"]}
    try:
        p = phonenumbers.parse(raw, cc)
    except NumberParseException as e:
        return {**out, "verdict": "INVALID", "input": raw, "reasons": [f"cannot parse: {str(e)[:120]}"
                + ("" if raw.startswith("+") or cc else " (add country= or start with +countrycode)")]}
    valid, possible = phonenumbers.is_valid_number(p), phonenumbers.is_possible_number(p)
    t = TYPES.get(phonenumbers.number_type(p), "unknown")
    region = phonenumbers.region_code_for_number(p)
    res = {**out, "input": raw, "verdict": "VALID" if valid else "POSSIBLE_BUT_INVALID" if possible else "INVALID",
           "e164": phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164),
           "international": phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
           "national": phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.NATIONAL),
           "country_code": p.country_code, "region": region, "type": t,
           "location": geocoder.description_for_number(p, "en") or None,
           "carrier": carrier.name_for_number(p, "en") or None,
           "time_zones": [z for z in timezone.time_zones_for_number(p) if z != "Etc/Unknown"]}
    warn = []
    if t == "premium_rate":
        warn.append("premium-rate number: calling or texting costs extra (common in scams)")
    if t == "voip":
        warn.append("VoIP number: easy to create and discard; weaker identity signal")
    if t == "toll_free":
        warn.append("toll-free number: usually cannot receive SMS")
    if t in ("fixed_line",):
        warn.append("landline: cannot receive SMS")
    nsn = str(p.national_number)
    if p.country_code == 1 and len(nsn) == 10 and nsn[3:6] == "555" and 100 <= int(nsn[6:]) <= 199:
        warn.append("555-01XX is the North American range reserved for fiction and examples: not a real subscriber number")
        res["verdict"] = "FICTIONAL"
    if not valid and possible:
        warn.append("right length but not an assigned number range: likely mistyped or fake")
    if res["carrier"] and t == "mobile":
        warn.append("carrier shown is the ORIGINAL carrier; the number may have been ported")
    res["warnings"] = warn
    res["can_sms_likely"] = t in ("mobile", "fixed_line_or_mobile") and res["verdict"] == "VALID"
    res["limits"] = "Validates numbering-plan rules offline; it cannot tell whether a number is currently in service or who owns it."
    return res
