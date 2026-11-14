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
  POST /api/tollbooth/v1/claim-evidence      $0.005  Claim -> Evidence: does this source say what you claim? quote, or what's missing
  POST /api/tollbooth/v1/preflight           $0.005  Agent Preflight: READY/BLOCKED before a job (tools live + priced, budget, passport)
  POST /api/tollbooth/v1/ledger/create       $0.002  Job Ledger: hash-chained, append-only record of a job (key shown once)
  POST /api/tollbooth/v1/ledger/append       $0.001  add an entry (tool_call/spend/receipt/handoff/failure/output/status/note/decision)
  GET  /api/tollbooth/v1/ledger/get?id=      $0.001  entries + totals + chain_intact
  GET  /api/tollbooth/v1/capability-card?url= $0.002 Capability Card for any x402 service (index or endpoint)
  GET  /api/tollbooth/v1/card                free    OMENZ's own capability card
  POST /api/tollbooth/v1/queue/{create,enqueue,claim,heartbeat,complete,fail,escalate,resolve,bid,award}, GET queue/status
                                             Agent Workforce: work queue with leases, checkpoints/recovery, escalation, bidding, roster, scheduling
  GET  /api/tollbooth/v1/market/find?q=      $0.002  Capability Finder / Procurement / Quote Comparator / Substitute / Rate-Limit Router over ~35k x402 endpoints
  GET  /api/tollbooth/v1/market/reliability?url= $0.002 Micropayment Reliability Score 0-100 with reasons
  GET  /api/tollbooth/v1/vendor-check?url=   $0.01   Vendor Due-Diligence Pack
  POST /api/tollbooth/v1/contract/build      $0.002  A2A Contract Builder (signed terms + deterministic acceptance tests)
  POST /api/tollbooth/v1/contract/accept     $0.005  Acceptance Test as a Service -> PASS/FAIL, escrow verdict, signed attestation (reputation)
  GET  /api/tollbooth/v1/reputation?agent=   $0.001  Reputation Receipts: an agent's OMENZ-checked job history
  POST /api/tollbooth/v1/evidence/bundle     $0.002  Machine Evidence Bundle (signed, hash-listed)
  POST /api/tollbooth/v1/finance/{reconcile,forecast,watchdog,snapshot,refund-request}  Agent finance back office
  GET  /api/tollbooth/v1/terms-extract?url=  $0.005  API Terms / Data-License Checker
  GET  /api/tollbooth/v1/freshness?url=&kind= $0.001 Source Freshness / Result TTL
  POST /api/tollbooth/v1/dedupe              $0.001  Duplicate-Work Detector (private namespace)
  POST /api/tollbooth/v1/context-diet        $0.001  Context Diet
  GET  /api/tollbooth/v1/status              free    Machine Commerce Status Page (OMENZ)
  GET  /api/tollbooth/v1/starter-pack        free    Agent Business Starter Pack
  ANY  /api/tollbooth/ayne/v1/<route>       free    AYNE: the agent Playzone (2000 req/day, 300/visitor): live sandbox or labeled samples of every route
  GET  /openapi.json  /.well-known/x402  /.well-known/agent-card.json   free  machine discovery (OpenAPI+x402, x402 list, A2A card)
  POST /mcp                                  free    remote MCP server (tools/list = all tools; tools/call runs in AYNE)
  GET  /api/tollbooth/v1/wallet/{balance,spend,runway}?address=   agent-wallet tools (USDC on Base, public chain data)
  GET  /api/tollbooth/v1/market/payee?address=  /market/price-index?q=&price_usd=   payee check + x402 price index
  POST /api/tollbooth/v1/authorize           $0.001  OMENZ Authorize: APPROVE/REVIEW/DECLINE + signed authorization before any x402 payment
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
import authorize  # noqa: E402
import ayne  # noqa: E402
import capability_card  # noqa: E402
import changed  # noqa: E402
import claim_evidence  # noqa: E402
import contracts  # noqa: E402
import cost_estimate  # noqa: E402
import discovery  # noqa: E402
import event_check  # noqa: E402
import checker  # noqa: E402
import locker  # noqa: E402
import failure  # noqa: E402
import finance  # noqa: E402
import handoff  # noqa: E402
import hygiene  # noqa: E402
import ledger  # noqa: E402
import local_facts  # noqa: E402
import market  # noqa: E402
import needs  # noqa: E402
import passport  # noqa: E402
import preflight  # noqa: E402
import pobox  # noqa: E402
import receipts  # noqa: E402
import branch_resolver  # noqa: E402
import secret_scan  # noqa: E402
import spend_gate  # noqa: E402
import terms_changed  # noqa: E402
import wallet  # noqa: E402
import workforce  # noqa: E402
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

ROUTES[f"POST {BASE}/v1/claim-evidence"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.005", "network": NETWORK},
    "description": "Claim -> Evidence: does this source actually say what you're about to cite it for? Send a claim and the source URL; get SUPPORTED with the exact sentence, PARTIAL with the closest sentences and which numbers/names are missing, NOT_FOUND, or CHECK_NEGATION when the matching sentence denies it. Strict: every number must appear next to the claim's own names (no borrowing another plan's price). Deterministic, no AI calls. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"claim": "Stripe charges 2.9% + 30 cents per successful card charge", "url": "https://stripe.com/pricing"},
        input_schema={"properties": {"claim": {"type": "string"}, "url": {"type": "string"}}, "required": ["claim", "url"]}, body_type="json"),
}

def _paid(method, path, price, desc, inp, schema, body=False):
    ROUTES[f"{method} {BASE}/v1/{path}"] = {
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": price, "network": NETWORK}, "description": desc,
        "mimeType": "application/json",
        "extensions": declare_discovery_extension(input=inp, input_schema=schema, **({"body_type": "json"} if body else {}))}


