"""OMENZ x402 tollbooth on omenz.org: deterministic checks agents pay for per call (HTTP 402, USDC on Base).

Source of truth: omenz-stack/products/x402_tollbooth/ (checker modules vendored in api/_tollbooth/).
Payout: the founder's Coinbase USDC-on-Base address. Facilitator: PayAI (keyless). Env vars can override both.

  GET /api/tollbooth                         free: service description + prices
  GET /api/tollbooth/v1/agent-ready?url=     $0.10
  GET /api/tollbooth/v1/site-check?url=      $0.01
  GET /api/tollbooth/v1/changed?url=         $0.005
  GET /api/tollbooth/v1/local-facts?url=     $0.01   Local Facts: phone/address/hours/holiday notices from the business's own site
  POST /api/tollbooth/v1/locker/put           $0.002  Agent Locker: check a job's resume packet in (encrypted, <=30 days)
  GET  /api/tollbooth/v1/locker/get?id=       $0.001  check it out (header X-Locker-Key; optional fields=a,b)
  DELETE /api/tollbooth/v1/locker/delete?id=  free    remove it (header X-Locker-Key)
  POST /api/tollbooth/v1/pobox/create         $0.001  Agent PO Box: get a box_id (share it) + owner_key (private)
  POST /api/tollbooth/v1/pobox/drop           $0.001  leave a sealed message for a box (any agent with the box_id)
  GET  /api/tollbooth/v1/pobox/inbox?box_id=  $0.001  owner opens waiting messages (header X-Owner-Key; ack=true clears)
  GET  /api/tollbooth/v1/alive?url=&method=  $0.001  Proof-of-Life: is this endpoint answering right now (up/paywalled/down...)
  GET  /api/tollbooth/v1/quote?url=&method=  $0.001  Price Quote: an x402 endpoint's live payment options, normalized to USD
  POST /api/tollbooth/v1/tx-preflight        $0.002  Transaction Preflight: GO/STOP before paying (budget, recipient, network, drift)
  POST /api/tollbooth/v1/secret-scan         $0.002  Secret-Leak Preflight: CLEAN/REVIEW/BLOCK before a payload leaves (nothing stored)
  POST /api/tollbooth/v1/spend-gate          $0.001  Spend Gate: ALLOW/DENY/ESCALATE a proposed spend against the owner's policy (caps, recipients, hurdle)
  GET  /api/tollbooth/v1/branch?url=&city=&zip=&street=  $0.01  Branch Resolver: the matching location page of a multi-location business + its facts
  POST /api/tollbooth/v1/failure/put         $0.002  Failure Receipt: standard why-it-failed record in a Locker for the next agent; optional PO Box dead-letter drop
  GET  /api/tollbooth/v1/terms-changed?url=&previous=  $0.005  Terms Changed?: only material pricing/limit/terms lines, diffed (stateless fingerprint)
  POST /api/tollbooth/v1/cost-estimate       $0.002  Cost-to-Complete: job cost before it starts (model + paid tools, live x402 quotes), budget/value check, cheaper routing
  POST /api/tollbooth/v1/passport/issue      $0.002  Permission Passport: signed, expiring, job-scoped permissions (tools, hosts, spend)
  POST /api/tollbooth/v1/passport/check      $0.001  ALLOW/DENY an action against a passport
  GET  /api/tollbooth/v1/passport/key        free    public key to verify passports offline
  POST /api/tollbooth/v1/needs               free    Agent Needs desk: tell OMENZ what you need, what it's worth, how often
  GET  /api/tollbooth/v1/pricing-policy      free    machine-readable fair-pricing promise
  GET  /api/tollbooth/v1/event-check?company=&claim=&days=  $0.005  Event Check: did the company actually FILE it (SEC 8-K), with the quote
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
import cost_estimate  # noqa: E402
import event_check  # noqa: E402
import checker  # noqa: E402
import locker  # noqa: E402
import failure  # noqa: E402
import handoff  # noqa: E402
import local_facts  # noqa: E402
import needs  # noqa: E402
import passport  # noqa: E402
import pobox  # noqa: E402
import receipts  # noqa: E402
import branch_resolver  # noqa: E402
import secret_scan  # noqa: E402
import spend_gate  # noqa: E402
import terms_changed  # noqa: E402
import x402_probe  # noqa: E402
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

PRICES = {"agent-ready": "$0.10", "site-check": "$0.01", "changed": "$0.005", "local-facts": "$0.01"}
DESCRIPTIONS = {
    "agent-ready": "Score 0-100 for how well AI assistants and agents can find, read and use a business website, with prioritized plain-language fixes. Deterministic, no AI calls. By OMENZ.",
    "site-check": "Website health and business facts for one URL (alive, still theirs, readable; contact paths, structured data). Deterministic. By OMENZ.",
    "local-facts": "What a local business's OWN website says right now: phone, address, hours, and holiday/temporary-closure notices quoted word for word, each with its source. Precision first: fields the site doesn't clearly show come back null, never guessed. Flags hidden structured data that disagrees with the page, sites that moved to another domain, and multi-location sites. Deterministic, no AI calls. By OMENZ.",
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

PROBE_DESC = {
    "alive": "Proof-of-Life: is this API/endpoint answering right now, before you spend money calling it? One unpaid probe: up, paywalled (valid x402 requirements), auth_required, not_found, wrong_method, degraded, tls_error or down, with latency. Never pays the target. By OMENZ.",
    "quote": "Price Quote: the live x402 payment options of any endpoint, normalized: USD price, network, stablecoin, payTo, scheme, timeout; cheapest option. Reads the 402 (v1 body or v2 header) without paying. By OMENZ.",
}
for _n in ("alive", "quote"):
    ROUTES[f"GET {BASE}/v1/{_n}"] = {
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.001", "network": NETWORK},
        "description": PROBE_DESC[_n], "mimeType": "application/json",
        "extensions": declare_discovery_extension(
            input={"url": "https://api.example.com/x402/endpoint", "method": "GET"},
            input_schema={"properties": {"url": {"type": "string", "description": "Endpoint URL to probe"},
                                         "method": {"type": "string", "description": "HTTP method the endpoint expects (default GET)"}},
                          "required": ["url"]}),
    }
ROUTES[f"POST {BASE}/v1/tx-preflight"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Transaction Preflight: GO or STOP before your agent pays an x402 endpoint. Checks it answers, the live price is within max_price_usd, payTo matches expected_pay_to, the network is allowed, the asset is a known USD stablecoin, and flags drift from the price you were quoted/listed. Never pays the target. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"url": "https://api.example.com/x402/endpoint", "method": "GET", "max_price_usd": 0.01,
               "expected_pay_to": "0x...", "networks": ["base"], "listed_price_usd": 0.005},
        input_schema={"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "max_price_usd": {"type": "number"},
                                     "expected_pay_to": {"type": "string"}, "networks": {"type": "array"},
                                     "listed_price_usd": {"type": "number"}, "allow_testnet": {"type": "boolean"}},
                      "required": ["url"]}, body_type="json"),
}
ROUTES[f"POST {BASE}/v1/secret-scan"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Secret-Leak Preflight: before a handoff, prompt or payload leaves your boundary, scan it for API keys (Anthropic, OpenAI, AWS, GitHub, Stripe, Slack, Google...), PEM keys, wallet private keys, recovery phrases, DB passwords, JWTs and card numbers. CLEAN / REVIEW / BLOCK with JSON path + offset and redacted previews. Scanned in memory, never stored or logged. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"payload": {"objective": "ship v2", "notes": "config attached"}},
        input_schema={"properties": {"payload": {"description": "String or JSON (<=256 KB) to check"}}, "required": ["payload"]},
        body_type="json"),
}

ROUTES[f"POST {BASE}/v1/spend-gate"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.001", "network": NETWORK},
    "description": "Spend Gate: ALLOW, DENY or ESCALATE before your agent spends money. Send the owner's policy (per-transaction, daily and monthly caps, approval threshold, recipient/category/network allow and block lists, hurdle: minimum expected return multiple) and the proposed spend; get the decision with every reason and the budget left. Stateless: nothing stored. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"policy": {"max_per_tx_usd": 1, "daily_cap_usd": 5, "escalate_above_usd": 0.5, "allowed_networks": ["base"],
                          "hurdle": {"min_return_multiple": 1.5}},
               "spend": {"amount_usd": 0.1, "recipient": "0x...", "network": "base", "category": "data", "expected_value_usd": 0.5,
                         "spent_today_usd": 1.2}},
        input_schema={"properties": {"policy": {"type": "object"}, "spend": {"type": "object", "description": "amount_usd required"}},
                      "required": ["spend"]}, body_type="json"),
}
ROUTES[f"GET {BASE}/v1/branch"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.01", "network": NETWORK},
    "description": "Branch Resolver: which location page of a multi-location business is the one you mean? Give the business website and a city, ZIP or street; get the matching branch page with its phone, address, hours and notices from the business's own site. Ambiguous or missing matches come back as such with candidates, never guessed. Deterministic. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"url": "https://www.example-chain.com", "city": "Pasadena"},
        input_schema={"properties": {"url": {"type": "string"}, "city": {"type": "string"}, "zip": {"type": "string"},
                                     "street": {"type": "string"}}, "required": ["url"]}),
}

ROUTES[f"POST {BASE}/v1/failure/put"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Failure Receipt + Dead-Letter Queue: when a job fails, record WHY in a standard machine-readable form (omenz.failure.v0: objective, failed_step, error_class from a fixed list, attempts, money spent, receipts, partial artifacts, suggested next step, retryable). Secret-scanned first (secrets = refused, not stored, not charged). Stored encrypted in an Agent Locker for the next agent; pass dlq_box_id to also drop a sealed pointer into an Agent PO Box used as your dead-letter queue. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"failure": {"job_id": "job-42", "objective": "get today's hours for a restaurant", "failed_step": "fetch site",
                           "error_class": "rate_limited", "attempts": [{"tool": "local-facts", "result": "429"}], "spent_usd": 0.01,
                           "suggested_next": "retry after 10 minutes"}, "to": "agent-b", "dlq_box_id": "pb_..."},
        input_schema={"properties": {"failure": {"type": "object", "description": "objective and failed_step required"},
                                     "to": {"type": "string"}, "from": {"type": "string"}, "dlq_box_id": {"type": "string"},
                                     "ttl_days": {"type": "integer"}}, "required": ["failure"]}, body_type="json"),
}
ROUTES[f"GET {BASE}/v1/terms-changed"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.005", "network": NETWORK},
    "description": "Terms Changed?: did an API or tool's pricing, limits or terms page change in a way that MATTERS? Keeps only material lines (prices, numbers with units, rate limits/quotas, commercial-use, prohibitions, refunds, data retention) and diffs them against your last fingerprint: exact lines added/removed, money_changed flag. Footer/date churn ignored. Stateless: keep the fingerprint, pass it as previous=. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"url": "https://example.com/pricing", "previous": "tc1.…"},
        input_schema={"properties": {"url": {"type": "string"}, "previous": {"type": "string", "description": "fingerprint from your last call"}},
                      "required": ["url"]}),
}

ROUTES[f"POST {BASE}/v1/cost-estimate"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Cost-to-Complete Estimate: what will this agent job cost BEFORE it starts? Give the steps (model, input/output tokens, runs, retry rate) with your model prices, and paid tool calls (price, or an x402 URL we quote live without paying). Get the total, a realistic range, the biggest cost, budget fit, value multiple, and how much routing named steps to a cheaper model saves. Deterministic arithmetic. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"job": {"models": {"big": {"input_per_mtok_usd": 8, "output_per_mtok_usd": 40}, "small": {"input_per_mtok_usd": 0.5, "output_per_mtok_usd": 3}},
                       "steps": [{"name": "extract", "model": "big", "input_tokens": 1000000, "output_tokens": 50000, "runs": 2, "retry_rate": 0.1}],
                       "tools": [{"name": "facts", "x402_url": "https://www.omenz.org/api/tollbooth/v1/local-facts?url=https://example.com", "calls": 10}],
                       "budget_usd": 30, "value_usd": 100, "alternatives": {"extract": "small"}}},
        input_schema={"properties": {"job": {"type": "object"}}, "required": ["job"]}, body_type="json"),
}
ROUTES[f"POST {BASE}/v1/passport/issue"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Permission Passport: issue a signed (Ed25519), expiring, job-scoped permission ticket for an agent: which tools, which hosts (plus explicit denies), how much it may spend, for how long (max 7 days). Carries permissions, never credentials. Any tool can check it with /passport/check or verify it offline with the public key. Limits damage when an agent is hijacked. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"scope": {"agent": "research-agent", "job_id": "job-42", "allow_tools": ["search", "local-facts"],
                         "allow_hosts": ["exa.ai", "omenz.org"], "max_spend_usd": 0.5, "expires_in_minutes": 60}},
        input_schema={"properties": {"scope": {"type": "object"}}, "required": ["scope"]}, body_type="json"),
}
ROUTES[f"POST {BASE}/v1/passport/check"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.001", "network": NETWORK},
    "description": "Permission Passport check: ALLOW or DENY an agent's next action (tool, URL/host, amount, spent so far) against its passport, with reasons, spend left and time left. Rejects forged or expired passports. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"token": "<passport token>", "action": {"tool": "search", "url": "https://api.exa.ai/search", "amount_usd": 0.007, "spent_so_far_usd": 0.1}},
        input_schema={"properties": {"token": {"type": "string"}, "action": {"type": "object"}}, "required": ["token"]}, body_type="json"),
}

ROUTES[f"GET {BASE}/v1/event-check"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.005", "network": NETWORK},
    "description": "Event Check: did a US public company actually FILE this news, or is it just going around? Give a ticker or name and the claim (CEO resigned, acquisition, results, bankruptcy, restatement, cyber incident, layoffs...). We map it to the required SEC 8-K item, pull the company's recent filings from EDGAR, and quote the sentence that states it. FILED only when one sentence carries the claim's names and roles; otherwise FILED_RELATED, NO_FILING_YET (4-business-day filing window), NOT_A_FILING_EVENT or NOT_FOUND. Deterministic. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"company": "NVDA", "claim": "Jensen Huang resigned as CEO", "days": 30},
        input_schema={"properties": {"company": {"type": "string", "description": "ticker or company name"},
                                     "claim": {"type": "string"}, "days": {"type": "integer", "description": "lookback window, 1-365 (default 30)"}},
                      "required": ["company", "claim"]}),
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
    for k, c in (("omenz-", "test"), ("x402", "x402-sdk"), ("python", "sdk"), ("node", "sdk"), ("axios", "sdk"), ("httpx", "sdk"), ("curl", "curl"),
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
            "about": "https://omenz.org", "pricing_policy": BASE + "/v1/pricing-policy",
            "tell_us_what_you_need": {"method": "POST", "path": BASE + "/v1/needs", "price": "free",
                                      "body": {"need": "required", "would_pay_usd_per_call": "number", "frequency": needs.FREQ,
                                               "current_workaround": "text", "task_context": "text", "reply_box_id": "pb_... (optional)"}}}


@app.get(BASE + "/v1/agent-ready")
def agent_ready(url: str = Query(...)):
    return checker.check(url)


@app.get(BASE + "/v1/local-facts")
def local_facts_route(request: Request, url: str = Query(...)):
    try:
        r = local_facts.lookup(url)
    except Exception:
        request.state.extra.update({"action": "local_facts", "error": 502})
        return JSONResponse({"error": "lookup failed; not charged"}, status_code=502)
    got = [k for k in ("name", "phone", "address") if (r.get(k) or {}).get("value")]
    request.state.extra.update({"action": "local_facts", "lf_status": r.get("status") or r.get("error"), "fields": len(got),
                                "notices": len(r.get("notices") or []), "hidden": len(((r.get("hidden_data") or {}).get("items")) or [])})
    if r.get("error") in ("invalid_url",):
        return JSONResponse(r, status_code=400)
    return r


@app.get(BASE + "/v1/alive")
def alive_route(request: Request, url: str = Query(...), method: str = "GET"):
    r = x402_probe.alive(url, method)
    request.state.extra.update({"action": "alive", "verdict": r.get("verdict")})
    return r


@app.get(BASE + "/v1/quote")
def quote_route(request: Request, url: str = Query(...), method: str = "GET"):
    r = x402_probe.quote(url, method)
    request.state.extra.update({"action": "quote", "q_status": r.get("status"), "options": len(r.get("options") or [])})
    return r


@app.post(BASE + "/v1/tx-preflight")
def tx_preflight_route(request: Request, body: dict = Body(...)):
    if not isinstance(body.get("url"), str):
        return JSONResponse({"error": "url required"}, status_code=422)
    try:
        r = x402_probe.preflight(body["url"], body.get("method", "GET"), body.get("max_price_usd"), body.get("expected_pay_to"),
                                 body.get("networks"), body.get("listed_price_usd"), bool(body.get("allow_testnet")))
    except (TypeError, ValueError):
        return JSONResponse({"error": "max_price_usd / listed_price_usd must be numbers, networks a list"}, status_code=422)
    request.state.extra.update({"action": "tx_preflight", "verdict": r.get("verdict")})
    return r


@app.post(BASE + "/v1/secret-scan")
def secret_scan_route(request: Request, body: dict = Body(...)):
    if "payload" not in body:
        return JSONResponse({"error": "payload required"}, status_code=422)
    r = secret_scan.scan(body["payload"])
    request.state.extra.update({"action": "secret_scan", "verdict": r.get("verdict"), "findings": len(r.get("findings") or [])})
    return r


@app.post(BASE + "/v1/spend-gate")
def spend_gate_route(request: Request, body: dict = Body(...)):
    if not isinstance(body.get("spend"), dict):
        return JSONResponse({"error": "spend object with amount_usd required"}, status_code=422)
    r = spend_gate.check(body.get("policy") if isinstance(body.get("policy"), dict) else {}, body["spend"])
    request.state.extra.update({"action": "spend_gate", "decision": r.get("decision")})
    if r.get("decision") == "ERROR":
        return JSONResponse(r, status_code=422)
    return r


@app.get(BASE + "/v1/branch")
def branch_route(request: Request, url: str = Query(...), city: str | None = None, zip: str | None = None, street: str | None = None):
    if not (city or zip or street):
        return JSONResponse({"error": "give at least one of city, zip, street"}, status_code=422)
    try:
        r = branch_resolver.resolve(url, city, zip, street)
    except Exception:
        request.state.extra.update({"action": "branch", "error": 502})
        return JSONResponse({"error": "lookup failed; not charged"}, status_code=502)
    request.state.extra.update({"action": "branch", "b_status": r.get("status")})
    return JSONResponse(json.loads(json.dumps(r, default=list)))


@app.post(BASE + "/v1/failure/put")
def failure_put(request: Request, body: dict = Body(...)):
    r = _locker_call(failure.put, body.get("failure"), body.get("to"), body.get("from"), body.get("dlq_box_id"), body.get("ttl_days", 14))
    request.state.extra["action"] = "failure_put"
    if isinstance(r, dict):
        request.state.extra.update({"error_class": r.get("error_class"), "dlq": bool(r.get("dlq"))})
    else:
        request.state.extra["error"] = r.status_code
    return r


@app.get(BASE + "/v1/terms-changed")
def terms_changed_route(request: Request, url: str = Query(...), previous: str | None = None):
    r = terms_changed.check(url, previous)
    request.state.extra.update({"action": "terms_changed", "tc_state": r.get("state")})
    if r.get("state") == "ERROR":
        return JSONResponse(r, status_code=422)
    return r


@app.post(BASE + "/v1/cost-estimate")
def cost_estimate_route(request: Request, body: dict = Body(...)):
    r = cost_estimate.estimate(body.get("job") if isinstance(body.get("job"), dict) else None)
    request.state.extra.update({"action": "cost_estimate", "ce_status": r.get("status")})
    if r.get("status") == "error":
        return JSONResponse(r, status_code=422)
    return r


@app.post(BASE + "/v1/passport/issue")
def passport_issue(request: Request, body: dict = Body(...)):
    r = passport.issue(body.get("scope"))
    request.state.extra["action"] = "passport_issue"
    if r.get("error"):
        return JSONResponse(r, status_code=422)
    return r


@app.post(BASE + "/v1/passport/check")
def passport_check(request: Request, body: dict = Body(...)):
    if not body.get("token"):
        return JSONResponse({"error": "token required"}, status_code=422)
    r = passport.check(body["token"], body.get("action") if isinstance(body.get("action"), dict) else {})
    request.state.extra.update({"action": "passport_check", "decision": r.get("decision")})
    return r


@app.get(BASE + "/v1/passport/key")
def passport_key():
    return passport.key()


@app.post(BASE + "/v1/needs")
def needs_route(request: Request, body: dict = Body(...)):
    code, r = needs.submit(body, request.headers.get("user-agent"))
    request.state.extra.update({"action": "need", "need_ok": code == 200})
    return JSONResponse(r, status_code=code)


@app.get(BASE + "/v1/pricing-policy")
def pricing_policy():
    return {**needs.POLICY, "routes": {k: v["accepts"]["price"] for k, v in ROUTES.items()}}


@app.get(BASE + "/v1/event-check")
def event_check_route(request: Request, company: str = Query(...), claim: str = Query(...), days: int = 30):
    r = event_check.check(company, claim, days)
    request.state.extra.update({"action": "event_check", "ec_verdict": r.get("verdict")})
    if r.get("verdict") == "ERROR":
        return JSONResponse(r, status_code=502 if "failed" in (r.get("error") or "") else 422)
    return r


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
