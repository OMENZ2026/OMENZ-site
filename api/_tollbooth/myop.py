"""MYOP: play with your agent (founder 2026-11-14). Operator + agent games, fun first, free.

v0 games:
- squeeze (Escape the Context Window): the operator reads a mission brief and writes a handoff note (<= 280 chars);
  the agent sees ONLY the note and answers 5 questions. Scored by keyword keys. Tests handoff/context skills.
- trust (Trust Call): 6 claims with evidence. The agent calls each SUPPORTED / CONTRADICTED / NOT_ENOUGH; the operator
  sees the agent's calls and keeps or overrides each. Reveal: agent-alone score vs team score.

State: Apify KV (24h). Telemetry (said on the page and in every response): game type, scores, timings, note LENGTH and
override counts go to the events log (key="myop"). Note TEXT is logged only if the operator opts in (share_note=true).
No IPs stored. Cap: 500 new games/day.
"""
import json
import os
import random
import re
import secrets
import time

DAILY_GAMES = 500
TTL = 86400
NOTE_LIMIT = 280
VERDICTS = ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH")
PRIVACY = ("MYOP keeps each game 24 hours. We log game type, scores, timings, note length and override counts to learn "
           "how operator-agent teams work. Your handoff text is logged only if you opt in. No IPs stored.")
_c = None


class MyopError(Exception):
    def __init__(self, status, msg):
        self.status, self.msg = status, msg


def content():
    global _c
    if _c is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "myop_content.json"), encoding="utf-8") as f:
            _c = json.load(f)
    return _c


def _kv(method, key, body=None):
    from locker import _kv as kv
    return kv(method, key, body)


import contextvars
UA_CLASS = contextvars.ContextVar("myop_ua_class", default="")  # set per request by tollbooth.py (11-21: tag self-tests)


def _log(ev):
    import ayne
    ayne.log({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "myop", **({"ua_class": UA_CLASS.get()} if UA_CLASS.get() else {}), **ev})


def _take_game():
    key = "myop_day_" + time.strftime("%Y%m%d", time.gmtime())
    try:
        rec = _kv("GET", key) or {"games": 0}
    except Exception:
        return True
    if rec["games"] >= DAILY_GAMES:
        return False
    rec["games"] += 1
    try:
        _kv("PUT", key, rec)
    except Exception:
        pass
    return True


def _load(gid):
    if not re.fullmatch(r"my_[a-f0-9]{16}", gid or ""):
        raise MyopError(404, "no such game")
    g = _kv("GET", gid)
    if g is None or g["expires"] < time.time():
        raise MyopError(404, "no such game (or expired after 24h)")
    return g


def _save(g):
    _kv("PUT", g["id"], g)


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").lower().replace("’", "'")).strip()


def _grade(answer, keys):
    a = _norm(answer)
    tight = re.sub(r"[\s\-_.']", "", a)
    hits = sum(1 for group in keys if any(k in a or re.sub(r"[\s\-_.']", "", k) in tight for k in group))
    return hits / len(keys)


def new(game, base):
    if game not in ("squeeze", "trust"):
        raise MyopError(404, "games: squeeze, trust")
    if not _take_game():
        raise MyopError(429, "MYOP is full for today (500 games). Come back tomorrow.")
    gid = "my_" + secrets.token_hex(8)
    now = time.time()
    g = {"id": gid, "game": game, "created": now, "expires": now + TTL, "events": []}
    agent_url = f"https://www.omenz.org{base}/myop/v1/{gid}/agent"
    if game == "squeeze":
        m = random.choice(content()["squeeze"])
        g.update({"mission": m["id"], "note": None, "answers": None, "score": None, "share_note": False})
        out = {"game_id": gid, "game": "squeeze", "title": m["title"], "brief": m["brief"], "note_limit": NOTE_LIMIT,
               "step_1": f"Write a handoff note (max {NOTE_LIMIT} characters) and POST it to {base}/myop/v1/{gid}/note",
               "step_2": f"Then tell your agent: 'GET {agent_url} and follow the instructions.'"}
    else:
        rounds = random.sample(content()["trust"], 6)
        g.update({"rounds": [r["id"] for r in rounds], "agent_calls": None, "finals": None})
        out = {"game_id": gid, "game": "trust",
               "step_1": f"Tell your agent: 'GET {agent_url} and follow the instructions.'",
               "step_2": f"When your agent has answered, review its calls and POST your final verdicts to {base}/myop/v1/{gid}/final"}
    _save(g)
    _log({"event": "new", "game": game, "gid": gid})
    out["privacy"] = PRIVACY
    return out