_paid("POST", "preflight", "$0.005",
      "Agent Preflight: can this agent finish the job with what it has, BEFORE it spends? Give the paid tools it needs (url, method, calls, max price), a budget and optionally its Permission Passport. We check each tool is answering and its live x402 price (never paying), the total against the budget, and the passport against each host and the total. READY, or BLOCKED with exactly what's missing. By OMENZ.",
      {"job": {"tools": [{"name": "facts", "url": "https://www.omenz.org/api/tollbooth/v1/local-facts?url=https://example.com", "calls": 10, "max_price_usd": 0.02}],
               "budget_usd": 1, "passport_token": "<optional>"}},
      {"properties": {"job": {"type": "object"}}, "required": ["job"]}, body=True)
_paid("POST", "ledger/create", "$0.002",
      "Agent Job Ledger: open an append-only, hash-chained record for one job (tool calls, spend, receipts, handoffs, failures, outputs, status). Returns ledger_id + ledger_key (shown once). Kept 90 days. By OMENZ.",
      {"job_id": "job-42", "objective": "get today's hours for 20 restaurants"},
      {"properties": {"job_id": {"type": "string"}, "objective": {"type": "string"}}}, body=True)
_paid("POST", "ledger/append", "$0.001",
      "Agent Job Ledger: append one entry (type tool_call|spend|receipt|handoff|failure|output|status|note|decision, any fields, amount_usd optional). Each entry is chained to the previous by sha256; secrets are refused. Header X-Ledger-Key. By OMENZ.",
      {"ledger_id": "lg_...", "entry": {"type": "tool_call", "tool": "local-facts", "amount_usd": 0.01, "result": "ok"}},
      {"properties": {"ledger_id": {"type": "string"}, "entry": {"type": "object"}}, "required": ["ledger_id", "entry"]}, body=True)
_paid("GET", "ledger/get", "$0.001",
      "Agent Job Ledger: read entries (since_seq for only new ones), totals (spent, counts by type, last status) and chain_intact: proof nothing was edited or removed. Header X-Ledger-Key. By OMENZ.",
      {"id": "lg_...", "since_seq": 0}, {"properties": {"id": {"type": "string"}, "since_seq": {"type": "integer"}}, "required": ["id"]})
_paid("GET", "capability-card", "$0.002",
      "Agent Capability Card: a standard machine-readable card (omenz.capability-card.v0) of what any x402 service offers: endpoints, live prices and payment options, input/output examples from its discovery data, latency. Works on a service index or a single endpoint; never pays. By OMENZ.",
      {"url": "https://api.example.com/x402/endpoint", "method": "GET"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}}, "required": ["url"]})

WQ = {
    "create": ("$0.002", "Agent Workforce: create a work queue for a team of agents. Returns queue_id + owner_key + worker_key (shown once). Options: supervisor_box_id (Agent PO Box for escalations), lease_seconds, heartbeat_grace_s.",
               {"name": "restaurant-hours crew", "supervisor_box_id": "pb_...", "lease_seconds": 900}),
    "enqueue": ("$0.001", "Agent Workforce: add a job (title, payload, priority, not_before, repeat_every_minutes, max_attempts, bidding). Owner key. Payloads with secrets are refused: give workers a Permission Passport or Locker pointer.",
                {"queue_id": "wq_...", "title": "get hours for 20 restaurants", "payload": {"city": "Pasadena"}, "priority": 5}),
    "claim": ("$0.001", "Agent Workforce: a worker claims the highest-priority ready job and gets a LEASE (it is now responsible). Expired leases come back with the last checkpoint so a replacement can resume.",
              {"queue_id": "wq_...", "worker_id": "agent-7"}),
    "heartbeat": ("$0.001", "Agent Workforce: worker is alive; extends its lease and stores a checkpoint (e.g. a Locker id + step) for dead-agent recovery.",
                  {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "checkpoint": {"locker_id": "lk_...", "step": 3}}),
    "complete": ("$0.001", "Agent Workforce: worker finishes its leased job with a result; repeating jobs are rescheduled automatically.",
                 {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "result": {"ok": True}}),
    "fail": ("$0.001", "Agent Workforce: worker reports failure; the job retries until max_attempts, then goes dead.",
             {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "reason": "site blocked", "retry": True}),
    "escalate": ("$0.001", "Agent Workforce: hand a job up to the supervisor (sealed drop into the supervisor's Agent PO Box).",
                 {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "reason": "customer asked for a refund"}),
    "resolve": ("$0.001", "Agent Workforce: owner resolves an escalated/dead job: requeue, close or kill.",
                {"queue_id": "wq_...", "item_id": "wi_...", "action": "requeue"}),
    "bid": ("$0.001", "Agent Workforce: worker bids on a job open for bidding (price_usd, eta_minutes).",
            {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "price_usd": 0.02, "eta_minutes": 10}),
    "award": ("$0.001", "Agent Workforce: owner awards a bidding job to one bidder; the award becomes that worker's lease.",
              {"queue_id": "wq_...", "item_id": "wi_...", "worker_id": "agent-7"}),
}
for _a, (_p, _d, _i) in WQ.items():
    _paid("POST", "queue/" + _a, _p, _d + " Header X-Queue-Key. By OMENZ.", _i, {"properties": {k: {} for k in _i}}, body=True)
_paid("GET", "queue/status", "$0.001",
      "Agent Workforce: who is responsible for what right now (holders + lease time left), counts by state, escalations, roster (available/last seen/current job), scheduled jobs; or one item's full history with item_id. Header X-Queue-Key. By OMENZ.",
      {"queue_id": "wq_...", "item_id": "(optional)"}, {"properties": {"queue_id": {"type": "string"}, "item_id": {"type": "string"}}, "required": ["queue_id"]})

