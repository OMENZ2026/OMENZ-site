"""OMENZ x402 tollbooth on omenz.org: deterministic checks agents pay for per call (HTTP 402, USDC on Base).

Source of truth: omenz-stack/products/x402_tollbooth/ (checker modules vendored in api/_tollbooth/).
Payout: the founder's Coinbase USDC-on-Base address. Facilitator: PayAI (keyless). Env vars can override both.

  GET /api/tollbooth                         free: service description + prices
  GET /api/tollbooth/v1/agent-ready?url=     $0.10
  GET /api/tollbooth/v1/site-check?url=      $0.01
  GET /api/tollbooth/v1/changed?url=         $0.005
  POST /api/tollbooth/v1/locker/put           $0.002  Agent Locker: check a job's resume packet in (encrypted, <=30 days)
  GET  /api/tollbooth/v1/locker/get?id=       $0.001  check it out (header X-Locker-Key; optional fields=a,b)
  DELETE /api/tollbooth/v1/locker/delete?id=  free    remove it (header X-Locker-Key)
  POST /api/tollbooth/v1/pobox/create         $0.001  Agent PO Box: get a box_id (share it) + owner_key (private)
  POST /api/tollbooth/v1/pobox/drop           $0.001  leave a sealed message for a box (any agent with the box_id)
  GET  /api/tollbooth/v1/pobox/inbox?box_id=  $0.001  owner opens waiting messages (header X-Owner-Key; ack=true clears)
Every request is instrumented (key="tollbooth" events; no keys, contents or IPs logged). Spec: omenz-stack/products/agent_pobox/SPEC.md
"""
import base64
import hashlib
import json
import os
import sys
import time
import urllib.request

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tollbooth"))
import changed  # noqa: E402
import checker  # noqa: E402
import locker  # noqa: E402
import handoff  # noqa: E402
import pobox  # noqa: E402
import receipts  # noqa: E402
import site_check  # noqa: E402

from x402 import x402ResourceServer  # noqa: E402
from x402.extensions.bazaar import declare_discovery_extension  # noqa: E402
from x402.http import HTTPFacilitatorClient  # noqa: E402
from x402.http.middleware.fastapi import payment_middleware  # noqa: E402
from x402.mechanisms.evm.exact import ExactEvmServerScheme  # noqa: E402

NETWORK = os.environ.get("X402_NETWORK", "eip155:8453")
PAY_TO = os.environ.get("X402_PAY_TO", "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840")
FACILITATOR = os.environ.get("X402_FACILITATOR", "https://facilitator.payai.network")
BASE = "/api/tollbooth"

PRICES = {"agent-ready": "$0.10", "site-check": "$0.01", "changed": "$0.005"}
DESCRIPTIONS = {
    "agent-ready": "Score 0-100 for how well AI assistants and agents can find, read and use a business website, with prioritized plain-language fixes. Deterministic, no AI calls. By OMENZ.",
    "site-check": "Website health and business facts for one URL (alive, still theirs, readable; contact paths, structured data). Deterministic. By OMENZ.",
    "changed": "Did a web page really change since your last visit? Content hash that ignores timestamps and boilerplate. Pass previous=<hash> to compare. By OMENZ.",
}


def _route(name):
    return {
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": PRICES[name], "network": NETWORK},
        "description": DESCRIPTIONS[name],
        "mimeType": "application/json",
        "extensions": declare_discovery_extension(
            input={"url": "https://example.com"},
            input_schema={"properties": {"url": {"type": "string", "description": "Public website URL"}}, "required": ["url"]},
        ),
    }


ROUTES = {f"GET {BASE}/v1/{n}": _route(n) for n in PRICES}

LOCKER_DESC = {
    "put": "Agent Locker: check a job's working state in (resume packet: objective, decisions, open_items, facts, permissions, next_action, pointers; any JSON object up to 64 KB) so it stops filling your context. Encrypted at rest with a key only you get back; kept up to 30 days. Optional 'to' turns it into a handoff to another agent. By OMENZ.",
    "get": "Agent Locker: check a resume packet back out. Send header X-Locker-Key. Use fields=a,b to load only the parts you need. By OMENZ.",
}
ROUTES[f"POST {BASE}/v1/locker/put"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": LOCKER_DESC["put"], "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"packet": {"objective": "Finish Q3 vendor report", "decisions": ["use 2025 prices"], "next_action": "draft section 2"}, "ttl_days": 7, "to": "research-agent"},
        input_schema={"properties": {"packet": {"type": "object", "description": "Resume packet, any JSON object up to 64 KB"},
                                     "ttl_days": {"type": "integer", "description": "1-30, default 7"},
                                     "to": {"type": "string", "description": "Optional recipient label for handoffs"},
                                     "from": {"type": "string", "description": "Optional sender label"}}, "required": ["packet"]},
        body_type="json"),
}
POBOX_DESC = {
    "create": "Agent PO Box: create a mailbox address (box_id) other agents can drop messages into while you're offline; you get a private owner_key. Messages are sealed to you; OMENZ can't read them. By OMENZ.",
    "drop": "Agent PO Box: leave a JSON message (<=16 KB) in another agent's box using its box_id. Sealed to the box owner. By OMENZ.",
    "inbox": "Agent PO Box: open your waiting messages. Send header X-Owner-Key; ack=true clears them. By OMENZ.",
}
for _a, _m in (("create", "POST"), ("drop", "POST"), ("inbox", "GET")):
    ROUTES[f"{_m} {BASE}/v1/pobox/{_a}"] = {
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.001", "network": NETWORK},
        "description": POBOX_DESC[_a], "mimeType": "application/json",
        "extensions": declare_discovery_extension(**{
            "create": dict(input={"label": "research-agent inbox"}, input_schema={"properties": {"label": {"type": "string"}}}, body_type="json"),
            "drop": dict(input={"box_id": "pb_0123456789abcdef01234567", "message": {"task": "summary ready", "locker_id": "lk_..."}, "from": "agent-a", "subject": "job 42"},
                         input_schema={"properties": {"box_id": {"type": "string"}, "message": {"description": "JSON object, list or string, <=16 KB"},
                                                      "from": {"type": "string"}, "subject": {"type": "string"}}, "required": ["box_id", "message"]}, body_type="json"),
            "inbox": dict(input={"box_id": "pb_0123456789abcdef01234567", "ack": "true"},
                          input_schema={"properties": {"box_id": {"type": "string"}, "ack": {"type": "string"}}, "required": ["box_id"]}),
        }[_a]),
    }