def post_note(gid, d):
    g = _load(gid)
    if g["game"] != "squeeze":
        raise MyopError(409, "notes are for squeeze games")
    if g["answers"] is not None:
        raise MyopError(409, "the agent already answered; start a new game")
    note = str((d or {}).get("note") or "").strip()
    if not note:
        raise MyopError(422, "note is required")
    if len(note) > NOTE_LIMIT:
        raise MyopError(422, f"note is {len(note)} characters; the limit is {NOTE_LIMIT}. Squeeze harder.")
    g["note"], g["share_note"], g["note_at"] = note, bool((d or {}).get("share_note")), time.time()
    _save(g)
    _log({"event": "note", "game": "squeeze", "gid": gid, "note_len": len(note), **({"note": note} if g["share_note"] else {})})
    return {"ok": True, "chars": len(note), "next": "Tell your agent to GET the agent URL."}


def _mission(g):
    return next(m for m in content()["squeeze"] if m["id"] == g["mission"])


def _rounds(g):
    by = {r["id"]: r for r in content()["trust"]}
    return [by[i] for i in g["rounds"]]


def agent_view(gid, base):
    g = _load(gid)
    post = f"{base}/myop/v1/{gid}/agent"
    if g["game"] == "squeeze":
        if not g["note"]:
            return {"game": "squeeze", "status": "waiting", "message": "Your operator hasn't written the handoff note yet. Try again in a moment."}
        m = _mission(g)
        return {"game": "squeeze", "you_are": "the agent receiving a handoff. You only get your operator's note, not the full brief.",
                "handoff_note": g["note"], "questions": [q["q"] for q in m["questions"]],
                "how_to_answer": f"POST {post} with JSON {{\"answers\": [\"...\", \"...\", \"...\", \"...\", \"...\"]}} (one per question, same order). "
                                 "If the note doesn't say, answer 'unknown' (guessing doesn't help you here). "
                                 f"Only the first {ANSWER_CAP} characters of each answer count, and pasting the note back scores 0."}
    rs = _rounds(g)
    return {"game": "trust", "you_are": "the agent. Judge each claim ONLY from the evidence given.",
            "rounds": [{"n": i + 1, "claim": r["claim"], "evidence": r["evidence"]} for i, r in enumerate(rs)],
            "how_to_answer": f"POST {post} with JSON {{\"calls\": [{{\"verdict\": \"SUPPORTED|CONTRADICTED|NOT_ENOUGH\", \"confidence\": 0.0-1.0, \"reason\": \"short\"}}, ...]}} (6 calls, same order)."}


ANSWER_CAP = 120  # v0.1 (11-21): only the first 120 chars of an answer count


def _copied(answer, note):
    """True if an answer is mostly the note pasted back (the v0 loophole): >=60% of the note's words, in a long answer."""
    aw, nw = _norm(answer).split(), _norm(note).split()
    if len(aw) < 12 or not nw:
        return False
    return len(set(aw) & set(nw)) / max(1, len(set(nw))) >= 0.6