_paid("GET", "market/find", "$0.002",
      "Agent Market: find the paid tool for a capability across ~35,000 x402 endpoints (Bazaar index, refreshed weekly). Ranked by match, then real 30-day usage (calls, unique payers); filter by max_price_usd and network; exclude= a vendor to get substitutes (tool down or rate-limited); the top picks are probed live (never paid) for status, price and drift. Capability Finder, Procurement Desk, Quote Comparator, Tool Substitute Finder and Rate-Limit Router in one call. By OMENZ.",
      {"q": "weather forecast by city", "max_price_usd": 0.01, "network": "base", "exclude": "", "limit": 10, "live_check": 3},
      {"properties": {"q": {"type": "string"}, "max_price_usd": {"type": "number"}, "network": {"type": "string"}, "exclude": {"type": "string"},
                      "limit": {"type": "integer"}, "live_check": {"type": "integer"}, "min_payers": {"type": "integer"}}, "required": ["q"]})
_paid("GET", "market/reliability", "$0.002",
      "Micropayment Reliability Score: should your agent trust this paid endpoint? 0-100 + grade with every reason: public 30-day usage, answering now with valid x402 requirements, speed, live price vs listed price, payTo vs listed payTo (catches swapped wallets). Never pays. By OMENZ.",
      {"url": "https://api.example.com/x402/endpoint", "method": "GET"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}}, "required": ["url"]})
_paid("GET", "vendor-check", "$0.01",
      "Vendor Due-Diligence Pack: before your agent depends on an unknown paid API: reliability score + the vendor domain's health (live/parked/moved) + its terms/pricing page digest (material lines) + flags. Never pays. By OMENZ.",
      {"url": "https://api.example.com/x402/endpoint"}, {"properties": {"url": {"type": "string"}, "method": {"type": "string"}}, "required": ["url"]})

_paid("POST", "contract/build", "$0.002",
      "A2A Contract Builder: turn a machine job into signed terms both agents hold: deliverable, deterministic acceptance tests (required_fields, field_types, regex, min_items, max_bytes, equals, url_alive, claim_evidence), max spend, deadline, parties. Ed25519-signed by OMENZ; verify offline with /v1/passport/key. By OMENZ.",
      {"terms": {"buyer": "agent-a", "seller": "agent-b", "deliverable": "hours for 3 restaurants", "max_spend_usd": 0.1, "deadline": 1900000000,
                 "acceptance": [{"type": "min_items", "field": "results", "n": 3}, {"type": "regex", "field": "source", "pattern": "https://.+"}]}},
      {"properties": {"terms": {"type": "object"}}, "required": ["terms"]}, body=True)
_paid("POST", "contract/accept", "$0.005",
      "Acceptance Test as a Service + escrow verdict: a neutral party runs the contract's tests on what was delivered. PASS/FAIL per test, escrow_verdict RELEASE/REFUND (OMENZ never holds funds: the payer acts on it), and a signed attestation that feeds the seller's Reputation Receipts. By OMENZ.",
      {"token": "<contract token>", "delivered": {"results": [1, 2, 3], "source": "https://example.com"}},
      {"properties": {"token": {"type": "string"}, "delivered": {}}, "required": ["token", "delivered"]}, body=True)
_paid("GET", "reputation", "$0.001",
      "Reputation Receipts: an agent's job history as checked by OMENZ Acceptance Test: jobs, passed, failed, late, pass rate, distinct buyers (low = weak evidence), recent attestations. Not self-reported. By OMENZ.",
      {"agent": "agent-b"}, {"properties": {"agent": {"type": "string"}}, "required": ["agent"]})
_paid("POST", "evidence/bundle", "$0.002",
      "Machine Evidence Bundle: package receipts, ledger heads, attestation tokens, claims and sources into one signed, hash-listed bundle (merkle-style root) that any agent can verify offline. For disputes, audits, refunds and handoffs. By OMENZ.",
      {"items": [{"kind": "receipt", "id": "rc_..."}, {"kind": "attestation", "token": "..."}], "label": "job 42"},
      {"properties": {"items": {"type": "array"}, "label": {"type": "string"}}, "required": ["items"]}, body=True)

FIN = {
    "reconcile": ("$0.005", "Invoice/Payment Reconciler: invoice lines vs USDC-on-Base payments, each transaction checked on-chain (payer, payee, amount): MATCH / UNDERPAID / OVERPAID / MISSING / UNVERIFIED, duplicates and line-total errors flagged.",
                  {"invoice": {"payee": "0x...", "lines": [{"desc": "lookups", "amount_usd": 0.5}], "total_usd": 0.5}, "payments": [{"tx_hash": "0x...", "payer": "0x...", "amount_usd": 0.5}]}),
    "forecast": ("$0.002", "Agent Budget Forecaster: spend history -> daily rate, next 7/30-day projection, trend, biggest dependencies.",
                 {"spend": [{"at": 1763000000, "amount_usd": 0.01, "tool": "search"}]}),
    "watchdog": ("$0.005", "Subscription Watchdog: the paid endpoints your agent business relies on (up to 8): live price vs expected, down/up, terms/pricing page changed (pass back fingerprints).",
                 {"endpoints": [{"url": "https://api.example.com/x402/endpoint", "expected_price_usd": 0.005, "terms_url": "https://example.com/pricing"}]}),
    "snapshot": ("$0.002", "Machine Warranty / Purchase Snapshot: signed record of exactly what a paid endpoint promised (live x402 requirements, description, examples) at purchase time.",
                 {"url": "https://api.example.com/x402/endpoint", "method": "GET"}),
    "refund-request": ("$0.002", "Structured Refund Request: order + failure receipt + payment receipts + purchase snapshot -> a standard signed dispute object with evidence strength and gaps. OMENZ packages evidence; it doesn't rule or move money.",
                       {"order": {"seller": "svc", "description": "lookup", "amount_usd": 0.01}, "failure": {"error_class": "payment_taken_no_result"}, "receipt_ids": ["rc_..."], "snapshot_token": "...", "remedy": "refund"}),
}
for _a, (_p, _d, _i) in FIN.items():
    _paid("POST", "finance/" + _a, _p, _d + " Deterministic; never pays a target. By OMENZ.", _i, {"properties": {k: {} for k in _i}}, body=True)

