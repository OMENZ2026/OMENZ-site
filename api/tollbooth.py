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
"""
import os
import sys

from fastapi import Body, FastAPI, Header, Query
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tollbooth"))
import changed  # noqa: E402
import checker  # noqa: E402
import locker  # noqa: E402
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


@app.middleware("http")
async def x402_mw(request, call_next):
    global _mw
    if _mw is None:
        _mw = payment_middleware(ROUTES, server)
    return await _mw(request, call_next)


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


@app.delete(BASE + "/v1/locker/delete")
def locker_delete(id: str = Query(...), x_locker_key: str | None = Header(None)):
    return _locker_call(locker.delete, id, x_locker_key)