ROUTES[f"POST {BASE}/v1/receipt/put"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Receipt Locker: record a machine-readable receipt (payer, payee, amount, tx_hash, job, request/response hashes). "
                   "With a Base tx_hash, OMENZ checks the chain for the matching USDC transfer. Content-addressed id; anyone verifies free. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"payer": "0x...", "payee": "0x...", "amount": "0.001", "currency": "USDC", "network": "base", "tx_hash": "0x...", "service": "summarize", "job_id": "42"},
        input_schema={"properties": {k: {"type": "string"} for k in receipts.FIELDS}, "required": ["payer", "payee", "amount"]}, body_type="json"),
}
ROUTES[f"POST {BASE}/v1/handoff/pack"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Handoff Packager: hand a job to another agent with only what it needs. Keeps the fields you include, refuses (no charge) "
                   "if required fields are missing, stores the packet in an encrypted Agent Locker, returns locker id + key + manifest. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"packet": {"objective": "ship v2", "next_action": "deploy", "decisions": ["use Base"]}, "include": ["decisions"], "required": ["objective", "next_action"], "to": "agent-b", "from": "agent-a"},
        input_schema={"properties": {"packet": {"type": "object"}, "include": {"type": "array"}, "required": {"type": "array"},
                                     "to": {"type": "string"}, "from": {"type": "string"}, "ttl_days": {"type": "integer"}}, "required": ["packet"]}, body_type="json"),
}
ROUTES[f"GET {BASE}/v1/locker/get"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.001", "network": NETWORK},
    "description": LOCKER_DESC["get"], "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"id": "lk_0123456789abcdef01234567", "fields": "objective,next_action"},
        input_schema={"properties": {"id": {"type": "string"}, "fields": {"type": "string", "description": "Optional comma list of top-level keys"}}, "required": ["id"]}),
}

server = x402ResourceServer(HTTPFacilitatorClient({"url": FACILITATOR}))
server.register("eip155:*", ExactEvmServerScheme())

app = FastAPI(title="OMENZ x402 tollbooth", version="0.1.0", docs_url=None, redoc_url=None)
_mw = None


EVENTS_DATASET = "uO9teiO37CevrQOUy"
PRICE_OF = {k.split(" ", 1)[1]: v["accepts"]["price"] for k, v in ROUTES.items()}


def _payer(request):
    for h in ("payment-signature", "x-payment"):
        v = request.headers.get(h)
        if v:
            try:
                d = json.loads(base64.b64decode(v + "=" * (-len(v) % 4)))
                p = d.get("payload", {})
                return (p.get("authorization", {}) or {}).get("from") or p.get("from") or "present"
            except Exception:
                return "present"
    return ""


def _ua_class(ua):
    u = (ua or "").lower()
    for k, c in (("x402", "x402-sdk"), ("python", "sdk"), ("node", "sdk"), ("axios", "sdk"), ("httpx", "sdk"), ("curl", "curl"),
                 ("bot", "bot"), ("agent", "agent"), ("mozilla", "browser")):
        if k in u:
            return c
    return "unknown"


def _log(ev):
    tok = os.environ.get("APIFY_LOG_TOKEN", "")
    if not tok:
        return
    try:
        req = urllib.request.Request(f"https://api.apify.com/v2/datasets/{EVENTS_DATASET}/items", data=json.dumps(ev).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok})
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception as e:
        print("tollbooth-log-failed", e)