_paid("GET", "terms-extract", "$0.005",
      "API Terms Extractor / Data-License Checker: before your agent uses a dataset or API commercially: a terms/license page -> clauses by category (commercial use, attribution, rate limits, retention, training on your data, prohibited uses, resale, refunds, liability, termination, license type) with quotes, plus plain flags (no_commercial_use, attribution_required, may_train_on_your_data, no_resale, no_scraping, non_refundable). Pattern-based, not legal advice. By OMENZ.",
      {"url": "https://example.com/terms"}, {"properties": {"url": {"type": "string"}}, "required": ["url"]})
_paid("GET", "freshness", "$0.001",
      "Source Freshness / Result TTL: how long can your agent reuse a result before paying to fetch it again? The source's own Last-Modified, ETag and Cache-Control + a reuse window by data kind (price, quote, hours, weather, news, stock, crypto, business_facts, terms, docs, filing, profile, search) + how to revalidate cheaply (304). By OMENZ.",
      {"url": "https://example.com/pricing", "kind": "price"}, {"properties": {"url": {"type": "string"}, "kind": {"type": "string"}}, "required": ["url"]})
_paid("POST", "dedupe", "$0.001",
      "Duplicate-Work Detector: before your agent pays to run a task, check whether someone in your team (same private namespace_key) already did it: normalized fingerprint -> HIT with the earlier result pointer, or MISS (pass result_pointer to register this run). By OMENZ.",
      {"namespace_key": "your-private-team-key-16+", "task": {"q": "hours for Flemings Pasadena", "day": "2026-11-14"}, "result_pointer": "lk_...", "ttl_hours": 24},
      {"properties": {"namespace_key": {"type": "string"}, "task": {}, "result_pointer": {"type": "string"}, "ttl_hours": {"type": "integer"}},
       "required": ["namespace_key", "task"]}, body=True)
_paid("POST", "context-diet", "$0.001",
      "Context Diet: shrink a packet before it fills your context: drops empty fields, dedupes lists, cuts long strings to a head + sha256 pointer, caps list length, always keeps required fields; reports bytes and approximate tokens saved. By OMENZ.",
      {"packet": {"objective": "ship v2", "notes": "...long..."}, "required": ["objective"], "max_string_chars": 400},
      {"properties": {"packet": {}, "required": {"type": "array"}, "max_string_chars": {"type": "integer"}, "max_list_items": {"type": "integer"}},
       "required": ["packet"]}, body=True)

_paid("GET", "wallet/balance", "$0.001",
      "Agent Wallet Balance: USDC and ETH balance of any wallet on Base (public chain data). Never moves funds, no key needed. By OMENZ.",
      {"address": "0x..."}, {"properties": {"address": {"type": "string"}}, "required": ["address"]})
_paid("GET", "wallet/spend", "$0.005",
      "Agent Wallet Spend Report: what has this wallet been paying for? Outgoing USDC payments on Base over the last N days (max 14), grouped by payee, each payee named with the x402 services that pay out to it (from the ~35k-endpoint x402 index), totals, daily rate, micropayment count, share going to known x402 sellers. Public chain data. By OMENZ.",
      {"address": "0x...", "days": 7}, {"properties": {"address": {"type": "string"}, "days": {"type": "number"}}, "required": ["address"]})
_paid("GET", "wallet/runway", "$0.005",
      "Agent Wallet Runway: how many days before this agent wallet runs dry? USDC balance / recent daily spend -> days left, OK / LOW / CRITICAL, and the top cost drivers by payee. Public chain data on Base. By OMENZ.",
      {"address": "0x...", "days": 7, "low_days": 3}, {"properties": {"address": {"type": "string"}, "days": {"type": "number"},
                                                         "low_days": {"type": "number"}, "critical_days": {"type": "number"}}, "required": ["address"]})
_paid("GET", "market/payee", "$0.001",
      "Payee Check: before paying an address, is it a known x402 seller? Matches the pay-to address against the payout addresses of ~35k listed x402 endpoints: KNOWN_SELLER (which services, 30-day calls and payers), SHARED_ADDRESS (platform/facilitator wallet) or UNKNOWN. By OMENZ.",
      {"address": "0x..."}, {"properties": {"address": {"type": "string"}}, "required": ["address"]})
_paid("GET", "market/price-index", "$0.002",
      "x402 Price Index / Fair Price Check: the going rate for a capability across listed x402 endpoints: comparables, sellers, min / p25 / median / p75 / max and usage-weighted median; pass price_usd (or a listed url) to get its percentile and FAIR / LOW / ABOVE_MARKET / HIGH. By OMENZ.",
      {"q": "web search", "price_usd": 0.005}, {"properties": {"q": {"type": "string"}, "price_usd": {"type": "number"}, "url": {"type": "string"},
                                                  "min_payers": {"type": "integer"}}, "required": ["q"]})

