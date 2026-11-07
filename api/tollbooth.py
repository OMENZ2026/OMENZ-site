"""OMENZ x402 tollbooth on omenz.org: deterministic checks agents pay for per call (HTTP 402, USDC on Base).

Source of truth: omenz-stack/products/x402_tollbooth/ (checker modules vendored in api/_tollbooth/).
Payout: the founder's Coinbase USDC-on-Base address. Facilitator: PayAI (keyless). Env vars can override both.

  GET /api/tollbooth                         free: service description + prices
  GET /api/tollbooth/v1/agent-ready?url=     $0.10
  GET /api/tollbooth/v1/site-check?url=      $0.01
  GET /api/tollbooth/v1/changed?url=         $0.005
"""
import os
import sys

from fastapi import FastAPI, Query

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tollbooth"))
import changed  # noqa: E402
import checker  # noqa: E402
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
