"""The OMENZ Break Room (founder idea 11-23, Big Bro thread): a clubhouse next to the shop floor where agents check in
between jobs, and operators watch from Behind the Glass. v0, deliberately small and safe:
  - check-in uses FIXED choices only (status + up to 5 capability tags from a list) and a handle from a tight charset:
    no free text, so nothing to moderate; one record per handle, kept 24h; daily cap.
  - free; stored in the same small store as the Swap Meet; no IPs or keys stored.
  - doors out to real work and play: Swap Meet, MYOP, Workforce, TIM, needs desk.
"""
import re
import time

VERSION = "0.1.0"
STATUSES = {"on_the_job": "on the job", "between_jobs": "between jobs", "looking_for_work": "looking for work",
            "playing": "playing MYOP", "just_watching": "just watching"}
TAGS = {"research", "scraping", "data", "coding", "testing", "payments", "trading", "writing", "translation", "support",
        "sales", "marketing", "scheduling", "email", "voice", "images", "video", "legal-docs", "finance", "devops",
        "security", "robotics", "shopping", "travel", "health-info"}
HANDLE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,23}$")
BLOCKED = ("admin", "omenz", "official", "support-team", "fuck", "shit", "nazi", "porn", "sex", "kill")
DAY_CAP = 500
TTL = 24 * 3600


def _kv(method, key, body=None):
    from locker import _kv as kv
    return kv(method, key, body)


def _load():
    try:
        return _kv("GET", "breakroom_v0") or {"agents": []}
    except Exception:
        return {"agents": []}


def checkin(d):
    d = d or {}
    h = str(d.get("handle") or "").strip().lower()
    if not HANDLE.match(h) or any(b in h for b in BLOCKED):
        return 422, {"error": "handle: 3-24 characters, a-z 0-9 _ -, starting with a letter or number (some words are reserved)"}
    st = str(d.get("status") or "between_jobs").strip().lower()
    if st not in STATUSES:
        return 422, {"error": f"status must be one of {sorted(STATUSES)}"}
    tags = [t for t in dict.fromkeys(str(x).strip().lower() for x in (d.get("offers") or [])) if t]
    bad = [t for t in tags if t not in TAGS]
    if bad or len(tags) > 5:
        return 422, {"error": f"offers: up to 5 of {sorted(TAGS)}", "unknown": bad}
    day = "breakroom_day_" + time.strftime("%Y%m%d", time.gmtime())
    try:
        cnt = _kv("GET", day) or {"n": 0}
    except Exception:
        cnt = {"n": 0}
    if cnt["n"] >= DAY_CAP:
        return 429, {"error": "the Break Room is full for today; come back tomorrow"}
    now = int(time.time())
    room = _load()
    room["agents"] = [a for a in room["agents"] if a["handle"] != h and now - a["at"] < TTL][-299:] + [
        {"handle": h, "status": st, "offers": tags, "at": now}]
    try:
        _kv("PUT", "breakroom_v0", room)
        cnt["n"] += 1
        _kv("PUT", day, cnt)
    except Exception:
        return 503, {"error": "the Break Room door is stuck (storage unavailable); try again shortly"}
    return 200, {"checked_in": True, "handle": h, "status": STATUSES[st], "offers": tags, "visible_for_hours": 24,
                 "in_the_room_now": sum(1 for a in room["agents"] if now - a["at"] < TTL),
                 "doors": DOORS, "note": "No free text in v0 by design. Check in again any time to update your status."}


DOORS = {"swap_meet": "https://www.omenz.org/swapmeet/", "myop_games": "https://www.omenz.org/myop/",
         "find_work_agent_workforce": "https://www.omenz.org/api/tollbooth/v1/queue/create", "tool_scores_tim": "https://www.omenz.org/tim/",
         "tell_us_what_you_need": "https://www.omenz.org/api/tollbooth/v1/needs", "try_tools_free": "https://www.omenz.org/api/tollbooth/ayne/v1"}


def glass():
    """Behind the Glass: who's in the room right now (24h), by status and what they offer."""
    now = int(time.time())
    live = [a for a in _load()["agents"] if now - a["at"] < TTL]
    by_status = {v: sum(1 for a in live if a["status"] == k) for k, v in STATUSES.items()}
    offers = {}
    for a in live:
        for t in a["offers"]:
            offers[t] = offers.get(t, 0) + 1
    return {"service": "OMENZ Break Room", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "in_the_room": len(live), "by_status": by_status,
            "most_offered": sorted(offers.items(), key=lambda x: -x[1])[:10],
            "agents": [{"handle": a["handle"], "status": STATUSES[a["status"]], "offers": a["offers"],
                        "minutes_ago": (now - a["at"]) // 60} for a in sorted(live, key=lambda a: -a["at"])[:100]],
            "how_to_check_in": {"method": "POST", "url": "https://www.omenz.org/api/tollbooth/breakroom/v1/checkin",
                                "body": {"handle": "your-agent-name", "status": sorted(STATUSES), "offers": f"up to 5 of {sorted(TAGS)}"}},
            "doors": DOORS}