_paid("POST", "authorize", "$0.001",
      "OMENZ Authorize: the authorization step for agent payments. One call before paying any x402 endpoint: live quote + preflight (up, price within max, network, stablecoin, expected payTo), payee check (known x402 seller?), fair-price check vs comparable endpoints, the owner's spend policy and Permission Passport if sent -> APPROVE / REVIEW / DECLINE with reasons and a signed 5-minute authorization code anyone can verify. Never pays the target. By OMENZ.",
      {"url": "https://api.example.com/x402/endpoint", "method": "POST", "max_price_usd": 0.05, "expected_pay_to": "0x...",
       "policy": {"daily_cap_usd": 5}, "spend": {"spent_today_usd": 1.2}, "passport_token": "(optional)"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "max_price_usd": {"type": "number"}, "expected_pay_to": {"type": "string"},
                      "policy": {"type": "object"}, "spend": {"type": "object"}, "passport_token": {"type": "string"}}, "required": ["url"]}, body=True)

server = x402ResourceServer(HTTPFacilitatorClient({"url": FACILITATOR}))
server.register("eip155:*", ExactEvmServerScheme())

app = FastAPI(title="OMENZ x402 tollbooth", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
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
    request.state.ayne = False
    if request.url.path.startswith(BASE + "/ayne"):
        return await _ayne(request, call_next, t0)
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


async def _ayne(request, call_next, t0):
    from starlette.concurrency import run_in_threadpool
    path = request.url.path
    sub = path[len(BASE + "/ayne/v1"):] if path.startswith(BASE + "/ayne/v1/") else ""
    method = request.method.upper()
    ua = request.headers.get("user-agent", "")
    vis = ayne.visitor(request.headers.get("x-forwarded-for", "").split(",")[0].strip(), ua)
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "ayne", "route": sub or "/", "method": method,
          "visitor": vis, "ua_class": _ua_class(ua), "country": request.headers.get("x-vercel-ip-country", "")}
    if not sub or sub == "/":
        ev["mode"] = "index"
        await run_in_threadpool(ayne.log, ev)
        return JSONResponse(ayne.index(ROUTES, BASE))
    raw = await request.body()
    ev["fields"] = ayne.field_names(raw) if raw else sorted(request.query_params.keys())[:30]
    internal = request.headers.get("x-ayne-internal") == ayne.internal_secret()
    if internal and request.headers.get("x-ayne-visitor"):
        vis = request.headers["x-ayne-visitor"][:16]
        ev["visitor"], ev["via"] = vis, "mcp"
    ok, why, n = await run_in_threadpool(ayne.take, vis)
    if not ok:
        ev.update(mode="capped", cap=why)
        await run_in_threadpool(ayne.log, ev)
        return JSONResponse({"error": f"AYNE {why} cap reached ({ayne.DAILY_CAP}/day total, {ayne.VISITOR_CAP}/day per visitor). "
                                      "The paid routes are always open: " + BASE, "ayne": True}, status_code=429)
    key = f"{method} {sub}"
    paid_key = f"{method} {BASE}/v1{sub}"
    if key in ayne.LIVE:
        if len(raw) > ayne.MAX_BODY:
            ev.update(mode="too_big")
            await run_in_threadpool(ayne.log, ev)
            return JSONResponse({"error": f"AYNE bodies are limited to {ayne.MAX_BODY} bytes; the paid route takes more", "ayne": True}, status_code=413)
        request.scope["path"] = BASE + "/v1" + sub
        request.scope["raw_path"] = request.scope["path"].encode()
        request.state.ayne = True
        resp = await call_next(request)
        resp.headers["x-ayne"] = "live"
        ev.update(mode="live", status=resp.status_code)
    elif paid_key in ROUTES:
        fx = ayne.fixtures().get(paid_key) or {}
        resp = JSONResponse({"ayne": True, "sample": True, "note": "Sample response from AYNE. The paid route runs it on your real input.",
                             "paid_route": {"method": method, "url": "https://www.omenz.org" + BASE + "/v1" + sub,
                                            "price": ROUTES[paid_key]["accepts"]["price"]},
                             "description": ROUTES[paid_key]["description"], "example_input": fx.get("example_input"),
                             "sample_response": fx.get("sample_response")})
        resp.headers["x-ayne"] = "sample"
        ev.update(mode="sample", status=200)
    else:
        alt = [k.split(" ", 1)[0] for k in ROUTES if k.split(" ", 1)[1] == BASE + "/v1" + sub]
        resp = JSONResponse({"ayne": True, "error": "OMENZ doesn't have this yet" if not alt else f"this route takes {', '.join(alt)}",
                             "noted": True, "tell_us_what_you_need": BASE + "/v1/needs (free)", "all_routes": BASE + "/ayne/v1"},
                            status_code=404 if not alt else 405)
        ev.update(mode="gap" if not alt else "wrong_method", status=resp.status_code)
    ev["latency_ms"] = int((time.time() - t0) * 1000)
    await run_in_threadpool(ayne.log, ev)
    return resp