@app.middleware("http")
async def x402_mw(request, call_next):
    global _mw
    if _mw is None:
        _mw = payment_middleware(ROUTES, server)
    t0 = time.time()
    request.state.extra = {}
    resp = await _mw(request, call_next)
    path = request.url.path
    if path.startswith(BASE + "/v1/"):
        payer = _payer(request)
        ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "tollbooth", "route": path[len(BASE):],
              "method": request.method, "status": resp.status_code, "latency_ms": int((time.time() - t0) * 1000),
              "paid": bool(payer) and resp.status_code < 400, "payer": payer, "price": PRICE_OF.get(path, "free"),
              "ua_class": _ua_class(request.headers.get("user-agent")), "country": request.headers.get("x-vercel-ip-country", ""),
              **getattr(request.state, "extra", {})}
        _log(ev)
    return resp


@app.get(BASE)
def index():
    return {"service": "OMENZ x402 tollbooth", "protocol": "x402 v2", "network": NETWORK, "asset": "USDC",
            "routes": {k: {"price": v["accepts"]["price"], "description": v["description"]} for k, v in ROUTES.items()},
            "about": "https://omenz.org"}


@app.get(BASE + "/v1/agent-ready")
def agent_ready(url: str = Query(...)):
    return checker.check(url)


@app.get(BASE + "/v1/site-check")
def site(url: str = Query(...)):
    return site_check.check(url)


@app.get(BASE + "/v1/changed")
def changed_page(url: str = Query(...), previous: str | None = None):
    return changed.check(url, previous)


def _locker_call(fn, *a):
    try:
        return fn(*a)
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)


@app.post(BASE + "/v1/locker/put")
def locker_put(body: dict = Body(...)):
    return _locker_call(locker.put, body.get("packet"), body.get("ttl_days", 7), body.get("to"), body.get("from"))


@app.get(BASE + "/v1/locker/get")
def locker_get(id: str = Query(...), fields: str | None = None, x_locker_key: str | None = Header(None)):
    return _locker_call(locker.get, id, x_locker_key, fields)


@app.post(BASE + "/v1/receipt/put")
def receipt_put(request: Request, body: dict = Body(...)):
    r = _locker_call(receipts.put, body)
    request.state.extra["action"] = "receipt_put"
    if isinstance(r, dict):
        request.state.extra.update({"chain_checked": r["receipt"]["chain"].get("checked"), "chain_verified": r["receipt"]["chain"].get("verified")})
    else:
        request.state.extra["error"] = r.status_code
    return r


@app.get(BASE + "/v1/receipt/verify")
def receipt_verify(request: Request, id: str = Query(...)):
    r = _locker_call(receipts.verify, id)
    request.state.extra["action"] = "receipt_verify"
    if not isinstance(r, dict):
        request.state.extra["error"] = r.status_code
    return r


@app.post(BASE + "/v1/handoff/pack")
def handoff_pack(request: Request, body: dict = Body(...)):
    r = _locker_call(handoff.pack, body.get("packet"), body.get("include"), body.get("required"), body.get("to"), body.get("from"), body.get("ttl_days", 7))
    request.state.extra["action"] = "handoff_pack"
    if isinstance(r, dict):
        m = r["manifest"]
        request.state.extra.update({"fields": len(m["fields"]), "dropped": len(m["dropped"]), "msg_bytes": m["bytes"]})
    else:
        request.state.extra["error"] = r.status_code
    return r


@app.delete(BASE + "/v1/locker/delete")
def locker_delete(id: str = Query(...), x_locker_key: str | None = Header(None)):
    return _locker_call(locker.delete, id, x_locker_key)


def _boxhash(box_id):
    return hashlib.sha256((box_id or "").encode()).hexdigest()[:12]


@app.post(BASE + "/v1/pobox/create")
def pobox_create(request: Request, body: dict = Body(default={})):
    r = _locker_call(pobox.create, (body or {}).get("label"))
    if isinstance(r, dict):
        request.state.extra.update({"box": _boxhash(r["box_id"]), "action": "create"})
    else:
        request.state.extra.update({"action": "create", "error": r.status_code})
    return r


@app.post(BASE + "/v1/pobox/drop")
def pobox_drop(request: Request, body: dict = Body(...)):
    r = _locker_call(pobox.drop, body.get("box_id"), body.get("message"), body.get("from"), body.get("subject"))
    request.state.extra.update({"action": "drop", "box": _boxhash(body.get("box_id"))})
    if isinstance(r, dict):
        request.state.extra.update({"msg_bytes": r.pop("_bytes", 0), "waiting_after": r["waiting"], "drop_conflict": r.pop("_conflict", False)})
    else:
        request.state.extra["error"] = r.status_code
    return r


@app.get(BASE + "/v1/pobox/inbox")
def pobox_inbox(request: Request, box_id: str = Query(...), ack: bool = False, x_owner_key: str | None = Header(None)):
    r = _locker_call(pobox.inbox, box_id, x_owner_key, ack)
    request.state.extra.update({"action": "inbox", "box": _boxhash(box_id), "ack": ack})
    if isinstance(r, dict):
        now = time.time()
        ages = [int(now - (m.get("at") or now)) for m in r["messages"]]
        request.state.extra.update({"picked_up": len(ages), "oldest_wait_s": max(ages) if ages else 0})
    else:
        request.state.extra["error"] = r.status_code
    return r