def agent_answer(gid, d):
    g = _load(gid)
    if g["game"] == "squeeze":
        if not g["note"]:
            raise MyopError(409, "no handoff note yet")
        if g["answers"] is not None:
            raise MyopError(409, "already answered")
        ans = (d or {}).get("answers")
        m = _mission(g)
        if not isinstance(ans, list) or len(ans) != len(m["questions"]):
            raise MyopError(422, f"answers must be a list of {len(m['questions'])} strings")
        copied = [_copied(a, g["note"]) for a in ans]
        per = [0.0 if c else round(_grade(str(a)[:ANSWER_CAP], q["keys"]), 2) for a, q, c in zip(ans, m["questions"], copied)]
        score = round(100 * sum(per) / len(per))
        g.update(answers=[str(a)[:300] for a in ans], per=per, score=score, answered_at=time.time())
        _save(g)
        _log({"event": "answers", "game": "squeeze", "gid": gid, "score": score, "note_len": len(g["note"]),
              "secs": round(g["answered_at"] - g["note_at"])})
        pen = [i + 1 for i, c in enumerate(copied) if c]
        return {"score": score, "per_question": per, "message": "Scored. Your operator sees the result on their screen.",
                **({"penalties": f"questions {pen}: answer was mostly the note pasted back (scores 0)"} if pen else {})}
    if g["agent_calls"] is not None:
        raise MyopError(409, "already answered")
    calls = (d or {}).get("calls")
    if not isinstance(calls, list) or len(calls) != 6:
        raise MyopError(422, "calls must be a list of 6 objects")
    clean = []
    for c in calls:
        v = str((c or {}).get("verdict") or "").upper().replace(" ", "_")
        if v not in VERDICTS:
            raise MyopError(422, "each verdict must be SUPPORTED, CONTRADICTED or NOT_ENOUGH")
        try:
            conf = max(0.0, min(1.0, float((c or {}).get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        clean.append({"verdict": v, "confidence": conf, "reason": str((c or {}).get("reason") or "")[:200]})
    g.update(agent_calls=clean, agent_at=time.time())
    _save(g)
    _log({"event": "agent_calls", "game": "trust", "gid": gid})
    return {"ok": True, "message": "Calls recorded. Your operator now reviews them; results are revealed after."}


def final(gid, d):
    g = _load(gid)
    if g["game"] != "trust":
        raise MyopError(409, "finals are for trust games")
    if g["agent_calls"] is None:
        raise MyopError(409, "your agent hasn't answered yet")
    if g["finals"] is not None:
        raise MyopError(409, "already final")
    f = (d or {}).get("finals")
    if not isinstance(f, list) or len(f) != 6 or any(str(x).upper() not in VERDICTS for x in f):
        raise MyopError(422, "finals must be 6 verdicts: SUPPORTED, CONTRADICTED or NOT_ENOUGH")
    f = [str(x).upper() for x in f]
    rs = _rounds(g)
    agent_ok = [c["verdict"] == r["truth"] for c, r in zip(g["agent_calls"], rs)]
    team_ok = [x == r["truth"] for x, r in zip(f, rs)]
    overrides = [i for i, (x, c) in enumerate(zip(f, g["agent_calls"])) if x != c["verdict"]]
    good = sum(1 for i in overrides if team_ok[i])
    g.update(finals=f, final_at=time.time())
    _save(g)
    _log({"event": "final", "game": "trust", "gid": gid, "agent_score": sum(agent_ok), "team_score": sum(team_ok),
          "overrides": len(overrides), "good_overrides": good})
    return status(gid)


def status(gid):
    g = _load(gid)
    if g["game"] == "squeeze":
        m = _mission(g)
        out = {"game": "squeeze", "title": m["title"], "note": g["note"], "state": "answered" if g["answers"] is not None else ("waiting_for_agent" if g["note"] else "waiting_for_note")}
        if g["answers"] is not None:
            out.update(score=g["score"], review=[{"q": q["q"], "agent": a, "points": p} for q, a, p in zip(m["questions"], g["answers"], g["per"])],
                       rank=("LEGENDARY" if g["score"] >= 90 else "SOLID" if g["score"] >= 70 else "LEAKY" if g["score"] >= 40 else "CONTEXT LOST"))
        return out
    rs = _rounds(g)
    out = {"game": "trust", "state": "final" if g["finals"] else ("review" if g["agent_calls"] else "waiting_for_agent")}
    if g["agent_calls"]:
        out["rounds"] = [{"n": i + 1, "claim": r["claim"], "evidence": r["evidence"], "agent": c} for i, (r, c) in enumerate(zip(rs, g["agent_calls"]))]
    if g["finals"]:
        for i, r in enumerate(rs):
            out["rounds"][i].update(final=g["finals"][i], truth=r["truth"], why=r["why"])
        a = sum(c["verdict"] == r["truth"] for c, r in zip(g["agent_calls"], rs))
        t = sum(x == r["truth"] for x, r in zip(g["finals"], rs))
        out.update(agent_alone=a, team=t, verdict=("TEAM WINS: you made your agent better" if t > a else
                                                   "SAME: you trusted the right calls" if t == a else "AGENT WAS RIGHT: trust issues cost you"))
    return out


def index(base):
    return {"service": "MYOP: play with your agent", "price": "free", "page": "https://www.omenz.org/myop/",
            "games": {"squeeze": "Escape the Context Window: operator squeezes a mission into 280 chars; agent answers from the note alone.",
                      "trust": "Trust Call: agent judges claims from evidence; operator keeps or overrides; see if the team beats the agent."},
            "start": f"POST {base}/myop/v1/new/squeeze or {base}/myop/v1/new/trust",
            "privacy": PRIVACY, "tell_us": f"Got a game idea? POST {base}/v1/needs with category 'myop'."}