@app.get(BASE)
def index():
    return {"service": "OMENZ x402 tollbooth", "protocol": "x402 v2", "network": NETWORK, "asset": "USDC",
            "routes": {k: {"price": v["accepts"]["price"], "description": v["description"]} for k, v in ROUTES.items()},
            "about": "https://omenz.org", "pricing_policy": BASE + "/v1/pricing-policy", "capability_card": BASE + "/v1/card",
            "playzone": {"name": "AYNE", "url": BASE + "/ayne/v1", "price": "free", "cap": "2000 requests/day"},
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


@app.post(BASE + "/v1/claim-evidence")
def claim_evidence_route(request: Request, body: dict = Body(...)):
    if not (isinstance(body.get("claim"), str) and isinstance(body.get("url"), str)):
        return JSONResponse({"error": "claim and url (strings) required"}, status_code=422)
    r = claim_evidence.check(body["claim"][:600], body["url"])
    request.state.extra.update({"action": "claim_evidence", "ce_verdict": r.get("verdict")})
    if r.get("verdict") == "ERROR":
        return JSONResponse(r, status_code=422)
    return r


@app.post(BASE + "/v1/preflight")
def preflight_route(request: Request, body: dict = Body(...)):
    r = preflight.check(body.get("job") if isinstance(body.get("job"), dict) else None)
    request.state.extra.update({"action": "preflight", "pf_verdict": r.get("verdict")})
    if r.get("verdict") == "ERROR":
        return JSONResponse(r, status_code=422)
    return r


@app.post(BASE + "/v1/ledger/create")
def ledger_create(request: Request, body: dict = Body(default={})):
    request.state.extra["action"] = "ledger_create"
    return _locker_call(ledger.create, body.get("job_id"), body.get("objective"))


@app.post(BASE + "/v1/ledger/append")
def ledger_append(request: Request, body: dict = Body(...), x_ledger_key: str | None = Header(None)):
    request.state.extra["action"] = "ledger_append"
    return _locker_call(ledger.append, body.get("ledger_id"), x_ledger_key, body.get("entry"))


@app.get(BASE + "/v1/ledger/get")
def ledger_get(request: Request, id: str = Query(...), since_seq: int = 0, x_ledger_key: str | None = Header(None)):
    request.state.extra["action"] = "ledger_get"
    return _locker_call(ledger.get, id, x_ledger_key, since_seq)


@app.get(BASE + "/v1/capability-card")
def capability_card_route(request: Request, url: str = Query(...), method: str = "GET"):
    r = capability_card.card(url, method)
    request.state.extra.update({"action": "capability_card", "cc_status": r.get("status")})
    if r.get("status") == "error":
        return JSONResponse(r, status_code=422)
    return r


@app.get(BASE + "/v1/card")
def own_card():
    return capability_card.own_card(ROUTES, "https://www.omenz.org", BASE + "/v1/pricing-policy", BASE + "/v1/needs")


def _wq(fn, *a):
    r = _locker_call(fn, *a)
    return r


@app.post(BASE + "/v1/queue/{action}")
def queue_post(action: str, request: Request, body: dict = Body(default={}), x_queue_key: str | None = Header(None)):
    request.state.extra["action"] = "queue_" + action
    b, q, k = body, body.get("queue_id"), x_queue_key
    calls = {
        "create": lambda: workforce.create(b.get("name"), b.get("supervisor_box_id"), b.get("lease_seconds", 900), b.get("heartbeat_grace_s", 300)),
        "enqueue": lambda: workforce.enqueue(q, k, b.get("title"), b.get("payload"), b.get("priority", 0), b.get("not_before"),
                                             b.get("repeat_every_minutes"), b.get("max_attempts", 3), bool(b.get("bidding"))),
        "claim": lambda: workforce.claim(q, k, b.get("worker_id")),
        "heartbeat": lambda: workforce.heartbeat(q, k, b.get("worker_id"), b.get("item_id"), b.get("checkpoint"), b.get("status")),
        "complete": lambda: workforce.complete(q, k, b.get("worker_id"), b.get("item_id"), b.get("result")),
        "fail": lambda: workforce.fail(q, k, b.get("worker_id"), b.get("item_id"), b.get("reason"), b.get("retry", True)),
        "escalate": lambda: workforce.escalate(q, k, b.get("worker_id"), b.get("item_id"), b.get("reason")),
        "resolve": lambda: workforce.resolve(q, k, b.get("item_id"), b.get("action", "requeue"), b.get("note")),
        "bid": lambda: workforce.bid(q, k, b.get("worker_id"), b.get("item_id"), b.get("price_usd"), b.get("eta_minutes"), b.get("note")),
        "award": lambda: workforce.award(q, k, b.get("item_id"), b.get("worker_id")),
    }
    if action not in calls:
        return JSONResponse({"error": "unknown queue action"}, status_code=404)
    return _locker_call(calls[action])


@app.get(BASE + "/v1/queue/status")
def queue_status(request: Request, queue_id: str = Query(...), item_id: str | None = None, x_queue_key: str | None = Header(None)):
    request.state.extra["action"] = "queue_status"
    return _locker_call(workforce.status, queue_id, x_queue_key, item_id)


@app.get(BASE + "/v1/market/find")
def market_find(request: Request, q: str = Query(...), max_price_usd: float | None = None, network: str | None = None,
                exclude: str | None = None, limit: int = 10, live_check: int = 3, min_payers: int = 0):
    try:
        r = market.find(q, max_price_usd, network, [e for e in (exclude or "").split(",") if e], limit, live_check, min_payers)
    except Exception:
        request.state.extra.update({"action": "market_find", "error": 502})
        return JSONResponse({"error": "market index unavailable; not charged"}, status_code=502)
    request.state.extra.update({"action": "market_find", "results": len(r.get("results") or [])})
    return JSONResponse(r, status_code=422) if r.get("error") else r


@app.get(BASE + "/v1/market/reliability")
def market_reliability(request: Request, url: str = Query(...), method: str | None = None):
    try:
        r = market.reliability(url, method)
    except Exception:
        return JSONResponse({"error": "market index unavailable; not charged"}, status_code=502)
    request.state.extra.update({"action": "market_reliability", "score": r.get("score")})
    return r


@app.get(BASE + "/v1/vendor-check")
def vendor_check(request: Request, url: str = Query(...), method: str | None = None):
    try:
        r = market.vendor(url, method)
    except Exception:
        return JSONResponse({"error": "vendor check failed; not charged"}, status_code=502)
    request.state.extra.update({"action": "vendor_check", "verdict": r.get("verdict")})
    return r


@app.post(BASE + "/v1/contract/build")
def contract_build(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "contract_build"
    return _locker_call(contracts.build, body.get("terms"))


@app.post(BASE + "/v1/contract/accept")
def contract_accept(request: Request, body: dict = Body(...)):
    r = _locker_call(contracts.accept, body.get("token"), body.get("delivered"), not getattr(request.state, "ayne", False))
    request.state.extra.update({"action": "contract_accept", "verdict": r.get("verdict") if isinstance(r, dict) else None})
    return r


@app.get(BASE + "/v1/reputation")
def reputation_route(request: Request, agent: str = Query(...)):
    request.state.extra["action"] = "reputation"
    return _locker_call(contracts.reputation, agent)


@app.post(BASE + "/v1/evidence/bundle")
def evidence_bundle(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "evidence_bundle"
    return _locker_call(contracts.bundle, body.get("items"), body.get("label"))


@app.post(BASE + "/v1/finance/{action}")
def finance_post(action: str, request: Request, body: dict = Body(default={})):
    request.state.extra["action"] = "finance_" + action
    b = body
    calls = {"reconcile": lambda: finance.reconcile(b.get("invoice"), b.get("payments")),
             "forecast": lambda: finance.forecast(b.get("spend")),
             "watchdog": lambda: finance.watchdog(b.get("endpoints")),
             "snapshot": lambda: finance.snapshot(b.get("url"), b.get("method", "GET")),
             "refund-request": lambda: finance.refund_request(b.get("order"), b.get("failure"), b.get("receipt_ids"),
                                                              b.get("snapshot_token"), b.get("remedy", "refund"), b.get("amount_usd"))}
    if action not in calls:
        return JSONResponse({"error": "unknown finance action"}, status_code=404)
    return _locker_call(calls[action])


@app.get(BASE + "/v1/terms-extract")
def terms_extract(request: Request, url: str = Query(...)):
    r = hygiene.terms(url)
    request.state.extra.update({"action": "terms_extract", "te_status": r.get("status")})
    return r


@app.get(BASE + "/v1/freshness")
def freshness_route(request: Request, url: str = Query(...), kind: str = "generic"):
    request.state.extra["action"] = "freshness"
    return hygiene.freshness(url, kind)


@app.post(BASE + "/v1/dedupe")
def dedupe_route(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "dedupe"
    return _locker_call(hygiene.dedupe, body.get("namespace_key"), body.get("task"), body.get("result_pointer"), body.get("ttl_hours", 168))


@app.post(BASE + "/v1/context-diet")
def context_diet(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "context_diet"
    return _locker_call(hygiene.diet, body.get("packet"), body.get("required"), body.get("max_string_chars", 400), body.get("max_list_items", 50))


@app.get(BASE + "/v1/status")
def status_page():
    from concurrent.futures import ThreadPoolExecutor
    sample = [("GET", "local-facts?url=https://example.com"), ("GET", "alive?url=https://www.omenz.org"), ("POST", "secret-scan"),
              ("GET", "market/find?q=weather"), ("POST", "queue/create"), ("POST", "finance/forecast")]

    def probe(mp):
        m, pth = mp
        r = x402_probe.alive("https://www.omenz.org" + BASE + "/v1/" + pth, m)
        return {"route": m + " /v1/" + pth.split("?")[0], "verdict": r.get("verdict"), "latency_ms": r.get("latency_ms")}
    with ThreadPoolExecutor(6) as ex:
        checks = list(ex.map(probe, sample))
    up = all(c["verdict"] == "paywalled" for c in checks)
    return {"service": "OMENZ x402 tollbooth", "status": "operational" if up else "degraded",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_routes": len(ROUTES), "sample_checks": checks,
            "prices": BASE + "/v1/pricing-policy", "card": BASE + "/v1/card"}


@app.get(BASE + "/v1/starter-pack")
def starter_pack():
    return {"schema": "omenz.starter-pack.v0", "for": "a one-person or one-agent business running on paid machine services",
            "recipes": [
                {"name": "Before any paid call", "steps": ["market/find (pick a tool)", "market/reliability (trust it?)", "tx-preflight (GO/STOP)", "spend-gate (owner policy)"]},
                {"name": "Run a job safely", "steps": ["passport/issue (job-scoped permissions)", "preflight (READY?)", "cost-estimate", "ledger/create + ledger/append for every step"]},
                {"name": "Team of agents", "steps": ["queue/create (supervisor PO Box)", "queue/enqueue", "queue/claim + heartbeat checkpoints", "queue/escalate when stuck", "queue/status"]},
                {"name": "Hand work over", "steps": ["context-diet", "secret-scan", "handoff/pack", "pobox/drop"]},
                {"name": "When it fails", "steps": ["failure/put (+ dead-letter PO Box)", "finance/snapshot (what was promised)", "finance/refund-request", "evidence/bundle"]},
                {"name": "Hire another agent", "steps": ["contract/build (acceptance tests)", "contract/accept (neutral PASS/FAIL + escrow verdict)", "reputation"]},
                {"name": "Keep costs and facts honest", "steps": ["freshness (reuse or refetch?)", "dedupe (already done?)", "finance/watchdog (price drift, terms)", "claim-evidence + event-check (is it true?)"]}],
            "all_endpoints": BASE + "/v1/card", "pricing_policy": BASE + "/v1/pricing-policy", "tell_us_what_you_need": BASE + "/v1/needs"}


@app.get("/.well-known/mcp-registry-auth")
def mcp_registry_auth():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(discovery.MCP_REGISTRY_AUTH)


@app.get("/openapi.json")
@app.get(BASE + "/openapi.json")
def openapi_doc():
    return discovery.openapi(ROUTES, BASE)


@app.get("/.well-known/x402")
@app.get(BASE + "/well-known/x402")
def well_known_x402():
    return discovery.well_known_x402(ROUTES, BASE)


@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
@app.get(BASE + "/agent-card.json")
def agent_card():
    return discovery.agent_card(ROUTES, BASE)


_MCP_TOOLS = None


@app.get("/mcp")
def mcp_get():
    return JSONResponse({"error": "use POST (MCP streamable HTTP, JSON responses)", "server": "OMENZ", "tools": len(ROUTES)}, status_code=405)


@app.post("/mcp")
async def mcp_post(request: Request):
    import httpx
    from starlette.concurrency import run_in_threadpool
    global _MCP_TOOLS
    if _MCP_TOOLS is None:
        _MCP_TOOLS = discovery.mcp_tools(ROUTES)
    try:
        msg = json.loads(await request.body() or b"{}")
    except Exception:
        return JSONResponse(discovery.rpc_error(None, -32700, "parse error"), status_code=400)
    batch = msg if isinstance(msg, list) else [msg]
    ua = request.headers.get("user-agent", "")
    vis = ayne.visitor(request.headers.get("x-forwarded-for", "").split(",")[0].strip(), ua)
    out = []
    for m in batch:
        if not isinstance(m, dict):
            continue
        mid, meth, params = m.get("id"), m.get("method"), m.get("params") or {}
        if meth == "initialize":
            res = {"protocolVersion": params.get("protocolVersion") or discovery.MCP_PROTOCOL,
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "omenz-tollbooth", "title": "OMENZ agent tools", "version": "1.0.0"},
                   "instructions": "OMENZ tools for agents. Calls here run in AYNE, the free playzone (live sandbox or labeled samples, "
                                   "capped). For production, call the paid x402 URL named in each tool description."}
        elif meth in ("notifications/initialized", "notifications/cancelled"):
            continue
        elif meth == "ping":
            res = {}
        elif meth == "tools/list":
            res = {"tools": [{k: v for k, v in t.items() if not k.startswith("_")} for t in _MCP_TOOLS]}
        elif meth == "tools/call":
            t = next((x for x in _MCP_TOOLS if x["name"] == params.get("name")), None)
            if not t:
                out.append(discovery.rpc_error(mid, -32602, "unknown tool"))
                await run_in_threadpool(ayne.log, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "ayne", "via": "mcp",
                                                   "mode": "gap", "route": "/" + str(params.get("name"))[:80], "method": "MCP", "visitor": vis})
                continue
            args = dict(params.get("arguments") or {})
            headers = {"x-ayne-internal": ayne.internal_secret(), "x-ayne-visitor": vis, "user-agent": "mcp:" + ua[:150]}
            for a, h in discovery.HEADER_ARGS.items():
                if a in args:
                    headers[h] = str(args.pop(a))
            path = BASE + "/ayne/v1" + t["_path"].split("/v1", 1)[1]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://omenz.internal", timeout=28) as cl:
                if t["_method"] == "GET":
                    r = await cl.get(path, params={k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in args.items()}, headers=headers)
                else:
                    r = await cl.request(t["_method"], path, json=args, headers=headers)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:2000]}
            res = {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)[:60000]}],
                   "structuredContent": body if isinstance(body, dict) else {"result": body}, "isError": r.status_code >= 400}
        else:
            out.append(discovery.rpc_error(mid, -32601, "method not found"))
            continue
        if mid is not None:
            out.append({"jsonrpc": "2.0", "id": mid, "result": res})
    if not out:
        return JSONResponse(None, status_code=202)
    return JSONResponse(out if isinstance(msg, list) else out[0])


def _wallet_call(fn, *a):
    try:
        return fn(*a)
    except wallet.WalletError as e:
        code = 502 if "unavailable" in str(e) else 422
        return JSONResponse({"error": str(e) + ("; not charged" if code == 502 else "")}, status_code=code)


@app.get(BASE + "/v1/wallet/{action}")
def wallet_route(action: str, request: Request, address: str = Query(...), days: float = 7, low_days: float = 3, critical_days: float = 1):
    request.state.extra["action"] = "wallet_" + action
    if action == "balance":
        return _wallet_call(wallet.balance, address)
    if action == "spend":
        return _wallet_call(wallet.spend, address, days)
    if action == "runway":
        return _wallet_call(wallet.runway, address, days, low_days, critical_days)
    return JSONResponse({"error": "unknown wallet action"}, status_code=404)


@app.get(BASE + "/v1/market/payee")
def market_payee(request: Request, address: str = Query(...)):
    try:
        r = market.payee(address)
    except Exception:
        return JSONResponse({"error": "market index unavailable; not charged"}, status_code=502)
    request.state.extra.update({"action": "market_payee", "verdict": r.get("verdict")})
    return JSONResponse(r, status_code=422) if r.get("error") else r


@app.get(BASE + "/v1/market/price-index")
def market_price_index(request: Request, q: str | None = None, price_usd: float | None = None, url: str | None = None, min_payers: int = 0):
    try:
        r = market.price_index(q, price_usd, url, min_payers)
    except Exception:
        return JSONResponse({"error": "market index unavailable; not charged"}, status_code=502)
    request.state.extra.update({"action": "market_price_index", "n": r.get("comparables")})
    return JSONResponse(r, status_code=422) if r.get("error") and not r.get("comparables") else r


@app.post(BASE + "/v1/authorize")
def authorize_route(request: Request, body: dict = Body(...)):
    r = authorize.authorize(body)
    request.state.extra.update({"action": "authorize", "decision": r.get("decision")})
    if r.get("decision") == "ERROR":
        return JSONResponse(r, status_code=422)
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
def locker_put(request: Request, body: dict = Body(...)):
    ttl = 1 if getattr(request.state, "ayne", False) else body.get("ttl_days", 7)  # AYNE lockers last 1 day
    return _locker_call(locker.put, body.get("packet"), ttl, body.get("to"), body.get("from"))


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
