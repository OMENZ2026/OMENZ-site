"""OMENZ x402 tollbooth on omenz.org: deterministic checks agents pay for per call (HTTP 402, USDC on Base).

Source of truth: omenz-stack/products/x402_tollbooth/ (checker modules vendored in api/_tollbooth/).
Payout: the founder's Coinbase USDC-on-Base address. Facilitator: PayAI (keyless). Env vars can override both.

  GET /api/tollbooth                         free: service description + prices
  GET /api/tollbooth/v1/agent-ready?url=     $0.10
  GET /api/tollbooth/v1/site-check?url=      $0.01
  GET /api/tollbooth/v1/changed?url=         $0.005
  GET /api/tollbooth/v1/local-facts?url=     $0.01   Local Facts: phone/address/hours/holiday notices from the business's own site
  POST /api/tollbooth/v1/locker/put           $0.002  Agent Locker: check a job's resume packet in (encrypted, <=30 days)
  GET  /api/tollbooth/v1/locker/get?id=       $0.002  check it out (header X-Locker-Key; optional fields=a,b)
  DELETE /api/tollbooth/v1/locker/delete?id=  free    remove it (header X-Locker-Key)
  POST /api/tollbooth/v1/pobox/create         $0.002  Agent PO Box: get a box_id (share it) + owner_key (private)
  POST /api/tollbooth/v1/pobox/drop           $0.002  leave a sealed message for a box (any agent with the box_id)
  GET  /api/tollbooth/v1/pobox/inbox?box_id=  $0.002  owner opens waiting messages (header X-Owner-Key; ack=true clears)
  GET  /api/tollbooth/v1/alive?url=&method=  $0.002  Proof-of-Life: is this endpoint answering right now (up/paywalled/down...)
  GET  /api/tollbooth/v1/quote?url=&method=  $0.002  Price Quote: an x402 endpoint's live payment options, normalized to USD
  POST /api/tollbooth/v1/tx-preflight        $0.002  Transaction Preflight: GO/STOP before paying (budget, recipient, network, drift)
  POST /api/tollbooth/v1/secret-scan         $0.002  Secret-Leak Preflight: CLEAN/REVIEW/BLOCK before a payload leaves (nothing stored)
  POST /api/tollbooth/v1/spend-gate          $0.002  Spend Gate: ALLOW/DENY/ESCALATE a proposed spend against the owner's policy (caps, recipients, hurdle)
  GET  /api/tollbooth/v1/branch?url=&city=&zip=&street=  $0.01  Branch Resolver: the matching location page of a multi-location business + its facts
  POST /api/tollbooth/v1/failure/put         $0.002  Failure Receipt: standard why-it-failed record in a Locker for the next agent; optional PO Box dead-letter drop
  GET  /api/tollbooth/v1/terms-changed?url=&previous=  $0.005  Terms Changed?: only material pricing/limit/terms lines, diffed (stateless fingerprint)
  POST /api/tollbooth/v1/cost-estimate       $0.002  Cost-to-Complete: job cost before it starts (model + paid tools, live x402 quotes), budget/value check, cheaper routing
  POST /api/tollbooth/v1/passport/issue      $0.002  Permission Passport: signed, expiring, job-scoped permissions (tools, hosts, spend)
  POST /api/tollbooth/v1/passport/check      $0.002  ALLOW/DENY an action against a passport
  GET  /api/tollbooth/v1/passport/key        free    public key to verify passports offline
  POST /api/tollbooth/v1/needs               free    Agent Needs desk: tell OMENZ what you need, what it's worth, how often
  GET  /api/tollbooth/v1/pricing-policy      free    machine-readable fair-pricing promise
  GET  /api/tollbooth/v1/event-check?company=&claim=&days=  $0.005  Event Check: did the company actually FILE it (SEC 8-K), with the quote
  POST /api/tollbooth/v1/claim-evidence      $0.005  Claim -> Evidence: does this source say what you claim? quote, or what's missing
  POST /api/tollbooth/v1/preflight           $0.005  Agent Preflight: READY/BLOCKED before a job (tools live + priced, budget, passport)
  POST /api/tollbooth/v1/ledger/create       $0.002  Job Ledger: hash-chained, append-only record of a job (key shown once)
  POST /api/tollbooth/v1/ledger/append       $0.002  add an entry (tool_call/spend/receipt/handoff/failure/output/status/note/decision)
  GET  /api/tollbooth/v1/ledger/get?id=      $0.002  entries + totals + chain_intact
  GET  /api/tollbooth/v1/capability-card?url= $0.002 Capability Card for any x402 service (index or endpoint)
  GET  /api/tollbooth/v1/card                free    OMENZ's own capability card
  POST /api/tollbooth/v1/queue/{create,enqueue,claim,heartbeat,complete,fail,escalate,resolve,bid,award}, GET queue/status
                                             Agent Workforce: work queue with leases, checkpoints/recovery, escalation, bidding, roster, scheduling
  GET  /api/tollbooth/v1/market/find?q=      $0.002  Capability Finder / Procurement / Quote Comparator / Substitute / Rate-Limit Router over ~35k x402 endpoints
  GET  /api/tollbooth/v1/market/reliability?url= $0.002 Micropayment Reliability Score 0-100 with reasons
  GET  /api/tollbooth/v1/vendor-check?url=   $0.01   Vendor Due-Diligence Pack
  POST /api/tollbooth/v1/contract/build      $0.002  A2A Contract Builder (signed terms + deterministic acceptance tests)
  POST /api/tollbooth/v1/contract/accept     $0.005  Acceptance Test as a Service -> PASS/FAIL, escrow verdict, signed attestation (reputation)
  POST /api/tollbooth/v1/checkpoint/create | checkpoint/submit, GET checkpoint/status  $0.005 / $0.01 / $0.002  Checkpoint: milestone tranches with per-milestone RELEASE/REFUND/RETRY verdicts
  GET  /api/tollbooth/v1/reputation?agent=   $0.002  Reputation Receipts: an agent's OMENZ-checked job history
  POST /api/tollbooth/v1/evidence/bundle     $0.002  Machine Evidence Bundle (signed, hash-listed)
  POST /api/tollbooth/v1/finance/{reconcile,forecast,watchdog,snapshot,refund-request}  Agent finance back office
  GET  /api/tollbooth/v1/terms-extract?url=  $0.005  API Terms / Data-License Checker
  GET  /api/tollbooth/v1/freshness?url=&kind= $0.002 Source Freshness / Result TTL
  POST /api/tollbooth/v1/dedupe              $0.002  Duplicate-Work Detector (private namespace)
  POST /api/tollbooth/v1/context-diet        $0.002  Context Diet
  GET  /api/tollbooth/v1/status              free    Machine Commerce Status Page (OMENZ)
  GET  /api/tollbooth/v1/starter-pack        free    Agent Business Starter Pack
  GET  /api/tollbooth/swapmeet/v1[/search|/new|/hot], POST /booth   free    OMENZ AI Agent Swap Meet (aisles, search, bring a booth)
  POST /api/tollbooth/v1/jacket/create|checkout|checkin  $0.002, GET jacket/history $0.002  Job Jacket: check a job's minimum working state out/in
  POST /api/tollbooth/v1/send/check $0.005   Send Check: SEND / CAUTION / STOP before an agent sends USDC/ETH (OFAC, poisoning, contract, balance)
  POST /api/tollbooth/v1/wallet-watch $0.01, GET wallet-watch/report $0.002   Wallet Watch: low-balance / low-runway alert to your PO Box
  POST /api/tollbooth/v1/uptime/watch $0.01, GET uptime/report $0.002   Uptime Watch: 30-day monitoring of a paid endpoint (status, latency, price, payTo)
  GET  /api/tollbooth/v1/track-record       free    test evidence per tool (frozen holdouts, release tests), promises, maturity
  GET/POST /api/tollbooth/myop/v1/...       free    MYOP: play with your agent (operator+agent games; page omenz.org/myop/)
  ANY  /api/tollbooth/ayne/v1/<route>       free    AYNE: the agent Playzone (2000 req/day, 300/visitor): live sandbox or labeled samples of every route
  GET  /openapi.json  /.well-known/x402  /.well-known/agent-card.json   free  machine discovery (OpenAPI+x402, x402 list, A2A card)
  POST /mcp                                  free    remote MCP server (tools/list = all tools; tools/call runs in AYNE)
  GET  /api/tollbooth/v1/wallet/{balance,spend,runway}?address=   agent-wallet tools (USDC on Base, public chain data)
  GET  /api/tollbooth/v1/market/payee?address=  /market/price-index?q=&price_usd=   payee check + x402 price index
  GET|POST /api/tollbooth/v1/authorize       $0.002  OMENZ Authorize: APPROVE/REVIEW/DECLINE + signed authorization before any x402 payment
  POST /api/tollbooth/v1/split-check         $0.002  Split Check: verify an on-chain revenue split (0xSplits v2) and who gets what
  POST /api/tollbooth/v1/credits/buy-1 | buy-5   $1 / $5  prepaid credits (one settlement; checks draw from the balance)
  GET  /api/tollbooth/v1/credits/balance     free    balance + recent charges (X-Credit-Id / X-Credit-Key)
  POST /api/tollbooth/v1/authorize/credit    credits OMENZ Authorize paid from credits: 2% of the payment, min $0.0003
  GET  /api/tollbooth/v1/market/report      $1.00   weekly x402 Market Report (supply side: endpoints, sellers, prices, concentration, top sellers)
  POST /api/tollbooth/v1/budget/{create,spend,release} $0.002/$0.002, GET budget/status $0.002, POST budget/freeze free
                                             Shared Budget: one spending cap a team of agents draws from (bookkeeping only)
  POST /api/tollbooth/v1/pay/verify         $0.002  Payment Verify: did this x402 payment settle on Base (payer, payee, USDC, confirmations)
  POST /api/tollbooth/v1/delivery-check     $0.002  Delivery Check: did the paid response match the seller's advertised output
  GET  /api/tollbooth/v1/market/cheapest?q= $0.002  Cheapest Working Tool: cheapest provider that answers right now (live-probed)
  POST /api/tollbooth/v1/spend-receipt      $0.003  Spend Receipt: signed what/why/cost(verified)/delivered receipt for one purchase
  POST /api/tollbooth/v1/checkout/open|close $0.002 each (or /credit: 1% of the purchase, min $0.0002)  OMENZ Checkout: the buyer layer around every payment
  GET  /api/tollbooth/v1/seller-record?host= $0.002  Seller Track Record from verified checkouts
  GET  /api/tollbooth/v1/facilitators       $0.002  Facilitator Status + Router: live x402 facilitators, fastest for your network/scheme
  POST /api/tollbooth/v1/sale/record        $0.002  Sale Record (sellers): verified, counted-once sale + signed sale receipt -> Seller Track Record
  GET  /api/tollbooth/v1/tx/decode?tx_hash= $0.002  Transaction Decode (Base): plain-English transfers, approvals, x402 payments
  GET  /api/tollbooth/v1/name/resolve?q=     $0.002  Name Resolve: ENS + Basenames <-> address (forward-verified)
  POST /api/tollbooth/v1/seller/acceptance-check $0.05  Seller Payment-Acceptance Check: does your x402 server refuse good money?
  GET  /api/tollbooth/v1/weather?lat=&lon=&days=    $0.002  Weather: now, 6h/24h, 5-day, agent flags
  GET  /api/tollbooth/v1/ip/check?ip=               $0.002  IP Check: owner, country, cloud, Tor
  GET  /api/tollbooth/v1/fx/convert?amount=&from=&to=&date=  $0.002  FX Rates: ECB reference rates, ~30 currencies
  POST /api/tollbooth/v1/lead/check {email,phone,website}  $0.005  Lead Check: email+phone+domain bundle
  GET  /api/tollbooth/v1/link/check?url=            $0.003  Link Check: unshorten, TLS, domain age
  GET  /api/tollbooth/v1/email/check?email=         $0.002  Email Check: deliverable? disposable, role, spoofable
  GET  /api/tollbooth/v1/phone/check?number=&country=  $0.002  Phone Check: valid? type, formats, warnings (offline)
  GET  /api/tollbooth/v1/domain/check?domain=       $0.003  Domain Check: age, DNS, MX/SPF/DMARC trust
  GET  /api/tollbooth/v1/package/check?ecosystem=&name=&version=  $0.003  Package Check: safe to install? (deps.dev + OSV)
  GET  /api/tollbooth/v1/token/check?token=        $0.005  Token Check (Base): safe to hold/accept? proxy, owner powers, OFAC
  GET  /api/tollbooth/v1/token/balance?address=&token=  $0.002  Token Balance (Base): any ERC-20 or native ETH
  GET  /api/tollbooth/v1/allowance?owner=&token=&spender=  $0.002  Allowance Check: can this spender move my tokens? UNLIMITED flagged + revoke call
  GET  /api/tollbooth/v1/settlement-cost    $0.002  Settlement Cost Check: live Base gas/USD cost of a settlement + settle/batch verdict
  POST /api/tollbooth/v1/guard              $0.05   Transaction Guard: GO/CAUTION/STOP before money moves (budget, counterparty, duplicate, price, economics, delivery)
  POST /api/tollbooth/v1/guard/credit       credits max($0.01, 10 bps of protected value), cap $5
  POST /api/tollbooth/v1/budget/delegate    $0.01   Delegation Budget: child agent allowances that inherit and narrow the parent (4 levels)
  POST /api/tollbooth/v1/settlement/rescue  $0.05   Settlement Rescue: SETTLED / NOT_SETTLED / STILL_UNCERTAIN + safe next action (EIP-3009 state)
  POST /api/tollbooth/v1/market/job         $0.01   OMENZ Market job desk: working providers for a job + verified history + Guard request (/guarded $0.05)
  POST /api/tollbooth/v1/dispute/packet     $0.10   Dispute Packet: settlement proof + promise + delivery check + timeline + signed refund request
  POST /api/tollbooth/v1/po/issue|redeem    $0.01 / $0.002  Agent Purchase Order: signed single-use 'may spend $X with Y for Z', budget-backed
  GET  /api/tollbooth/v1/loadouts           free    OMENZ Loadouts catalog: Agent Skins + robot loadouts (HOST MODE...), platform profiles, capability words
  POST /api/tollbooth/v1/loadout/check|compile|simulate  $0.01 / $0.02 / $0.005  loadout x platform compatibility, platform plan + signed install receipt, sim run
  POST /api/tollbooth/v1/robot/action-gate   $0.002  ALLOW / CONFIRM_FIRST / DENY before one physical robot action, signed receipt
  GET  /.well-known/mcp.json                 free    MCP discovery card
  GET  /api/tollbooth/v1/market/sellers?q=   $0.25   x402 seller lead list by capability (usage, prices, example endpoint)
Every request is instrumented (key="tollbooth" events; no keys, contents or IPs logged; search routes keep only common capability words, see pricing-policy). Spec: omenz-stack/products/agent_pobox/SPEC.md
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
import credits  # noqa: E402
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
import myop  # noqa: E402
import track_record  # noqa: E402
import swapmeet  # noqa: E402
import jacket  # noqa: E402
import uptime  # noqa: E402
import wallet_watch  # noqa: E402
import passport  # noqa: E402
import preflight  # noqa: E402
import pobox  # noqa: E402
import receipts  # noqa: E402
import branch_resolver  # noqa: E402
import buyer  # noqa: E402
import checkout  # noqa: E402
import facilitators  # noqa: E402
import chain_tools  # noqa: E402
import token_check  # noqa: E402
import package_check  # noqa: E402
import domain_check  # noqa: E402
import phone_check  # noqa: E402
import email_check  # noqa: E402
import link_check  # noqa: E402
import name_check  # noqa: E402
import lead_check  # noqa: E402
import fx_rates  # noqa: E402
import ip_check  # noqa: E402
import weather  # noqa: E402
import gas  # noqa: E402
import guard  # noqa: E402
import rescue  # noqa: E402
import dispute  # noqa: E402
import po  # noqa: E402
import loadout  # noqa: E402
import secret_scan  # noqa: E402
import spend_gate  # noqa: E402
import splits  # noqa: E402
import terms_changed  # noqa: E402
import wallet  # noqa: E402
import workforce  # noqa: E402
import x402_probe  # noqa: E402
import site_check  # noqa: E402

from x402 import x402ResourceServer  # noqa: E402
from x402.extensions.bazaar import bazaar_resource_server_extension, declare_discovery_extension  # noqa: E402
import cdp_auth  # noqa: E402
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
            input={"url": "https://www.omenz.org"},
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
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
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
        input={"payer": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "payee": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "amount": "0.001", "currency": "USDC", "network": "base", "tx_hash": "0x...", "service": "summarize", "job_id": "42"},
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
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
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
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
        "description": PROBE_DESC[_n], "mimeType": "application/json",
        "extensions": declare_discovery_extension(
            input={"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET"},
            input_schema={"properties": {"url": {"type": "string", "description": "Endpoint URL to probe"},
                                         "method": {"type": "string", "description": "HTTP method the endpoint expects (default GET)"}},
                          "required": ["url"]}),
    }
ROUTES[f"POST {BASE}/v1/tx-preflight"] = {
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Transaction Preflight: GO or STOP before your agent pays an x402 endpoint. Checks it answers, the live price is within max_price_usd, payTo matches expected_pay_to, the network is allowed, the asset is a known USD stablecoin, and flags drift from the price you were quoted/listed. Never pays the target. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET", "max_price_usd": 0.01,
               "expected_pay_to": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "networks": ["base"], "listed_price_usd": 0.005},
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
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
    "description": "Spend Gate: ALLOW, DENY or ESCALATE before your agent spends money. Send the owner's policy (per-transaction, daily and monthly caps, approval threshold, recipient/category/network allow and block lists, hurdle: minimum expected return multiple) and the proposed spend; get the decision with every reason and the budget left. Stateless: nothing stored. By OMENZ.",
    "mimeType": "application/json",
    "extensions": declare_discovery_extension(
        input={"policy": {"max_per_tx_usd": 1, "daily_cap_usd": 5, "escalate_above_usd": 0.5, "allowed_networks": ["base"],
                          "hurdle": {"min_return_multiple": 1.5}},
               "spend": {"amount_usd": 0.1, "recipient": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "network": "base", "category": "data", "expected_value_usd": 0.5,
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
        input={"url": "https://www.omenz.org/logo/", "previous": "tc1.…"},
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
                       "tools": [{"name": "facts", "x402_url": "https://www.omenz.org/api/tollbooth/v1/local-facts?url=https://www.omenz.org", "calls": 10}],
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
    "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": "$0.002", "network": NETWORK},
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
      {"job": {"tools": [{"name": "facts", "url": "https://www.omenz.org/api/tollbooth/v1/local-facts?url=https://www.omenz.org", "calls": 10, "max_price_usd": 0.02}],
               "budget_usd": 1, }},
      {"properties": {"job": {"type": "object"}}, "required": ["job"]}, body=True)
_paid("POST", "ledger/create", "$0.002",
      "Agent Job Ledger: open an append-only, hash-chained record for one job (tool calls, spend, receipts, handoffs, failures, outputs, status). Returns ledger_id + ledger_key (shown once). Kept 90 days. By OMENZ.",
      {"job_id": "job-42", "objective": "get today's hours for 20 restaurants"},
      {"properties": {"job_id": {"type": "string"}, "objective": {"type": "string"}}}, body=True)
_paid("POST", "ledger/append", "$0.002",
      "Agent Job Ledger: append one entry (type tool_call|spend|receipt|handoff|failure|output|status|note|decision, any fields, amount_usd optional). Each entry is chained to the previous by sha256; secrets are refused. Header X-Ledger-Key. By OMENZ.",
      {"ledger_id": "lg_...", "entry": {"type": "tool_call", "tool": "local-facts", "amount_usd": 0.01, "result": "ok"}},
      {"properties": {"ledger_id": {"type": "string"}, "entry": {"type": "object"}}, "required": ["ledger_id", "entry"]}, body=True)
_paid("GET", "ledger/get", "$0.002",
      "Agent Job Ledger: read entries (since_seq for only new ones), totals (spent, counts by type, last status) and chain_intact: proof nothing was edited or removed. Header X-Ledger-Key. By OMENZ.",
      {"id": "lg_...", "since_seq": 0}, {"properties": {"id": {"type": "string"}, "since_seq": {"type": "integer"}}, "required": ["id"]})
_paid("GET", "capability-card", "$0.002",
      "Agent Capability Card: a standard machine-readable card (omenz.capability-card.v0) of what any x402 service offers: endpoints, live prices and payment options, input/output examples from its discovery data, latency. Works on a service index or a single endpoint; never pays. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}}, "required": ["url"]})

WQ = {
    "create": ("$0.002", "Agent Workforce: create a work queue for a team of agents. Returns queue_id + owner_key + worker_key (shown once). Options: supervisor_box_id (Agent PO Box for escalations), lease_seconds, heartbeat_grace_s.",
               {"name": "restaurant-hours crew", "supervisor_box_id": "pb_...", "lease_seconds": 900}),
    "enqueue": ("$0.002", "Agent Workforce: add a job (title, payload, priority, not_before, repeat_every_minutes, max_attempts, bidding, jacket_id + jacket_fields to attach a Job Jacket). Owner key. Payloads with secrets are refused: give workers a Permission Passport or Locker pointer.",
                {"queue_id": "wq_...", "title": "get hours for 20 restaurants", "payload": {"city": "Pasadena"}, "priority": 5}),
    "claim": ("$0.002", "Agent Workforce: a worker claims the highest-priority ready job and gets a LEASE (it is now responsible). Send jacket_key too and the attached Job Jacket is checked out in the same call (one call to start a shift). Expired leases come back with the last checkpoint so a replacement can resume.",
              {"queue_id": "wq_...", "worker_id": "agent-7"}),
    "heartbeat": ("$0.002", "Agent Workforce: worker is alive; extends its lease and stores a checkpoint (e.g. a Locker id + step) for dead-agent recovery.",
                  {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "checkpoint": {"locker_id": "lk_...", "step": 3}}),
    "complete": ("$0.002", "Agent Workforce: worker finishes its leased job with a result; repeating jobs are rescheduled automatically.",
                 {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "result": {"ok": True}}),
    "fail": ("$0.002", "Agent Workforce: worker reports failure; the job retries until max_attempts, then goes dead.",
             {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "reason": "site blocked", "retry": True}),
    "escalate": ("$0.002", "Agent Workforce: hand a job up to the supervisor (sealed drop into the supervisor's Agent PO Box).",
                 {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "reason": "customer asked for a refund"}),
    "resolve": ("$0.002", "Agent Workforce: owner resolves an escalated/dead job: requeue, close or kill.",
                {"queue_id": "wq_...", "item_id": "wi_...", "action": "requeue"}),
    "bid": ("$0.002", "Agent Workforce: worker bids on a job open for bidding (price_usd, eta_minutes).",
            {"queue_id": "wq_...", "worker_id": "agent-7", "item_id": "wi_...", "price_usd": 0.02, "eta_minutes": 10}),
    "award": ("$0.002", "Agent Workforce: owner awards a bidding job to one bidder; the award becomes that worker's lease.",
              {"queue_id": "wq_...", "item_id": "wi_...", "worker_id": "agent-7"}),
}
for _a, (_p, _d, _i) in WQ.items():
    _paid("POST", "queue/" + _a, _p, _d + " Header X-Queue-Key. By OMENZ.", _i, {"properties": {k: {} for k in _i}}, body=True)
_paid("GET", "queue/status", "$0.002",
      "Agent Workforce: who is responsible for what right now (holders + lease time left), counts by state, escalations, roster (available/last seen/current job), scheduled jobs; or one item's full history with item_id. Header X-Queue-Key. By OMENZ.",
      {"queue_id": "wq_...", "item_id": "(optional)"}, {"properties": {"queue_id": {"type": "string"}, "item_id": {"type": "string"}}, "required": ["queue_id"]})

_paid("GET", "market/find", "$0.002",
      "Which paid API should my agent use? Agent Market finds the paid tool for a capability across ~38,000 x402 endpoints (Bazaar index, refreshed daily). Ranked by match, then real 30-day usage (calls, unique payers); filter by max_price_usd and network; exclude= a vendor to get substitutes (tool down or rate-limited); the top picks are probed live (never paid) for status, price and drift. Capability Finder, Procurement Desk, Quote Comparator, Tool Substitute Finder and Rate-Limit Router in one call. By OMENZ.",
      {"q": "weather forecast by city", "max_price_usd": 0.01, "network": "base", "limit": 10, "live_check": 3},
      {"properties": {"q": {"type": "string"}, "need": {"type": "string"}, "max_price_usd": {"type": "number"}, "network": {"type": "string"}, "exclude": {"type": "string"},
                      "limit": {"type": "integer"}, "live_check": {"type": "integer"}, "min_payers": {"type": "integer"}}, "required": ["q"]})
_paid("GET", "market/reliability", "$0.002",
      "Micropayment Reliability Score: should your agent trust this paid endpoint? 0-100 + grade with every reason: public 30-day usage, answering now with valid x402 requirements, speed, live price vs listed price, payTo vs listed payTo (catches swapped wallets), and payer independence from public Base data (how many recent payers look independent vs also receiving USDC from the payee). Never pays. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}}, "required": ["url"]})
_paid("GET", "vendor-check", "$0.01",
      "Vendor Due-Diligence Pack: before your agent depends on an unknown paid API: reliability score + the vendor domain's health (live/parked/moved) + its terms/pricing page digest (material lines) + flags. Never pays. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive"}, {"properties": {"url": {"type": "string"}, "method": {"type": "string"}}, "required": ["url"]})

_paid("POST", "checkpoint/create", "$0.005",
      "OMENZ Checkpoint (create): split an agent job into paid milestones. Each milestone has an amount, its own deterministic acceptance tests (required_fields, field_types, regex, min_items, max_bytes, equals, url_alive, claim_evidence) and an optional deadline. Returns a signed plan and checkpoint_id. OMENZ never holds funds. By OMENZ.",
      {"buyer": "agent-b", "seller": "agent-s", "job": "research report", "total_usd": 3, "milestones": [{"name": "outline", "amount_usd": 1, "acceptance": [{"type": "required_fields", "fields": ["outline"]}]}, {"name": "report", "amount_usd": 2, "acceptance": [{"type": "min_items", "field": "sections", "n": 3}], "deadline_hours": 48}]},
      {"properties": {"buyer": {"type": "string"}, "seller": {"type": "string"}, "job": {"type": "string"}, "total_usd": {"type": "number"}, "milestones": {"type": "array"}}, "required": ["milestones"]}, body=True)
_paid("POST", "checkpoint/submit", "$0.01",
      "OMENZ Checkpoint (submit): deliver one milestone. Its acceptance tests run; you get PASS/FAIL and the escrow verdict for THAT tranche: RELEASE (buyer pays it now), RETRY (seller fixes, max 3 attempts) or REFUND (failed or late, not owed), a signed receipt, and running totals (released / refunded / pending). A decided milestone can't be passed or counted twice. Seller track record updated. By OMENZ.",
      {"checkpoint_id": "ck_...", "milestone": "outline", "delivered": {"outline": "1. intro 2. method 3. results"}},
      {"properties": {"checkpoint_id": {"type": "string"}, "milestone": {"type": "string"}, "delivered": {"type": "object"}}, "required": ["checkpoint_id", "milestone", "delivered"]}, body=True)
_paid("GET", "checkpoint/status", "$0.002",
      "OMENZ Checkpoint (status): where a milestone job stands: each milestone RELEASE / REFUND / RETRY / PENDING with attempts, and released / refunded / pending USD. By OMENZ.",
      {"id": "ck_..."}, {"properties": {"id": {"type": "string"}}, "required": ["id"]})
_paid("POST", "contract/build", "$0.002",
      "A2A Contract Builder: turn a machine job into signed terms both agents hold: deliverable, deterministic acceptance tests (required_fields, field_types, regex, min_items, max_bytes, equals, url_alive, claim_evidence), max spend, deadline, parties. Ed25519-signed by OMENZ; verify offline with /v1/passport/key. By OMENZ.",
      {"terms": {"buyer": "agent-a", "seller": "agent-b", "deliverable": "hours for 3 restaurants", "max_spend_usd": 0.1, "deadline": 1900000000,
                 "acceptance": [{"type": "min_items", "field": "results", "n": 3}, {"type": "regex", "field": "source", "pattern": "https://.+"}]}},
      {"properties": {"terms": {"type": "object"}}, "required": ["terms"]}, body=True)
_paid("POST", "contract/accept", "$0.005",
      "Acceptance Test as a Service + escrow verdict: a neutral party runs the contract's tests on what was delivered. PASS/FAIL per test, escrow_verdict RELEASE/REFUND (OMENZ never holds funds: the payer acts on it), and a signed attestation that feeds the seller's Reputation Receipts. By OMENZ.",
      {"token": "<contract token>", "delivered": {"results": [1, 2, 3], "source": "https://www.omenz.org"}},
      {"properties": {"token": {"type": "string"}, "delivered": {}}, "required": ["token", "delivered"]}, body=True)
_paid("GET", "reputation", "$0.002",
      "Reputation Receipts: an agent's job history as checked by OMENZ Acceptance Test: jobs, passed, failed, late, pass rate, distinct buyers (low = weak evidence), recent attestations. Not self-reported. By OMENZ.",
      {"agent": "agent-b"}, {"properties": {"agent": {"type": "string"}}, "required": ["agent"]})
_paid("POST", "evidence/bundle", "$0.002",
      "Machine Evidence Bundle: package receipts, ledger heads, attestation tokens, claims and sources into one signed, hash-listed bundle (merkle-style root) that any agent can verify offline. For disputes, audits, refunds and handoffs. By OMENZ.",
      {"items": [{"kind": "receipt", "id": "rc_..."}, {"kind": "attestation", "token": "..."}], "label": "job 42"},
      {"properties": {"items": {"type": "array"}, "label": {"type": "string"}}, "required": ["items"]}, body=True)

FIN = {
    "reconcile": ("$0.005", "Invoice/Payment Reconciler: invoice lines vs USDC-on-Base payments, each transaction checked on-chain (payer, payee, amount): MATCH / UNDERPAID / OVERPAID / MISSING / UNVERIFIED, duplicates and line-total errors flagged.",
                  {"invoice": {"payee": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "lines": [{"desc": "lookups", "amount_usd": 0.5}], "total_usd": 0.5}, "payments": [{"tx_hash": "0x...", "payer": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "amount_usd": 0.5}]}),
    "forecast": ("$0.002", "Agent Budget Forecaster: spend history -> daily rate, next 7/30-day projection, trend, biggest dependencies.",
                 {"spend": [{"at": 1763000000, "amount_usd": 0.01, "tool": "search"}]}),
    "watchdog": ("$0.005", "Subscription Watchdog: the paid endpoints your agent business relies on (up to 8): live price vs expected, down/up, terms/pricing page changed (pass back fingerprints).",
                 {"endpoints": [{"url": "https://www.omenz.org/api/tollbooth/v1/alive", "expected_price_usd": 0.005, "terms_url": "https://www.omenz.org/llms.txt"}]}),
    "snapshot": ("$0.002", "Machine Warranty / Purchase Snapshot: signed record of exactly what a paid endpoint promised (live x402 requirements, description, examples) at purchase time.",
                 {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET"}),
    "refund-request": ("$0.002", "Structured Refund Request: order + failure receipt + payment receipts + purchase snapshot -> a standard signed dispute object with evidence strength and gaps. OMENZ packages evidence; it doesn't rule or move money.",
                       {"order": {"seller": "svc", "description": "lookup", "amount_usd": 0.01}, "failure": {"error_class": "payment_taken_no_result"}, "receipt_ids": ["rc_..."], "snapshot_token": "...", "remedy": "refund"}),
}
for _a, (_p, _d, _i) in FIN.items():
    _paid("POST", "finance/" + _a, _p, _d + " Deterministic; never pays a target. By OMENZ.", _i, {"properties": {k: {} for k in _i}}, body=True)

_paid("GET", "terms-extract", "$0.005",
      "API Terms Extractor / Data-License Checker: before your agent uses a dataset or API commercially: a terms/license page -> clauses by category (commercial use, attribution, rate limits, retention, training on your data, prohibited uses, resale, refunds, liability, termination, license type) with quotes, plus plain flags (no_commercial_use, attribution_required, may_train_on_your_data, no_resale, no_scraping, non_refundable). Pattern-based, not legal advice. By OMENZ.",
      {"url": "https://www.anthropic.com/legal/consumer-terms"}, {"properties": {"url": {"type": "string"}}, "required": ["url"]})
_paid("GET", "freshness", "$0.002",
      "Source Freshness / Result TTL: how long can your agent reuse a result before paying to fetch it again? The source's own Last-Modified, ETag and Cache-Control + a reuse window by data kind (price, quote, hours, weather, news, stock, crypto, business_facts, terms, docs, filing, profile, search) + how to revalidate cheaply (304). By OMENZ.",
      {"url": "https://www.omenz.org/logo/", "kind": "price"}, {"properties": {"url": {"type": "string"}, "kind": {"type": "string"}}, "required": ["url"]})
_paid("POST", "dedupe", "$0.002",
      "Duplicate-Work Detector: before your agent pays to run a task, check whether someone in your team (same private namespace_key) already did it: normalized fingerprint -> HIT with the earlier result pointer, or MISS (pass result_pointer to register this run). By OMENZ.",
      {"namespace_key": "your-private-team-key-16+", "task": {"q": "hours for Flemings Pasadena", "day": "2026-11-14"}, "result_pointer": "lk_...", "ttl_hours": 24},
      {"properties": {"namespace_key": {"type": "string"}, "task": {}, "result_pointer": {"type": "string"}, "ttl_hours": {"type": "integer"}},
       "required": ["namespace_key", "task"]}, body=True)
_paid("POST", "context-diet", "$0.002",
      "Context Diet: shrink a packet before it fills your context: drops empty fields, dedupes lists, cuts long strings to a head + sha256 pointer, caps list length, always keeps required fields; reports bytes and approximate tokens saved. By OMENZ.",
      {"packet": {"objective": "ship v2", "notes": "Long meeting notes: we agreed to ship v2 Friday, Ana owns the tests, budget is $40, skip the redesign for now."}, "required": ["objective"], "max_string_chars": 400},
      {"properties": {"packet": {}, "required": {"type": "array"}, "max_string_chars": {"type": "integer"}, "max_list_items": {"type": "integer"}},
       "required": ["packet"]}, body=True)

_paid("GET", "wallet/balance", "$0.002",
      "Agent Wallet Balance: USDC and ETH balance of any wallet on Base (public chain data). Never moves funds, no key needed. By OMENZ.",
      {"address": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840"}, {"properties": {"address": {"type": "string"}}, "required": ["address"]})
_paid("GET", "wallet/spend", "$0.005",
      "Agent Wallet Spend Report: what has this wallet been paying for? Outgoing USDC payments on Base over the last N days (max 14), grouped by payee, each payee named with the x402 services that pay out to it (from the ~35k-endpoint x402 index), totals, daily rate, micropayment count, share going to known x402 sellers. Public chain data. By OMENZ.",
      {"address": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "days": 7}, {"properties": {"address": {"type": "string"}, "days": {"type": "number"}}, "required": ["address"]})
_paid("GET", "wallet/runway", "$0.005",
      "Agent Wallet Runway: how many days before this agent wallet runs dry? USDC balance / recent daily spend -> days left, OK / LOW / CRITICAL, and the top cost drivers by payee. Public chain data on Base. By OMENZ.",
      {"address": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "days": 7, "low_days": 3}, {"properties": {"address": {"type": "string"}, "days": {"type": "number"},
                                                         "low_days": {"type": "number"}, "critical_days": {"type": "number"}}, "required": ["address"]})
_paid("GET", "market/payee", "$0.002",
      "Payee Check: before paying an address, is it a known x402 seller? Screens it against OFAC's sanctioned crypto addresses and matches it against the payout addresses of ~35k listed x402 endpoints: KNOWN_SELLER (which services, 30-day calls and payers), SHARED_ADDRESS (platform/facilitator wallet) or UNKNOWN. By OMENZ.",
      {"address": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840"}, {"properties": {"address": {"type": "string"}}, "required": ["address"]})
_paid("GET", "market/price-index", "$0.002",
      "x402 Price Index / Fair Price Check: the going rate for a capability across listed x402 endpoints: comparables, sellers, min / p25 / median / p75 / max and usage-weighted median; pass price_usd (or a listed url) to get its percentile and FAIR / LOW / ABOVE_MARKET / HIGH. By OMENZ.",
      {"q": "web search", "price_usd": 0.005}, {"properties": {"q": {"type": "string"}, "price_usd": {"type": "number"}, "url": {"type": "string"},
                                                  "min_payers": {"type": "integer"}}, "required": ["q"]})

_paid("POST", "authorize", "$0.002",
      "OMENZ Authorize: the authorization step for agent payments. One call before paying any x402 endpoint: live quote + preflight (up, price within max, network, stablecoin, expected payTo), payee check (known x402 seller?) + OFAC sanctions screen (a sanctioned payTo = DECLINE) + seller domain age (registered < 30 days = REVIEW), fair-price check vs comparable endpoints, the owner's spend policy and Permission Passport if sent -> APPROVE / REVIEW / DECLINE with reasons and a signed 5-minute authorization code anyone can verify. Never pays the target. Doing many? Prepay once (POST /v1/credits/buy-1, $1) and check via /v1/authorize/credit at 2% of the payment (min $0.0003), with no per-check settlement. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "POST", "max_price_usd": 0.05, "expected_pay_to": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840",
       "policy": {"daily_cap_usd": 5}, "spend": {"spent_today_usd": 1.2}, "passport_token": "(optional)"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "max_price_usd": {"type": "number"}, "expected_pay_to": {"type": "string"},
                      "policy": {"type": "object"}, "spend": {"type": "object"}, "passport_token": {"type": "string"}}, "required": ["url"]}, body=True)

_paid("GET", "authorize", "$0.002",
      "OMENZ Authorize (GET form): same APPROVE / REVIEW / DECLINE check before paying an x402 endpoint, with query params: url, method, max_price_usd, expected_pay_to, daily_cap_usd, spent_today_usd. Returns reasons + a signed 5-minute authorization code. Never pays the target. Doing many? Prepay once (POST /v1/credits/buy-1, $1) and check via /v1/authorize/credit at 2% of the payment (min $0.0003), with no per-check settlement. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET", "max_price_usd": 0.05},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "max_price_usd": {"type": "number"}, "expected_pay_to": {"type": "string"},
                      "daily_cap_usd": {"type": "number"}, "spent_today_usd": {"type": "number"}}, "required": ["url"]})

_paid("POST", "split-check", "$0.002",
      "Split Check: before paying into (or trusting) an on-chain revenue split, verify what it actually pays. Detects 0xSplits v2 splits on Base / Base Sepolia, proves a claimed recipients+allocations config against the on-chain splitHash (or discovers it from recent events), shows each recipient's share, whether a given beneficiary is included, whether the split is immutable (no owner), and USDC waiting to be distributed. Read-only. By OMENZ.",
      {"address": "0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "network": "base", "claimed": {"recipients": ["0x1bd3aaa92243e3d4352bdce07050aec6fcf5e840", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"], "allocations": [970000, 30000]}, "beneficiary": "0x..."},
      {"properties": {"address": {"type": "string"}, "network": {"type": "string"}, "claimed": {"type": "object"}, "beneficiary": {"type": "string"}},
       "required": ["address"]}, body=True)

for _usd in (1, 5):
    _paid("POST", f"credits/buy-{_usd}", f"${_usd}.00",
          f"OMENZ prepaid credits: ${_usd}.00 balance in one x402 payment. Checks then draw from the balance with no per-check settlement: "
          "OMENZ Authorize costs 2% of the payment being checked (minimum $0.0003) via POST /v1/authorize/credit. Returns credit_id + credit_key (shown once). By OMENZ.",
          {}, {"properties": {}}, body=True)

_paid("GET", "market/report", "$1.00",
      "x402 Market Report (weekly): the supply side of the agent-payment economy: endpoints and sellers listed, how many get paid calls, price distribution, seller concentration (top 10 / top 50 share of calls), networks, top 25 sellers with usage. Compiled weekly by OMENZ from the x402 Bazaar index. By OMENZ.",
      {}, {"properties": {}})
_paid("GET", "market/sellers", "$0.25",
      "x402 Seller Lead List: sellers offering a capability (or all), with endpoints, 30-day calls, unique payers, price range, last-called date and an example endpoint; up to 500 rows. For payment platforms, investors and sellers sizing a niche. Public listing data. By OMENZ.",
      {"q": "web search", "min_payers": 5, "limit": 100},
      {"properties": {"q": {"type": "string"}, "min_payers": {"type": "integer"}, "limit": {"type": "integer"}}})

_paid("POST", "jacket/create", "$0.002",
      "Job Jacket: create the portable minimum working state for one assignment (objective, instructions, state, checkpoint, optional Permission Passport + Job Ledger link). Encrypted with a key only you hold, up to 30 days, 64 KB. Returns jacket_id + jacket_key (shown once). Credentials are refused: keep reference names only. By OMENZ.",
      {"job_id": "job-42", "objective": "get today's hours for 20 restaurants", "instructions": "precision first", "state": {"done": [], "todo": ["a.com", "b.com"]}, "worker": "agent-a"},
      {"properties": {"objective": {"type": "string"}, "job_id": {"type": "string"}, "instructions": {"type": "string"}, "state": {"type": "object"}, "checkpoint": {"type": "string"}, "passport_token": {"type": "string"}, "ledger_id": {"type": "string"}, "ttl_days": {"type": "integer"}}, "required": ["objective"]}, body=True)
_paid("POST", "jacket/checkout", "$0.002",
      "Job Jacket checkout: start a shift. Returns only what this worker needs (objective, instructions, checkpoint, state trimmed to requested fields / size, Passport verdict) and a lease so no other worker holds it at the same time; take_over for dead workers. Headers X-Jacket-Id / X-Jacket-Key. By OMENZ.",
      {"worker": "agent-b", "fields": ["todo"], "max_string_chars": 400, "lease_minutes": 60},
      {"properties": {"worker": {"type": "string"}, "fields": {"type": "array"}, "max_string_chars": {"type": "integer"}, "lease_minutes": {"type": "integer"}, "take_over": {"type": "boolean"}}, "required": ["worker"]}, body=True)
_paid("POST", "jacket/checkin", "$0.002",
      "Job Jacket checkin: end a shift. state_patch merges (null deletes a key) or state replaces; new checkpoint and note; the jacket becomes a new version and the lease is released. Optional Job Ledger entry (header X-Ledger-Key). Headers X-Jacket-Id / X-Jacket-Key. By OMENZ.",
      {"worker": "agent-b", "state_patch": {"done": ["a.com"], "todo": ["b.com"]}, "checkpoint": "1 of 2 done", "note": "a.com closed Sundays"},
      {"properties": {"worker": {"type": "string"}, "state_patch": {"type": "object"}, "state": {"type": "object"}, "checkpoint": {"type": "string"}, "note": {"type": "string"}, "keep_lease": {"type": "boolean"}}, "required": ["worker"]}, body=True)
_paid("GET", "jacket/history", "$0.002",
      "Job Jacket history: every version (who, when, checkpoint, note, state hash; never the contents) and the current lease. Headers X-Jacket-Id / X-Jacket-Key. By OMENZ.",
      {}, {"properties": {}})

_paid("POST", "send/check", "$0.005",
      "Send Check: one call before an agent sends USDC or ETH on Base. Recipient on the OFAC sanctions list -> STOP; recipient is the token contract itself -> STOP; ADDRESS POISONING (recipient looks like a payee you used before, same first and last 4 characters, but isn't) -> STOP; sender balance too low -> STOP; recipient is a contract or a never-used address -> CAUTION. Verdict SEND / CAUTION / STOP with reasons. Read-only public chain data; never signs or moves money. By OMENZ.",
      {"from": "0xc9c7b38C0942914fC8EA12063BC92dcd3b581670", "to": "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840", "asset": "USDC", "amount": 0.01},
      {"properties": {"from": {"type": "string"}, "to": {"type": "string"}, "asset": {"type": "string", "enum": ["USDC", "ETH"]}, "amount": {"type": "number"}, "history_days": {"type": "number"}}, "required": ["to"]}, body=True)
_paid("POST", "wallet-watch", "$0.01",
      "Wallet Watch: never run dry mid-job. Register an agent's Base wallet with min_usdc and/or min_days (runway at its recent spend rate); OMENZ checks it daily for up to 30 days and drops ONE alert into your Agent PO Box when it runs low (re-arms after you top up). Read-only public chain data; never touches the wallet. Returns watch_id + watch_key (shown once). By OMENZ.",
      {"address": "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840", "min_usdc": 2, "min_days": 3, "pobox_id": "box_...", "days": 30},
      {"properties": {"address": {"type": "string"}, "min_usdc": {"type": "number"}, "min_days": {"type": "number"}, "pobox_id": {"type": "string"}, "days": {"type": "integer"}}, "required": ["address"]}, body=True)
_paid("GET", "wallet-watch/report", "$0.002",
      "Wallet Watch report: current USDC, runway days, state OK / ALERTING, low checks and the last 14 checks. Header X-Watch-Key. By OMENZ.",
      {"id": "ww_..."}, {"properties": {"id": {"type": "string"}}, "required": ["id"]})
_paid("POST", "uptime/watch", "$0.01",
      "Uptime Watch: register a paid endpoint your agent depends on; OMENZ checks it daily (and on each report) for 30 days: up/down, latency, live x402 price and payTo, so you catch outages, price drift and swapped payout wallets before paying. Never pays the endpoint. Returns watch_id + watch_key (shown once). By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET", "days": 30},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "days": {"type": "integer"}}, "required": ["url"]}, body=True)
_paid("GET", "uptime/report", "$0.002",
      "Uptime Watch report: uptime %, median latency, incidents, price changes and payout-wallet changes for a watched endpoint, plus recent checks. When the endpoint is down (or substitutes=true) it also returns the 3 best live substitutes from ~38,000 x402 APIs. Header X-Watch-Key. By OMENZ.",
      {"id": "uw_..."}, {"properties": {"id": {"type": "string"}}, "required": ["id"]})

# Buyer Kit (founder 2026-11-17: "more tools for agents who are going to be buying stuff"): budget/*, pay/verify, delivery-check
_paid("POST", "budget/create", "$0.002",
      "Shared Budget: one spending cap a whole TEAM of agents draws from (total, per day or per month), with a per-purchase max, an escalate line and allowed/blocked payees. Spend Gate is stateless, so 5 agents can each stay under $1 and spend $5 together; a Shared Budget keeps the one running total. Returns budget_id + owner_key + spender_key (shown once). Bookkeeping only: OMENZ never holds or moves money. By OMENZ.",
      {"name": "research crew", "cap_usd": 2, "period": "day", "per_tx_max_usd": 0.05, "escalate_above_usd": 0.02},
      {"properties": {"name": {"type": "string"}, "cap_usd": {"type": "number"}, "period": {"type": "string", "enum": ["total", "day", "month"]},
                      "per_tx_max_usd": {"type": "number"}, "escalate_above_usd": {"type": "number"},
                      "allowed_recipients": {"type": "array"}, "blocked_recipients": {"type": "array"}, "ttl_days": {"type": "integer"},
                      "velocity_max_per_hour": {"type": "integer"}},
       "required": ["cap_usd"]}, body=True)
_paid("POST", "budget/spend", "$0.002",
      "Shared Budget: ask before each purchase. ALLOW records it against the team cap (returns spend_id + what's left); DENY or ESCALATE records nothing, with the reason. Idempotent by idempotency_key, so retries never double-count. Header X-Budget-Key. Honest limit: two spends in the same instant can both pass; per_tx_max_usd bounds that. By OMENZ.",
      {"budget_id": "bg_...", "amount_usd": 0.01, "recipient": "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840", "agent": "worker-3",
       "url": "https://www.omenz.org/api/tollbooth/v1/local-facts", "idempotency_key": "job42-call7"},
      {"properties": {"budget_id": {"type": "string"}, "amount_usd": {"type": "number"}, "recipient": {"type": "string"}, "agent": {"type": "string"},
                      "url": {"type": "string"}, "memo": {"type": "string"}, "idempotency_key": {"type": "string"}}, "required": ["budget_id", "amount_usd"]}, body=True)
_paid("POST", "budget/release", "$0.002",
      "Shared Budget: give a recorded spend back to the cap when the purchase failed, was refunded or never happened. Header X-Budget-Key. By OMENZ.",
      {"budget_id": "bg_...", "spend_id": "sp_...", "reason": "seller timed out"},
      {"properties": {"budget_id": {"type": "string"}, "spend_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["budget_id", "spend_id"]}, body=True)
_paid("GET", "budget/status", "$0.002",
      "Shared Budget: cap, spent, remaining this window, spend by agent and by payee, recent purchases. Header X-Budget-Key (owner or spender). By OMENZ.",
      {"id": "bg_..."}, {"properties": {"id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["id"]})
_paid("POST", "pay/verify", "$0.002",
      "Payment Verify: did this x402 payment really settle on Base? Send the tx hash or the seller's PAYMENT-RESPONSE header; get SETTLED / MISMATCH / PENDING / FAILED / NOT_FOUND with payer, payee, USDC amount, block, confirmations and time, checked against the payee/amount you expected. Also Circle Gateway batched payments (GatewayWalletBatched, no per-payment tx): send gateway_nonce or gateway_transfer_id and get PENDING / CONFIRMED / SETTLED / FAILED with payer, payee, amount and the batch tx. Proof for disputes, refunds and books. Public data, never needs a key. By OMENZ.",
      {"tx_hash": "0x...", "expected_pay_to": "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840", "expected_amount_usd": 0.001},
      {"properties": {"tx_hash": {"type": "string"}, "payment_response": {"type": "string"}, "expected_pay_to": {"type": "string"},
                      "expected_payer": {"type": "string"}, "expected_amount_usd": {"type": "number"}, "max_amount_usd": {"type": "number"},
                      "min_confirmations": {"type": "integer"}, "gateway_nonce": {"type": "string"}, "gateway_transfer_id": {"type": "string"}}}, body=True)
_paid("POST", "delivery-check", "$0.002",
      "Delivery Check: you paid; did you get what was advertised? Send the paid endpoint's url (+ method) and the JSON it returned. We read the seller's own x402 discovery output example (unpaid probe) or use your JSON Schema, then compare fields and value types: MATCH / PARTIAL / MISMATCH / NO_CONTRACT, with exactly what's missing, empty or the wrong kind, and error bodies caught. Evidence for finance/refund-request. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET", "delivered": {"status": "up"}},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "delivered": {}, "schema": {"type": "object"},
                      "example": {}, "must_have": {"type": "array"}}, "required": ["delivered"]}, body=True)

_paid("GET", "market/cheapest", "$0.002",
      "Cheapest Working Tool: 'I need X' -> the cheapest x402 provider that ANSWERS right now. Matches from ~38,000 indexed endpoints, sorted by price, each live-probed (unpaid) in that order; returns the pick + runners-up by live price and latency, and the cheap-but-dead ones it skipped. Never pays a target. By OMENZ.",
      {"q": "token price", "max_price_usd": 0.01, "want": 3},
      {"properties": {"q": {"type": "string"}, "max_price_usd": {"type": "number"}, "network": {"type": "string"}, "want": {"type": "integer"},
                      "min_match": {"type": "number"}}, "required": ["q"]})
_paid("POST", "spend-receipt", "$0.003",
      "Spend Receipt: one signed receipt per purchase: what your agent bought, why, what it cost (verified on Base from the tx hash or PAYMENT-RESPONSE) and what came back (checked against the seller's advertised output). GOOD_BUY / PAID_NOT_DELIVERED / PAID_PARTLY_DELIVERED / PAYMENT_NOT_CONFIRMED. Ed25519-signed, verifiable offline. Payment Verify + Delivery Check in one call. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET", "tx_hash": "0x...", "expected_amount_usd": 0.001,
       "delivered": {"status": "up"}, "purpose": "check vendor before job", "agent": "worker-3", "job_id": "job-42"},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "tx_hash": {"type": "string"}, "payment_response": {"type": "string"},
                      "expected_pay_to": {"type": "string"}, "expected_amount_usd": {"type": "number"}, "delivered": {}, "schema": {"type": "object"},
                      "purpose": {"type": "string"}, "agent": {"type": "string"}, "job_id": {"type": "string"}}, "required": ["url"]}, body=True)

_paid("POST", "checkout/open", "$0.002",
      "OMENZ Checkout (open): ONE call before your agent pays any x402 seller. Send the url (or just q = what you need and OMENZ picks the cheapest seller that answers right now), your max price, optional Shared Budget (budget_id + X-Budget-Key) and policy. Runs Authorize (live quote, payTo, fair price, policy), the seller's OMENZ track record, and draws from the team budget: GO / REVIEW / STOP + checkout_id + signed 5-minute authorization. Provider-neutral, any wallet; never touches your money. High volume: checkout/open/credit at 1% of the purchase (min $0.0002). By OMENZ.",
      {"q": "token price", "max_price_usd": 0.01, "budget_id": "bg_...", "agent": "worker-3", "purpose": "BTC price for the report"},
      {"properties": {"url": {"type": "string"}, "q": {"type": "string"}, "method": {"type": "string"}, "max_price_usd": {"type": "number"},
                      "expected_pay_to": {"type": "string"}, "budget_id": {"type": "string"}, "policy": {"type": "object"}, "agent": {"type": "string"},
                      "purpose": {"type": "string"}, "job_id": {"type": "string"}, "idempotency_key": {"type": "string"}}}, body=True)
_paid("POST", "checkout/close", "$0.002",
      "OMENZ Checkout (close): ONE call after paying. Send checkout_id + the tx hash (or PAYMENT-RESPONSE header) + the response you got. Verifies settlement on Base against the authorized payee and amount, checks delivery against the seller's advertised output, returns a signed Spend Receipt (GOOD_BUY / PAID_NOT_DELIVERED / PAYMENT_NOT_CONFIRMED), gives the money back to the Shared Budget if you never paid, and updates the seller's track record. High volume: checkout/close/credit at 1% (min $0.0002). By OMENZ.",
      {"checkout_id": "ck_...", "tx_hash": "0x...", "delivered": {"price": 80915.2}},
      {"properties": {"checkout_id": {"type": "string"}, "tx_hash": {"type": "string"}, "payment_response": {"type": "string"}, "delivered": {},
                      "schema": {"type": "object"}, "not_paid": {"type": "boolean"}, "release_if_unconfirmed": {"type": "boolean"}},
       "required": ["checkout_id"]}, body=True)
_paid("GET", "seller-record", "$0.002",
      "Seller Track Record: how an x402 seller actually performed for buyers who checked out through OMENZ: purchases closed, delivery rate, outcomes (good buy / paid not delivered), USDC settled (verified on Base), first/last seen. Aggregate per seller host, no buyer data. By OMENZ.",
      {"host": "prices.genexxis.com"}, {"properties": {"host": {"type": "string"}}, "required": ["host"]})

_paid("GET", "facilitators", "$0.002",
      "Facilitator Status + Router: which x402 facilitators are answering RIGHT NOW and which to use. Live probe of 10 known facilitators (PayAI, Coinbase CDP, x402.rs, Daydreams, Dexter, Mogami, OpenX402, the x402.org reference and more, plus one URL of yours): up / auth_required / down, latency, networks, schemes (exact/upto), x402 versions. Say network + scheme and get the fastest live facilitator plus fallbacks. For sellers choosing or failing over a facilitator, and SDKs routing settlement. Never pays or settles anything. By OMENZ.",
      {"network": "base", "scheme": "exact"},
      {"properties": {"network": {"type": "string"}, "scheme": {"type": "string"}, "x402_version": {"type": "integer"}, "url": {"type": "string"}}})

_paid("POST", "sale/record", "$0.002",
      "Sale Record (for SELLERS): after each x402 sale, your middleware sends the tx hash (or PAYMENT-RESPONSE) + the route sold. OMENZ checks the payment really settled on Base to the payTo your route advertises right now, counts it once, and returns a signed sale receipt. Verified sales and distinct payers show in your public Seller Track Record, which buyers see in OMENZ Checkout before paying. Proof of real sales, not claims. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/alive", "method": "GET", "tx_hash": "0x..."},
      {"properties": {"url": {"type": "string"}, "method": {"type": "string"}, "tx_hash": {"type": "string"}, "payment_response": {"type": "string"}},
       "required": ["url"]}, body=True)

_paid("GET", "tx/decode", "$0.002",
      "Transaction Decode (Base): what did this transaction actually do, in plain English. Status, confirmations, function called, every token transfer (symbol + amount), approvals (UNLIMITED approvals flagged), NFT moves, fee, time, and whether it was an x402 payment (EIP-3009 transferWithAuthorization). For agents checking a payment, a refund, or what a contract just did with their money. Public chain data, never needs a key. By OMENZ.",
      {"tx_hash": "0x..."}, {"properties": {"tx_hash": {"type": "string"}}, "required": ["tx_hash"]})
_paid("GET", "name/resolve", "$0.002",
      "Name Resolve: ENS (name.eth) and Basenames (name.base.eth) to address, or an address to its primary ENS name, forward-verified so a spoofed reverse record is flagged. For agents about to pay or trust 'vitalik.eth' or 'shop.base.eth'. Public chain data. By OMENZ. v0.2: expected_address -> MATCH/MISMATCH, Basename reverse too, wallet/contract/EIP-7702 on Base, OFAC screen, look-alike (non-ASCII) warning.",
      {"q": "vitalik.eth"}, {"properties": {"q": {"type": "string", "description": "name or 0x address"}, "expected_address": {"type": "string", "description": "the address you were told to pay: returns verdict MATCH or MISMATCH"}}, "required": ["q"]})

_paid("GET", "weather", "$0.002",
      "OMENZ Weather: forecast for any coordinates on Earth, shaped for agents. Now (temp C/F, wind, humidity, cloud, pressure, condition), next 6h and 24h (high/low, rain total, max wind), up to a 5-day outlook, and yes/no flags to branch on: rain_next_6h, freezing_next_24h, high_wind_next_24h, heat_next_24h. Source: MET Norway (Norwegian Meteorological Institute), cached responsibly. By OMENZ.",
      {"lat": "34.1478", "lon": "-118.1445", "days": "3"},
      {"properties": {"lat": {"type": "number"}, "lon": {"type": "number"}, "days": {"type": "integer", "description": "1-5, default 3"}}, "required": ["lat", "lon"]})
_paid("GET", "ip/check", "$0.002",
      "OMENZ IP Check: who is behind this IP, and is it a person, a server or an anonymizer? Owner organization, network range and registry country (RDAP), reverse DNS, cloud/CDN membership (AWS, Google Cloud, Cloudflare published ranges), Tor exit node. ANONYMIZER / DATACENTER / NOT_A_KNOWN_DATACENTER with signals, for signup screening, fraud checks, rate limits and log triage. IPv4 + IPv6. Registry country, not a guessed street location. By OMENZ.",
      {"ip": "8.8.8.8"},
      {"properties": {"ip": {"type": "string"}}, "required": ["ip"]})
_paid("GET", "fx/convert", "$0.002",
      "OMENZ FX Rates: convert an amount between ~30 currencies (USD, EUR, GBP, JPY, MXN, CAD, AUD, CHF, CNY, INR, BRL...) at the European Central Bank's official reference rate, today or any business day in the last 90 days (weekends/holidays use the previous business day, said so). Returns result, rate, inverse rate and the rate date. Deterministic and auditable for invoices, pricing and bookkeeping; not a live trading quote. By OMENZ.",
      {"amount": "100", "from": "USD", "to": "EUR"},
      {"properties": {"amount": {"type": "number"}, "from": {"type": "string"}, "to": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD, optional, last 90 days"}}, "required": ["from", "to"]})
_paid("POST", "lead/check", "$0.005",
      "OMENZ Lead Check: is this lead real enough to spend time on? One call runs Email Check + Phone Check + Domain Check (cheaper than all three) plus cross-checks: does the email domain match the company website, brand-new website, fictional/premium/VoIP phone, disposable email. FAKE_OR_UNUSABLE / WEAK / GOOD_LEAD with reasons. Send any of email, phone (+country), website. Public DNS/RDAP + offline phone data, no SMTP probe, nothing stored. By OMENZ.",
      {"email": "hello@omenz.org", "phone": "+1 650 253 0000", "website": "omenz.org"},
      {"properties": {"email": {"type": "string"}, "phone": {"type": "string"}, "country": {"type": "string"}, "website": {"type": "string"}}})
_paid("GET", "link/check", "$0.003",
      "OMENZ Link Check: where does this link really go, and is it safe to follow, sign in or pay? Follows the redirect chain hop by hop (unshortens bit.ly/tinyurl etc.), then checks the destination: TLS certificate (valid, issuer, days to expiry, hostname match), destination domain age (RDAP), plain http, page status. DANGER (bad/expired cert, new domain < 30 days, redirect loop, private-network target) / CAUTION (shortener, lands on a different site than shown, http, expiring cert, many hops, 4xx/5xx) / UNREACHABLE / OK. Never submits forms, runs scripts or pays. By OMENZ.",
      {"url": "https://bit.ly/3x"},
      {"properties": {"url": {"type": "string"}}, "required": ["url"]})
_paid("GET", "email/check", "$0.002",
      "OMENZ Email Check: is this email address real enough to use? UNDELIVERABLE (bad syntax, no such domain, no mail server) / RISKY (disposable throwaway provider, or a domain with no SPF and no DMARC) / DELIVERABLE_LIKELY. Also: free webmail vs company domain, role account (info@, sales@), plus-addressing and the normalized address. Public DNS only, no SMTP probing, nothing stored. Pairs with Phone Check for leads and signups. By OMENZ.",
      {"email": "hello@omenz.org"},
      {"properties": {"email": {"type": "string"}}, "required": ["email"]})
_paid("GET", "phone/check", "$0.002",
      "OMENZ Phone Check: is this a real, dialable phone number and what kind? VALID / POSSIBLE_BUT_INVALID / INVALID / FICTIONAL (555-01XX), E.164 + international + national formats, country, type (mobile, landline, toll-free, premium-rate, VoIP...), location, original carrier, time zones, can-it-SMS, and warnings before an agent calls or texts (premium-rate cost, VoIP, landline). Fully offline (Google libphonenumber data): nothing leaves OMENZ, nothing stored. By OMENZ.",
      {"number": "+1 650 253 0000"},
      {"properties": {"number": {"type": "string"}, "country": {"type": "string", "description": "2-letter ISO code for local formats, e.g. US"}}, "required": ["number"]})
_paid("GET", "domain/check", "$0.003",
      "OMENZ Domain Check: should your agent trust this domain before paying it or emailing it? Registration age and expiry (RDAP), registrar and registry status, does it resolve, can it receive mail (MX), SPF and DMARC (can others spoof it?). RED_FLAGS if unregistered, not resolving, on hold or registered < 30 days ago; CAUTION if young, expiring, or missing mail/anti-spoofing records; LOOKS_ESTABLISHED otherwise. Subdomains are checked against their registered domain. Public data (RDAP + DNS-over-HTTPS), no keys. By OMENZ.",
      {"domain": "example.com"},
      {"properties": {"domain": {"type": "string", "description": "domain or URL"}}, "required": ["domain"]})
_paid("GET", "package/check", "$0.003",
      "OMENZ Package Check: is this software package safe for your agent to install? npm, PyPI, Go, Cargo, Maven, NuGet. BLOCK if the package does not exist (hallucinated name: slopsquatting risk, with 'did you mean') or the version has HIGH/CRITICAL known vulnerabilities; CAUTION if deprecated, under 30 days old, any known vuln, no license, or a near-miss of a popular package name (typosquat); SAFE_TO_INSTALL otherwise. Returns the vulns, the version to upgrade to, license and package age. Sources: deps.dev + OSV.dev. Deterministic, read-only. By OMENZ.",
      {"ecosystem": "pypi", "name": "requests", "version": "2.19.0"},
      {"properties": {"ecosystem": {"type": "string", "enum": ["pypi", "npm", "go", "cargo", "maven", "nuget"]}, "name": {"type": "string"}, "version": {"type": "string"}}, "required": ["ecosystem", "name"]})
_paid("GET", "token/check", "$0.005",
      "OMENZ Token Check (Base): is this token safe to hold or accept, before your agent buys, swaps or takes it as payment? Reads the contract itself: real ERC-20 or not, upgradeable proxy (EIP-1967 / OpenZeppelin slots: code can change under you), active owner and the powers in its bytecode (mint, pause, blacklist/freeze, fees, tx limits), owner/admin on the OFAC SDN list. SAFE_TO_HOLD / CAUTION / RED_FLAGS with every reason; regulated stablecoins labeled (issuer freeze is by design). Deterministic: no AI grades, no price predictions. Public chain data, never signs. Source-code verification via Sourcify (token + implementation; unverified = CAUTION). By OMENZ.",
      {"token": "0x4200000000000000000000000000000000000006"},
      {"properties": {"token": {"type": "string", "description": "ERC-20 contract address on Base"}}, "required": ["token"]})
_paid("GET", "token/balance", "$0.002",
      "Token Balance (Base): balance of any ERC-20 (symbol + decimals resolved) or native ETH for an address, raw and human units, read live from Base. For agents checking they can afford a purchase, or that a payment arrived. Public chain data, never needs a key. By OMENZ.",
      {"address": "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840", "token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
      {"properties": {"address": {"type": "string"}, "token": {"type": "string", "description": "ERC-20 address on Base; omit or 'eth' for native ETH"}}, "required": ["address"]})
_paid("GET", "allowance", "$0.002",
      "Allowance Check (Base): how much can this spender move from this wallet right now? Reads the live ERC-20 allowance and the owner's balance: UNLIMITED (risk HIGH) / COVERS_FULL_BALANCE / LIMITED / NO_ALLOWANCE, with a safe next action and the exact revoke call (approve(spender, 0)). Optional intended_usd says whether a stablecoin allowance covers your next payment. For agents before approving, paying through a contract, or cleaning up old approvals. Public chain data, never signs. By OMENZ.",
      {"owner": "0x1bd3AaA92243e3d4352bdcE07050aeC6fcF5e840", "token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "spender": "0x000000000022D473030F116dDEE9F6B43aC78BA3"},
      {"properties": {"owner": {"type": "string"}, "token": {"type": "string"}, "spender": {"type": "string"}, "intended_usd": {"type": "number"}}, "required": ["owner", "token", "spender"]})

_paid("POST", "seller/acceptance-check", "$0.05",
      "Seller Payment-Acceptance Check: is your x402 server turning away paying agents? We probe YOUR route with a throwaway, unfunded key (no money can move): a fresh payment must reach your facilitator; a payment echoing an older 402 (changed description/example, changed timeout) must not be refused; an x402 v1 X-PAYMENT must not be ignored silently. Verdict ACCEPTS_GOOD_MONEY / REFUSES_GOOD_MONEY / SERVES_UNPAID / NO_VALID_402 with each problem and the exact fix. OMENZ found this leak on its own server: a funded repeat buyer was refused 4 times. Max 5 requests to your URL. By OMENZ.",
      {"url": "https://www.omenz.org/api/tollbooth/v1/site-check?url=https://example.com", "method": "GET"},
      {"properties": {"url": {"type": "string", "description": "your x402 route (https)"}, "method": {"type": "string", "enum": ["GET", "POST"]}}, "required": ["url"]}, body=True)

_paid("GET", "settlement-cost", "$0.002",
      "Settlement Cost Check (Base): what moving money costs RIGHT NOW (live gas price, L1 data fee, ETH/USD from Chainlink on Base) for an x402 settlement (~86,550 gas, measured), a USDC transfer, an ETH transfer and an approval, in ETH and USD. Send amount_usd (+ payments_per_day) to learn whether a payment that small is worth settling on its own: SETTLE / BATCH_OR_CREDITS / DONT_SETTLE_SINGLY, the overhead %, break-even payment size, and cheaper options (CDP free tier, Circle Gateway batching, prepaid credits). By OMENZ.",
      {"amount_usd": 0.001, "payments_per_day": 5000},
      {"properties": {"amount_usd": {"type": "number"}, "payments_per_day": {"type": "integer"}}})

_paid("POST", "guard", "$0.05",
      "OMENZ Transaction Guard: ONE call before money moves. 'PAY $X TO Y FOR Z' -> GO / CAUTION / STOP with every check: budget authorized (Shared Budget), counterparty checked (Authorize: live 402, payTo, known seller, OFAC sanctions screen, fair price + Seller Track Record), DUPLICATE PAYMENT checked (OMENZ records and your on-chain USDC history to that payee, Base), quoted price unchanged, settlement economics, expected delivery recorded (seller's advertised output fingerprint). Then checkout/close: settled -> delivery verified -> signed receipt -> reconciled. Send url (or q), payer (your wallet), quoted_price_usd, purpose, budget_id. Larger purchases: guard/credit at 10 bps of the protected value (min $0.01, max $5). Never touches your money. By OMENZ.",
      {"url": "https://prices.genexxis.com/token-price", "method": "GET", "payer": "0x...", "quoted_price_usd": 0.003, "max_price_usd": 0.01,
       "purpose": "BTC price for the daily report", "budget_id": "bg_..."},
      {"properties": {"url": {"type": "string"}, "q": {"type": "string"}, "method": {"type": "string"}, "payer": {"type": "string"},
                      "quoted_price_usd": {"type": "number"}, "max_price_usd": {"type": "number"}, "expected_pay_to": {"type": "string"},
                      "purpose": {"type": "string"}, "budget_id": {"type": "string"}, "policy": {"type": "object"}, "agent": {"type": "string"},
                      "dup_window_hours": {"type": "integer"}}}, body=True)

_paid("POST", "budget/delegate", "$0.01",
      "Delegation Budget (agent allowances): a parent budget's OWNER gives a child agent its own bounded allowance: human/company -> supervisor agent -> workers -> sub-agents (4 levels). The child can only NARROW the parent: cap <= parent, per-purchase max, allowed payees (subset), blocked payees (inherited), velocity limit (purchases/hour), expiry <= parent. Every child spend is checked against and counted in every ancestor, so the company cap holds across the whole tree; freezing a parent stops all descendants; budget/status shows spend by child. Header X-Budget-Key = the parent's owner_key. Bookkeeping only. By OMENZ.",
      {"budget_id": "bg_...(parent)", "name": "worker-3", "cap_usd": 0.5, "per_tx_max_usd": 0.05, "allowed_recipients": ["0x..."], "velocity_max_per_hour": 60},
      {"properties": {"budget_id": {"type": "string"}, "name": {"type": "string"}, "cap_usd": {"type": "number"}, "period": {"type": "string"},
                      "per_tx_max_usd": {"type": "number"}, "escalate_above_usd": {"type": "number"}, "allowed_recipients": {"type": "array"},
                      "blocked_recipients": {"type": "array"}, "velocity_max_per_hour": {"type": "integer"}, "ttl_days": {"type": "integer"}},
       "required": ["budget_id", "cap_usd"]}, body=True)
_paid("POST", "settlement/rescue", "$0.05",
      "Settlement Rescue: 'payment weird? give it to us.' Timeout, 5xx or no PAYMENT-RESPONSE after paying, and you must decide whether to pay again. Send the X-PAYMENT header you sent (or the tx hash, or payer + payee + amount). We read the EIP-3009 authorization's on-chain state on Base: SETTLED (nonce used: here is the tx, do NOT pay again) / NOT_SETTLED (expired unused: safe to pay again ONCE) / STILL_UNCERTAIN (unused but still valid: a facilitator can still settle it, do NOT sign a new one yet, with seconds left) / NOT_FOUND_ON_CHAIN, plus a duplicate-payment scan, a safe next action and a signed record for refunds and disputes. Read-only. By OMENZ.",
      {"payment_header": "(the base64 X-PAYMENT you sent)", "window_hours": 24},
      {"properties": {"payment_header": {"type": "string"}, "authorization": {"type": "object"}, "tx_hash": {"type": "string"}, "payer": {"type": "string"},
                      "pay_to": {"type": "string"}, "amount_usd": {"type": "number"}, "window_hours": {"type": "integer"}}}, body=True)

_paid("POST", "market/job", "$0.01",
      "OMENZ Market job desk: tell OMENZ the JOB ('token price', 'weather by city', 'company enrichment by domain'). We search ~38,000 x402 endpoints, live-probe the matches (unpaid), and rank WORKING providers by live price and latency, each with its OMENZ-verified history (purchases checked, delivery rate, verified sales), plus settlement economics and a ready-to-send Transaction Guard request for the pick. Then guard -> pay -> checkout/close -> (settlement/rescue if weird). Want it guarded in the same call? POST market/job/guarded ($0.05). Never pays a provider. By OMENZ.",
      {"need": "token price", "max_price_usd": 0.01, "purpose": "BTC price for the daily report"},
      {"properties": {"need": {"type": "string"}, "max_price_usd": {"type": "number"}, "network": {"type": "string"}, "want": {"type": "integer"},
                      "purpose": {"type": "string"}, "payer": {"type": "string"}, "budget_id": {"type": "string"}}, "required": ["need"]}, body=True)
_paid("POST", "market/job/guarded", "$0.05",
      "OMENZ Market job desk + Transaction Guard in one call: find the working provider for your job, then GO / CAUTION / STOP with budget, counterparty, duplicate payment (send payer), quoted price, settlement economics and expected delivery checked, plus a checkout_id for checkout/close. Same price as Guard alone. By OMENZ.",
      {"need": "token price", "max_price_usd": 0.01, "payer": "0x...", "budget_id": "bg_..."},
      {"properties": {"need": {"type": "string"}, "max_price_usd": {"type": "number"}, "payer": {"type": "string"}, "budget_id": {"type": "string"},
                      "purpose": {"type": "string"}}, "required": ["need"]}, body=True)

_paid("POST", "dispute/packet", "$0.10",
      "Dispute Packet: a purchase went bad (not delivered, wrong output, partial, overcharged, duplicate). One call builds the machine-readable case: settlement proof on Base (Settlement Rescue: did money move, how much, to whom, duplicates), the seller's own advertised output captured live (what was promised), a Delivery Check of what came back, a timeline, and a signed refund request (remedy + amount + evidence strength), all hash-listed in an Ed25519-signed manifest anyone can verify offline. Send checkout_id or url + tx_hash / payment_header / payer+pay_to, the delivered response and the issue. OMENZ packages evidence; it never rules on disputes or moves money. By OMENZ.",
      {"url": "https://prices.genexxis.com/token-price", "tx_hash": "0x...", "payer": "0x...", "delivered": {"error": "upstream timeout"}, "issue": "wrong_output"},
      {"properties": {"checkout_id": {"type": "string"}, "url": {"type": "string"}, "method": {"type": "string"}, "tx_hash": {"type": "string"},
                      "payment_header": {"type": "string"}, "payer": {"type": "string"}, "pay_to": {"type": "string"}, "amount_usd": {"type": "number"},
                      "delivered": {}, "schema": {"type": "object"}, "issue": {"type": "string", "enum": ["not_delivered", "wrong_output", "partial", "overcharged", "duplicate", "other"]},
                      "what": {"type": "string"}, "seller": {"type": "string"}, "amount_requested_usd": {"type": "number"}}}, body=True)

_paid("POST", "po/issue", "$0.01",
      "Agent Purchase Order: whoever controls the money pre-approves ONE purchase: 'this agent may spend up to $X with seller Y (payTo and/or host) for Z, until T'. Returns an Ed25519-signed, single-use PO token anyone can verify offline. Budget-backed POs (budget_id + X-Budget-Key) draw from the Shared Budget on redeem, so team caps and the delegation tree still apply. By OMENZ.",
      {"max_usd": 0.5, "pay_to": "0x9287e3102d411029025c7617d75245bfc7920f17", "seller": "prices.genexxis.com", "for": "BTC price for the daily report",
       "agent": "worker-3", "budget_id": "bg_...", "expires_in_hours": 24},
      {"properties": {"max_usd": {"type": "number"}, "pay_to": {"type": "string"}, "seller": {"type": "string"}, "for": {"type": "string"},
                      "agent": {"type": "string"}, "budget_id": {"type": "string"}, "job_id": {"type": "string"}, "expires_in_hours": {"type": "number"}},
       "required": ["max_usd"]}, body=True)
_paid("POST", "po/redeem", "$0.002",
      "Agent Purchase Order redeem: the buyer agent (or the seller, before serving) checks a PO right before paying: signature, expiry, payee, seller, amount <= max, and that it was never used. ALLOW marks it used (once) and, if budget-backed, draws the amount from the Shared Budget; returns a signed redemption record. By OMENZ.",
      {"token": "(PO token)", "amount_usd": 0.003, "pay_to": "0x9287e3102d411029025c7617d75245bfc7920f17", "url": "https://prices.genexxis.com/token-price"},
      {"properties": {"token": {"type": "string"}, "amount_usd": {"type": "number"}, "pay_to": {"type": "string"}, "seller": {"type": "string"},
                      "url": {"type": "string"}}, "required": ["token", "amount_usd"]}, body=True)

_LO_IN = {"loadout": "host-mode", "platform": "unitree-g1"}
_LO_SCHEMA = {"properties": {"loadout": {"description": "preset id (GET /v1/loadouts) or an omenz.loadout.v0 object"},
                             "platform": {"description": "platform profile id or a custom {id, native, addon} manifest"},
                             "allow_addons": {"type": "boolean"}}, "required": ["loadout"]}
_paid("POST", "loadout/check", "$0.01",
      "OMENZ Loadout Check: will this job loadout (Agent Skin or robot loadout like HOST MODE, PERSONAL TRAINER, RECEPTIONIST) run on this robot or agent? Provider-neutral capability words vs the platform profile (ROS 2 via ros-mcp, Unitree G1/Go2 via unitree_sdk2, digital MCP agent, OMENZ sim, or your own manifest): READY / DEGRADED / NOT_COMPATIBLE per capability and workflow, add-ons to install, safety-declaration gaps (e-stop, speed, no-go zones, contact), and what a human must confirm. Deterministic. By OMENZ.",
      _LO_IN, _LO_SCHEMA, body=True)
_paid("POST", "loadout/compile", "$0.02",
      "OMENZ Loadout Compile: turn a loadout into the platform plan (nav2 action goals for ros-mcp, unitree_sdk2 calls, or MCP tools + an Authorize passport request) plus an Ed25519-signed install receipt (omenz.loadout-install.v0: allowed capabilities, speed/payload limits, no-go zones, confirm list, expiry). Dry-run plans from public SDK docs; OMENZ never sends commands to hardware. By OMENZ.",
      {**_LO_IN, "platform": "ros2-mobile-manipulator", "valid_hours": 24}, _LO_SCHEMA, body=True)
_paid("POST", "loadout/simulate", "$0.005",
      "OMENZ Loadout Simulate: run one loadout workflow (e.g. HOST MODE drink_run) in the OMENZ 2D sim home: step-by-step trace, simulated time, and the action-gate decision on every step, so you see where it stops for a human yes before any robot moves. Deterministic, not physics. By OMENZ.",
      {"loadout": "host-mode", "workflow": "drink_run", "auto_confirm": False},
      {"properties": {"loadout": {}, "workflow": {"type": "string"}, "auto_confirm": {"type": "boolean"}, "context": {"type": "object"}},
       "required": ["loadout"]}, body=True)
_paid("POST", "robot/action-gate", "$0.002",
      "OMENZ Robot Action Gate: call before ONE physical action from a third-party skill or loadout. Checks the signed install receipt (or loadout), the capability, speed and payload limits, no-go zones, forbidden capabilities (face ID), people/children nearby and the human-confirm list: ALLOW / CONFIRM_FIRST / DENY + a signed receipt for the audit trail. The robot's own safety system still has the last word. By OMENZ.",
      {"install_token": "(from loadout/compile)", "action": {"cap": "arm.handover", "args": {"object": "cup"}},
       "context": {"human_confirmed": False, "children_present": True}},
      {"properties": {"install_token": {"type": "string"}, "loadout": {}, "action": {"type": "object"}, "context": {"type": "object"}},
       "required": ["action"]}, body=True)


def _attach_output_examples():
    """Advertise what each OMENZ route returns (the AYNE sample response) in its x402 discovery data, so buyers and
    Delivery Check can hold us to it. Same shape the x402 bazaar helper writes for output=OutputConfig(example=...)."""
    try:
        fx = ayne.fixtures()
    except Exception:
        return
    for k, v in ROUTES.items():
        sample = (fx.get(k) or {}).get("sample_response")
        baz = (v.get("extensions") or {}).get("bazaar")
        if not isinstance(sample, dict) or not isinstance(baz, dict) or (baz.get("info") or {}).get("output"):
            continue
        baz.setdefault("info", {})["output"] = {"type": "json", "example": sample}
        sch = baz.get("schema")
        if isinstance(sch, dict) and isinstance(sch.get("properties"), dict):
            sch["properties"]["output"] = {"type": "object", "properties": {"type": {"type": "string"}, "example": {"type": "object"}}, "required": ["type"]}


_attach_output_examples()

# Facilitator: Coinbase CDP when the founder has set CDP_API_KEY_ID/SECRET in Vercel (settlements then index our routes in
# the CDP Bazaar, where Coinbase's agents shop); otherwise PayAI (keyless). An explicit X402_FACILITATOR env var wins.
if cdp_auth.configured() and not os.environ.get("X402_FACILITATOR"):
    FACILITATOR, FACILITATOR_NAME = cdp_auth.URL, "coinbase-cdp"
    server = x402ResourceServer(HTTPFacilitatorClient({"url": cdp_auth.URL, "create_headers": cdp_auth.create_headers}))
else:
    FACILITATOR_NAME = "coinbase-cdp" if "cdp.coinbase" in FACILITATOR else "payai" if "payai" in FACILITATOR else FACILITATOR
    server = x402ResourceServer(HTTPFacilitatorClient({"url": FACILITATOR}))
server.register("eip155:*", ExactEvmServerScheme())
server.register_extension(bazaar_resource_server_extension)


# Stale-402 tolerance (11-20). Buyers who reuse an earlier 402 were rejected locally whenever we edited a route's
# description/example (extension_echo_mismatch) or any non-money field (No matching payment requirements); a funded
# repeat Authorize payer was turned away 4 times this way. Money terms stay strict: scheme, network, asset and payTo must
# match and the signed amount must be at least today's price. The facilitator still verifies the signature against OUR
# current requirements, so this only stops us refusing good money over discovery text.
def _lenient_match(available, payload):
    a = getattr(payload, "accepted", None)
    if a is None:
        return None
    for req in available:
        try:
            if (req.scheme == a.scheme and req.network == a.network and str(req.asset).lower() == str(a.asset).lower()
                    and str(req.pay_to).lower() == str(a.pay_to).lower() and int(a.amount) >= int(req.amount)):
                return req
        except (TypeError, ValueError):
            continue
    return None


_strict_validate_extensions = server.validate_extensions


def _validate_extensions_money_only(payment_required, payment_payload):
    ext = getattr(payment_payload, "extensions", None)
    if ext and "bazaar" in ext:  # bazaar = discovery metadata only; an old echo must not block a payment
        payment_payload = payment_payload.model_copy(update={"extensions": {k: v for k, v in ext.items() if k != "bazaar"}})
    return _strict_validate_extensions(payment_required, payment_payload)


server.find_matching_requirements = _lenient_match
server.validate_extensions = _validate_extensions_money_only

# Swap Meet shows OMENZ's own booths at LIVE prices (Bazaar listing data keeps the price from the last settlement; audit 11-21)
swapmeet.OMENZ_PRICES = {"https://www.omenz.org" + k.split(" ", 1)[1]: float(str(v["accepts"]["price"]).lstrip("$")) for k, v in ROUTES.items()}
app = FastAPI(title="OMENZ x402 tollbooth", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
_mw = None


@app.exception_handler(405)
async def _wrong_method(request: Request, exc):
    """Wrong HTTP method: tell the agent the right method, price and an example body instead of a bare 405."""
    path = request.url.path.rstrip("/")
    hits = [(k.split(" ", 1)[0], v) for k, v in ROUTES.items() if k.split(" ", 1)[1] == path]
    body = {"error": "wrong method for this route"}
    allow = getattr(exc, "headers", None) or {}
    if hits:
        m, v = hits[0]
        info = (v.get("extensions") or {}).get("bazaar", {}).get("info", {}).get("input", {})
        body.update({"use_method": m, "price_usd": v["accepts"]["price"], "network": "Base (USDC, x402)",
                     "what_it_does": v.get("description", "")[:300],
                     "example_body" if m == "POST" else "example_query": info.get("body") or info.get("queryParams"),
                     "catalog": BASE, "openapi": "/openapi.json"})
        allow = {"Allow": m}
    return JSONResponse(body, status_code=405, headers=dict(allow))


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
    rid = None
    if path.startswith(BASE + "/v1/"):
        # composability v0 (11-20): one request id + tool name on every response, so agents can chain and cite calls
        rid = "rq_" + os.urandom(8).hex()
        try:
            resp.headers["X-OMENZ-Request-Id"] = rid
            resp.headers["X-OMENZ-Tool"] = path[len(BASE) + 4:].split("?")[0]
            # founder 11-21: every tool carries the survey / needs desk, and why it helps the caller
            resp.headers["X-OMENZ-Feedback"] = ("Tell OMENZ what you need (free): POST /api/tollbooth/v1/needs or https://www.omenz.org/survey/ "
                                                "- recurring needs get built, so your next search finds a working tool faster")
        except Exception:
            pass
    if path.startswith(BASE + "/v1/") or path == BASE + "/swapmeet/v1/search":
        payer = _payer(request)
        ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "tollbooth", "route": path[len(BASE):],
              "method": request.method, "status": resp.status_code, "latency_ms": int((time.time() - t0) * 1000),
              "paid": bool(payer) and resp.status_code < 400, "payer": payer, "price": PRICE_OF.get(path, "free"),
              "ua_class": _ua_class(request.headers.get("user-agent")), "country": request.headers.get("x-vercel-ip-country", ""),
              "request_id": rid, "parent_request_id": (request.headers.get("x-omenz-parent-request-id") or "")[:40] or None,
              **getattr(request.state, "extra", {})}
        if payer and resp.status_code == 402 and request.headers.get("x-payment") and not request.headers.get("payment-signature"):
            # x402 v1 client (X-PAYMENT): the v2 server ignores it silently; tell the buyer how to pay instead (11-20)
            pr = resp.headers.get("payment-required")
            resp = JSONResponse({"x402Version": 2, "error": "x402 v1 X-PAYMENT is not accepted here: this server speaks x402 v2. "
                                 "Read the PAYMENT-REQUIRED header of this 402 and resend the payment in a PAYMENT-SIGNATURE header.",
                                 "docs": "https://www.omenz.org/llms.txt"}, status_code=402, headers={"PAYMENT-REQUIRED": pr} if pr else None)
        if payer and resp.status_code == 402:
            ev["pay_error"] = _pay_error(resp)  # why a sent payment was rejected (added 11-20: funded repeat payers were being turned away)
            ev.update(_pay_shape(request))
        _log(ev)
    return resp


def _pay_shape(request):
    """Which header + x402 version + what the client signed for (amount, payTo, resource), no secrets."""
    for h in ("payment-signature", "x-payment"):
        v = request.headers.get(h)
        if v:
            out = {"pay_header": h}
            try:
                d = json.loads(base64.b64decode(v + "=" * (-len(v) % 4)))
                a = d.get("accepted") or {}
                au = (d.get("payload") or {}).get("authorization") or {}
                out.update({"pay_version": d.get("x402Version"), "pay_scheme": a.get("scheme") or d.get("scheme"),
                            "pay_network": a.get("network") or d.get("network"), "pay_amount": a.get("amount") or au.get("value"),
                            "pay_to": str(a.get("payTo") or au.get("to") or "")[:42],
                            "pay_resource": str((d.get("resource") or {}).get("url") or "")[:200],
                            "pay_valid_before": au.get("validBefore")})
            except Exception:
                out["pay_version"] = "unparsed"
            return out
    return {}


def _pay_error(resp):
    v = resp.headers.get("payment-required") or resp.headers.get("x-payment-required") or ""
    try:
        d = json.loads(base64.b64decode(v + "=" * (-len(v) % 4)))
        return str(d.get("error") or d.get("invalidReason") or "no_reason")[:300]
    except Exception:
        return "unparsed" if v else "no_header"


def _pay_snippet(method, url, price):
    """AYNE -> paid conversion (11-20): a tested x402 v2 snippet at the moment an agent has just seen the sample.
    Verified end to end against OMENZ with an unfunded key (facilitator answered insufficient_funds = it would pay)."""
    call = f's.get("{url}?...")' if method == "GET" else f's.post("{url}", json={{...}})'
    return {"price": price, "network": "Base (USDC)", "account_needed": False,
            "python": ["pip install \"x402[requests,evm]\" eth-account",
                       "from eth_account import Account",
                       "from x402 import x402ClientSync",
                       "from x402.mechanisms.evm.exact import ExactEvmScheme",
                       "from x402.http.clients.requests import x402_requests",
                       "client = x402ClientSync().register(\"eip155:8453\", ExactEvmScheme(Account.from_key(YOUR_WALLET_KEY)))",
                       "s = x402_requests(client)  # pays automatically when it gets a 402",
                       call],
            "safer": "Check a payment first with POST /v1/authorize, or wrap every purchase with omenz-authorize (github.com/OMENZ2026/omenz-authorize)",
            "errors_not_charged": True}


async def _ayne(request, call_next, t0):
    from starlette.concurrency import run_in_threadpool
    path = request.url.path
    sub = path[len(BASE + "/ayne/v1"):] if path.startswith(BASE + "/ayne/v1/") else ""
    method = request.method.upper()
    ua = request.headers.get("user-agent", "")
    vis = ayne.visitor(request.headers.get("x-forwarded-for", "").split(",")[0].strip(), ua)
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": "ayne", "route": sub or "/", "method": method,
          "visitor": vis, "ua_class": _ua_class(ua), "country": request.headers.get("x-vercel-ip-country", "")}
    if sub in ("/market/find", "/market/cheapest") and request.query_params.get("q"):
        ev["need_words"] = market.need_words(request.query_params.get("q"))
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
    limited = key not in ayne.LIVE and key in ayne.LIMITED_LIVE and await run_in_threadpool(ayne.limited_ok, vis, key)
    if key in ayne.LIVE or limited:
        if len(raw) > ayne.MAX_BODY:
            ev.update(mode="too_big")
            await run_in_threadpool(ayne.log, ev)
            return JSONResponse({"error": f"AYNE bodies are limited to {ayne.MAX_BODY} bytes; the paid route takes more", "ayne": True}, status_code=413)
        request.scope["path"] = BASE + "/v1" + sub
        request.scope["raw_path"] = request.scope["path"].encode()
        request.state.ayne = True
        resp = await call_next(request)
        resp.headers["x-ayne"] = "live-limited" if limited else "live"
        ev.update(mode="live", status=resp.status_code)
    elif paid_key in ROUTES:
        fx = ayne.fixtures().get(paid_key) or {}
        resp = JSONResponse({"ayne": True, "sample": True, "note": "Sample response from AYNE. The paid route runs it on your real input.",
                             "paid_route": {"method": method, "url": "https://www.omenz.org" + BASE + "/v1" + sub,
                                            "price": ROUTES[paid_key]["accepts"]["price"]},
                             "description": ROUTES[paid_key]["description"], "example_input": fx.get("example_input"),
                             "sample_response": fx.get("sample_response"),
                             "pay_for_real": _pay_snippet(method, "https://www.omenz.org" + BASE + "/v1" + sub, ROUTES[paid_key]["accepts"]["price"])})
        resp.headers["x-ayne"] = "sample"
        ev.update(mode="sample", status=200)
    else:
        alt = [k.split(" ", 1)[0] for k in ROUTES if k.split(" ", 1)[1] == BASE + "/v1" + sub]
        body = {"ayne": True, "error": "OMENZ doesn't have this yet" if not alt else f"this route takes {', '.join(alt)}",
                "noted": True, "tell_us_what_you_need": BASE + "/v1/needs (free)", "all_routes": BASE + "/ayne/v1"}
        if alt:
            k = alt[0] + " " + BASE + "/v1" + sub
            fx = ayne.fixtures().get(k) or {}
            body.update({"use_method": alt[0], "try_free_here": {"method": alt[0], "url": "https://www.omenz.org" + BASE + "/ayne/v1" + sub,
                         "example_body": fx.get("example_input")}, "paid_route": {"method": alt[0], "url": "https://www.omenz.org" + BASE + "/v1" + sub,
                         "price": ROUTES[k]["accepts"]["price"]}, "description": ROUTES[k]["description"]})
        resp = JSONResponse(body, status_code=404 if not alt else 405)
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


@app.get(BASE + "/swapmeet/v1")
def swapmeet_aisles(request: Request):
    request.state.extra["action"] = "swapmeet_aisles"
    try:
        out = dict(swapmeet.aisles())
    except Exception as e:
        return JSONResponse({"error": "market index unavailable", "detail": str(e)[:120]}, status_code=503)
    # Skins aisle (garage 11-21, queue 0ap): whole jobs pre-equipped, OMENZ's own booth row
    try:
        cat = loadout.catalog()
        pres = sorted(cat.get("presets", []), key=lambda p: (p.get("kind") == "embodied", p.get("name", "")))
        skins = [{"booth": "www.omenz.org", "url": "https://www.omenz.org" + BASE + "/v1/loadout/compile", "method": "POST",
                  "price_usd": float(str(ROUTES[f"POST {BASE}/v1/loadout/compile"]["accepts"]["price"]).lstrip("$")),
                  "what": f"Agent Skin {p['name']}: {p.get('for', '')}"[:160], "networks": ["eip155:8453"], "foot_traffic": "new",
                  "skin_id": p["id"], "kind": p.get("kind"), "appraise": "https://www.omenz.org/skins/"} for p in pres[:12]]
        if skins:
            out["aisles"] = list(out.get("aisles", [])) + [{"id": "skins", "name": "Agent Skins (whole jobs, OMENZ)", "booths": skins,
                                                            "browse": "https://www.omenz.org/skins/", "try_free": BASE + "/ayne/v1/loadout/compile"}]
    except Exception:
        pass
    return out


@app.get(BASE + "/swapmeet/v1/search")
def swapmeet_search(request: Request, q: str = Query("")):
    request.state.extra["action"] = "swapmeet_search"
    request.state.extra["need_words"] = market.need_words(q)
    r = swapmeet.search(q)
    return JSONResponse(r, status_code=422 if "error" in r else 200)


_HOT = {"at": 0, "data": None}


@app.get(BASE + "/swapmeet/v1/hot")
def swapmeet_hot():
    """Free. What's hot this week at the Swap Meet: biggest movers by paying wallets + busy newcomers (snapshot deltas)."""
    if not _HOT["data"] or time.time() - _HOT["at"] > 3600:
        try:
            req = urllib.request.Request(f"https://api.apify.com/v2/key-value-stores/{market.STORE}/records/swapmeet_hot",
                                         headers={"Authorization": "Bearer " + os.environ.get("APIFY_LOG_TOKEN", "")})
            _HOT.update(at=time.time(), data=json.loads(urllib.request.urlopen(req, timeout=15).read()))
        except Exception as e:
            return JSONResponse({"error": "hot list unavailable", "detail": str(e)[:120]}, status_code=503)
    return _HOT["data"]


@app.get(BASE + "/swapmeet/v1/new")
def swapmeet_new():
    return swapmeet.new_arrivals()


@app.post(BASE + "/swapmeet/v1/booth")
def swapmeet_booth(request: Request, body: dict = Body(None)):
    request.state.extra["action"] = "swapmeet_booth"
    code, r = swapmeet.bring_booth(body)
    return JSONResponse(r, status_code=code)


@app.get(BASE + "/myop/v1")
def myop_index():
    return myop.index(BASE)


@app.middleware("http")
async def _myop_ua(request: Request, call_next):
    if "/myop/v1" in request.url.path:
        myop.UA_CLASS.set(_ua_class(request.headers.get("user-agent", "")))
    return await call_next(request)


def _myop(fn, *a):
    try:
        return fn(*a)
    except myop.MyopError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)


@app.post(BASE + "/myop/v1/new/{game}")
def myop_new(game: str, request: Request):
    request.state.extra["action"] = "myop_new"
    return _myop(myop.new, game, BASE)


@app.post(BASE + "/myop/v1/{gid}/note")
def myop_note(gid: str, body: dict = Body(None)):
    return _myop(myop.post_note, gid, body)


@app.get(BASE + "/myop/v1/{gid}/agent")
def myop_agent_view(gid: str, request: Request):
    request.state.extra["action"] = "myop_agent"
    return _myop(myop.agent_view, gid, BASE)


@app.post(BASE + "/myop/v1/{gid}/agent")
def myop_agent_answer(gid: str, body: dict = Body(None)):
    return _myop(myop.agent_answer, gid, body)


@app.post(BASE + "/myop/v1/{gid}/final")
def myop_final(gid: str, body: dict = Body(None)):
    return _myop(myop.final, gid, body)


@app.get(BASE + "/myop/v1/{gid}")
def myop_status(gid: str):
    return _myop(myop.status, gid)


@app.post(BASE + "/v1/needs")
def needs_route(request: Request, body: dict = Body(...)):
    code, r = needs.submit(body, request.headers.get("user-agent"))
    request.state.extra.update({"action": "need", "need_ok": code == 200})
    return JSONResponse(r, status_code=code)


@app.get(BASE + "/v1/conventions")
def conventions_route():
    """Free. How OMENZ tools fit together (composability v0, 11-20)."""
    return {"schema": "omenz.conventions.v0", "price": "free",
            "request_ids": {"response_headers": ["X-OMENZ-Request-Id (rq_...)", "X-OMENZ-Tool"],
                            "chain": "send X-OMENZ-Parent-Request-Id: <rq_ of the previous OMENZ call> to link a workflow (Authorize -> Guard -> Pay -> Checkout close -> Receipt)"},
            "signed_records": {"shape": "omenz.<thing>.v<N> with issuer 'omenz.org' and at/iat (unix seconds)",
                               "signature": "Ed25519; verify offline with GET /v1/passport/key", "kinds": sorted([
                                   "authorization", "attestation", "spend-receipt", "sale-receipt", "settlement-rescue", "dispute-packet",
                                   "purchase-order", "po-redemption", "purchase-snapshot", "refund-request", "evidence-bundle", "contract",
                                   "checkpoint", "checkpoint-receipt", "loadout-install", "action-gate", "handoff"])},
            "id_prefixes": {"az_": "authorization", "po_": "purchase order", "ct_": "contract", "ck_": "checkpoint", "eb_": "evidence bundle",
                            "rr_": "refund request", "li_": "loadout install", "box_": "PO box", "rq_": "request"},
            "outcomes": {"bad_input": "BAD_INPUT (in 'verdict' or 'status'; HTTP 200 or 4xx, never charged on 4xx)",
                         "upstream_down": "UNAVAILABLE", "unknown_not_guessed": "fields we can't back are null, never invented"},
            "money": {"protocol": "x402 v2 (PAYMENT-SIGNATURE); v1 X-PAYMENT gets an explicit upgrade message",
                      "accepted_if": "scheme, network, asset, payTo match and signed amount >= today's price (older 402 copies still work)",
                      "errors_not_charged": True, "pricing_policy": "/v1/pricing-policy"},
            "workflow_examples": [["market/job", "guard", "(pay seller)", "checkout/close", "settlement/rescue if weird"],
                                  ["checkpoint/create", "checkpoint/submit per milestone", "checkpoint/status"],
                                  ["loadout/compile", "passport/issue", "jacket/create", "robot/action-gate per physical step"]]}


@app.get(BASE + "/v1/track-record")
def track_record_route():
    return track_record.build(ROUTES, BASE)


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
                                             b.get("repeat_every_minutes"), b.get("max_attempts", 3), bool(b.get("bidding")),
                                             b.get("jacket_id"), b.get("jacket_fields")),
        "claim": lambda: workforce.claim(q, k, b.get("worker_id"), b.get("jacket_key")),
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
def market_find(request: Request, q: str = Query(""), need: str = Query(""), task: str = Query(""), max_price_usd: float | None = None,
                network: str | None = None, exclude: str | None = None, limit: int = 10, live_check: int = 3, min_payers: int = 0):
    q = (q or need or task).strip()  # 2026-11-16: accept need=/task= (the convention other x402 discovery APIs use)
    if not q:
        return JSONResponse({"error": "describe what you need: q= (or need= / task=)", "example": "/v1/market/find?need=weather forecast by city"}, status_code=422)
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


@app.post(BASE + "/v1/checkpoint/create")
def checkpoint_create(request: Request, body: dict = Body(...)):
    import checkpoint
    request.state.extra["action"] = "checkpoint_create"
    return _locker_call(checkpoint.create, body)


@app.post(BASE + "/v1/checkpoint/submit")
def checkpoint_submit(request: Request, body: dict = Body(...)):
    import checkpoint
    r = _locker_call(checkpoint.submit, body)
    request.state.extra.update({"action": "checkpoint_submit", "verdict": r.get("escrow_verdict") if isinstance(r, dict) else None})
    return r


@app.get(BASE + "/v1/checkpoint/status")
def checkpoint_status(request: Request, id: str = Query(...)):
    import checkpoint
    request.state.extra["action"] = "checkpoint_status"
    return _locker_call(checkpoint.status, id)


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
    sample = [("GET", "local-facts?url=https://www.omenz.org"), ("GET", "alive?url=https://www.omenz.org"), ("POST", "secret-scan"),
              ("GET", "market/find?q=weather"), ("POST", "queue/create"), ("POST", "finance/forecast")]

    def probe(mp):
        m, pth = mp
        r = x402_probe.alive("https://www.omenz.org" + BASE + "/v1/" + pth, m)
        return {"route": m + " /v1/" + pth.split("?")[0], "verdict": r.get("verdict"), "latency_ms": r.get("latency_ms")}
    with ThreadPoolExecutor(6) as ex:
        checks = list(ex.map(probe, sample))
    up = all(c["verdict"] == "paywalled" for c in checks)
    return {"service": "OMENZ x402 tollbooth", "status": "operational" if up else "degraded",
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "paid_routes": len(ROUTES), "facilitator": FACILITATOR_NAME, "sample_checks": checks,
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


@app.get("/.well-known/402index-verify.txt")
def index402_verify():
    """402index.io domain verification (public hash only; the edit token lives in omenz-stack/data/secrets)."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("2fada1cb216de389e3560d4579a52f9f99ad17ac06f2f83d3a0e58ea20911d10")


@app.get("/.well-known/x402list.txt")
def x402list_verify():
    """x402-list.com owner-update domain proof (one-time token, request 8db56da6, 2026-11-19)."""
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("x402list-verify-__hbxBYGCSSMxV92Z0XRTIPY-FX8CQxbn6FIs72LP24\n")


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
# 11-20: free OMENZ tools in MCP too (trust builders); tools/call runs the real free route, not AYNE.
_RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
_MCP_FREE = [
    {"name": "swapmeet_search", "title": "AI Agent Swap Meet search (free)", "_method": "GET", "_free_path": BASE + "/swapmeet/v1/search",
     "description": "Free. Search ~38,000 paid agent services (x402 Bazaar) by what you need; shows busy booths and OMENZ-verified history.",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string", "description": "what you need, e.g. 'token price'"}}, "required": ["q"]}, "annotations": _RO},
    {"name": "omenz_track_record", "title": "OMENZ track record (free)", "_method": "GET", "_free_path": BASE + "/v1/track-record",
     "description": "Free. Test evidence per OMENZ tool plus the earned record of real outside calls, success rates and daily self-probe uptime.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
    {"name": "omenz_loadouts", "title": "Agent Skins + robot loadouts catalog (free)", "_method": "GET", "_free_path": BASE + "/v1/loadouts",
     "description": "Free. Every OMENZ skin (Accountant, Researcher, Sales, Marketing, Customer Service, Purchasing...), department pack and robot job, with the tools and limits each equips.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
    {"name": "omenz_conventions", "title": "How OMENZ tools chain (free)", "_method": "GET", "_free_path": BASE + "/v1/conventions",
     "description": "Free. Request ids and chaining, signed record shapes, id prefixes and payment acceptance rules for composing OMENZ tools into workflows.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _RO},
    {"name": "omenz_tell_us_what_you_need", "title": "Tell OMENZ what you need (free)", "_method": "POST", "_free_path": BASE + "/v1/needs",
     "description": "Free. Tell OMENZ a capability you need and what you'd pay per call; recurring needs get built, tested and listed.",
     "inputSchema": {"type": "object", "properties": {"need": {"type": "string"}, "would_pay_usd_per_call": {"type": "number"}, "frequency": {"type": "string"},
                                                      "current_workaround": {"type": "string"}, "reply_box_id": {"type": "string"}}, "required": ["need"]},
     "annotations": {"readOnlyHint": False, "idempotentHint": False, "openWorldHint": False}},
]


@app.get("/mcp")
@app.get(BASE + "/mcp")  # alias: payapi listing points here
def mcp_get():
    return JSONResponse({"error": "use POST (MCP streamable HTTP, JSON responses)", "server": "OMENZ", "tools": len(ROUTES)}, status_code=405)


@app.post("/mcp")
@app.post(BASE + "/mcp")  # alias: payapi listing points here
async def mcp_post(request: Request):
    import httpx
    from starlette.concurrency import run_in_threadpool
    global _MCP_TOOLS
    if _MCP_TOOLS is None:
        _MCP_TOOLS = discovery.mcp_tools(ROUTES) + _MCP_FREE
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
            path = t["_free_path"] if t.get("_free_path") else BASE + "/ayne/v1" + t["_path"].split("/v1", 1)[1]
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


@app.get(BASE + "/v1/authorize")
def authorize_get(request: Request, url: str = Query(""), method: str = Query("GET"), max_price_usd: float | None = Query(None),
                  expected_pay_to: str | None = Query(None), daily_cap_usd: float | None = Query(None), spent_today_usd: float | None = Query(None)):
    body = {"url": url, "method": method}
    if max_price_usd is not None:
        body["max_price_usd"] = max_price_usd
    if expected_pay_to:
        body["expected_pay_to"] = expected_pay_to
    if daily_cap_usd is not None:
        body["policy"] = {"daily_cap_usd": daily_cap_usd}
    if spent_today_usd is not None:
        body["spend"] = {"spent_today_usd": spent_today_usd}
    return authorize_route(request, body)


@app.get(BASE + "/v1/authorize/verify")
def authorize_verify(token: str = Query("")):
    """FREE: sellers/auditors verify an OMENZ authorization token (Ed25519, key at /v1/passport/key) before serving a paid call."""
    import contracts
    body = contracts._open(token) if token else None
    if not body:
        return JSONResponse({"valid": False, "reason": "bad or missing token (pass ?token=<authorization_token>)"}, status_code=400)
    exp = body.get("expires") or body.get("expires_at") or 0
    live = (not exp) or float(exp) > time.time()
    return {"valid": True, "live": live, "authorization": body,
            "meaning": "OMENZ checked this payment before it was made: decision, url, payTo, amount and expiry are signed by OMENZ.",
            "public_key": "https://www.omenz.org" + BASE + "/v1/passport/key"}


@app.post(BASE + "/v1/split-check")
def split_check_route(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "split_check"
    try:
        r = splits.check(body.get("address"), body.get("network", "base"), body.get("claimed") if isinstance(body.get("claimed"), dict) else None,
                         body.get("beneficiary"))
    except splits.SplitError as e:
        code = 502 if "unavailable" in str(e) else 422
        return JSONResponse({"error": str(e) + ("; not charged" if code == 502 else "")}, status_code=code)
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"error": "claimed must be {recipients: [...], allocations: [...]}"}, status_code=422)
    request.state.extra["verdict"] = r.get("verdict")
    return r


@app.post(BASE + "/v1/credits/buy-{usd}")
def credits_buy(usd: int, request: Request):
    if usd not in (1, 5):
        return JSONResponse({"error": "packs: buy-1 or buy-5"}, status_code=404)
    request.state.extra["action"] = f"credits_buy_{usd}"
    if getattr(request.state, "ayne", False):
        return JSONResponse({"error": "credits can't be bought in AYNE"}, status_code=403)
    return _locker_call(credits.buy, usd)


@app.get(BASE + "/v1/credits/balance")
def credits_balance(request: Request, x_credit_id: str | None = Header(None), x_credit_key: str | None = Header(None)):
    request.state.extra["action"] = "credits_balance"
    return _locker_call(credits.balance, x_credit_id, x_credit_key)


@app.post(BASE + "/v1/authorize/credit")
def authorize_credit(request: Request, body: dict = Body(...), x_credit_id: str | None = Header(None), x_credit_key: str | None = Header(None)):
    request.state.extra["action"] = "authorize_credit"
    try:
        credits._load(x_credit_id, x_credit_key)
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    r = authorize.authorize(body)
    if r.get("decision") == "ERROR":
        return JSONResponse(r, status_code=422)
    fee = credits.authorize_fee((r.get("authorization") or {}).get("amount_usd"))
    try:
        left = credits.charge(x_credit_id, x_credit_key, fee, "authorize " + str(body.get("url"))[:60])
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    request.state.extra.update({"decision": r.get("decision"), "credit_fee": fee})
    return {**r, "billing": {"method": "credits", "fee_usd": fee, "balance_usd": left, "rule": "2% of the authorized payment, minimum $0.0003"}}


@app.get(BASE + "/v1/market/report")
def market_report(request: Request):
    request.state.extra["action"] = "market_report"
    try:
        return market.report()
    except Exception:
        return JSONResponse({"error": "market index unavailable; not charged"}, status_code=502)


@app.get(BASE + "/v1/market/sellers")
def market_sellers(request: Request, q: str | None = None, min_payers: int = 1, limit: int = 100):
    request.state.extra["action"] = "market_sellers"
    try:
        return market.sellers_list(q, min_payers, limit)
    except Exception:
        return JSONResponse({"error": "market index unavailable; not charged"}, status_code=502)


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


@app.post(BASE + "/v1/jacket/create")
def jacket_create(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "jacket_create"
    if getattr(request.state, "ayne", False):
        body = {**body, "ttl_days": 1}
    return _locker_call(jacket.create, body)


@app.post(BASE + "/v1/jacket/checkout")
def jacket_checkout(request: Request, body: dict = Body(None), x_jacket_id: str | None = Header(None), x_jacket_key: str | None = Header(None)):
    request.state.extra["action"] = "jacket_checkout"
    return _locker_call(jacket.checkout, x_jacket_id, x_jacket_key, body)


@app.post(BASE + "/v1/jacket/checkin")
def jacket_checkin(request: Request, body: dict = Body(None), x_jacket_id: str | None = Header(None), x_jacket_key: str | None = Header(None),
                   x_ledger_key: str | None = Header(None)):
    request.state.extra["action"] = "jacket_checkin"
    return _locker_call(jacket.checkin, x_jacket_id, x_jacket_key, body, x_ledger_key)


@app.get(BASE + "/v1/jacket/history")
def jacket_history(request: Request, x_jacket_id: str | None = Header(None), x_jacket_key: str | None = Header(None)):
    return _locker_call(jacket.history, x_jacket_id, x_jacket_key)


@app.get(BASE + "/v1/track-record/rollup")
def track_record_rollup():
    try:
        return track_record.rollup(routes=ROUTES)
    except Exception as e:
        return JSONResponse({"error": "rollup failed", "detail": str(e)[:160]}, status_code=503)


@app.post(BASE + "/v1/send/check")
def send_check_route(request: Request, body: dict = Body(...)):
    import send_check
    request.state.extra["action"] = "send_check"
    r = send_check.check(body)
    request.state.extra["verdict"] = r.get("verdict")
    return r


@app.post(BASE + "/v1/wallet-watch")
def wallet_watch_route(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "wallet_watch"
    return _locker_call(wallet_watch.watch, body.get("address"), body.get("min_usdc"), body.get("min_days"), body.get("pobox_id"), body.get("days", 30))


@app.get(BASE + "/v1/wallet-watch/report")
def wallet_watch_report(request: Request, id: str = Query(""), x_watch_key: str | None = Header(None)):
    request.state.extra["action"] = "wallet_watch_report"
    return _locker_call(wallet_watch.report, id, x_watch_key)


@app.post(BASE + "/v1/uptime/watch")
def uptime_watch(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "uptime_watch"
    days = 1 if getattr(request.state, "ayne", False) else body.get("days", 30)
    return _locker_call(uptime.watch, body.get("url"), body.get("method", "GET"), days)


@app.get(BASE + "/v1/uptime/report")
def uptime_report(request: Request, id: str = Query(""), substitutes: bool = Query(False), x_watch_key: str | None = Header(None)):
    request.state.extra["action"] = "uptime_report"
    return _locker_call(uptime.report, id, x_watch_key, substitutes)


@app.post(BASE + "/v1/budget/create")
def budget_create(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "budget_create"
    return _locker_call(buyer.budget_create, body, 1 if getattr(request.state, "ayne", False) else None)


@app.post(BASE + "/v1/budget/spend")
def budget_spend(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "budget_spend"
    return _locker_call(buyer.budget_spend, body.get("budget_id"), x_budget_key, body)


@app.post(BASE + "/v1/budget/release")
def budget_release(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "budget_release"
    return _locker_call(buyer.budget_release, body.get("budget_id"), x_budget_key, body.get("spend_id"), body.get("reason"))


@app.post(BASE + "/v1/budget/freeze")
def budget_freeze(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    """Free: the owner can always stop the team spending."""
    request.state.extra["action"] = "budget_freeze"
    return _locker_call(buyer.budget_freeze, body.get("budget_id"), x_budget_key, body.get("frozen", True))


@app.get(BASE + "/v1/budget/status")
def budget_status(request: Request, id: str = Query(...), limit: int = 50, x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "budget_status"
    return _locker_call(buyer.budget_status, id, x_budget_key, limit)


@app.post(BASE + "/v1/pay/verify")
def pay_verify(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "pay_verify"
    return buyer.pay_verify(body)


@app.post(BASE + "/v1/checkout/open")
def checkout_open(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "checkout_open"
    return _locker_call(checkout.open_, body, x_budget_key)


@app.post(BASE + "/v1/checkout/close")
def checkout_close(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "checkout_close"
    return _locker_call(checkout.close, body, x_budget_key)


def _credit_checkout(request, fn, body, budget_key, cid, ckey, side):
    try:
        credits._load(cid, ckey)
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    try:
        r = fn(body, budget_key)
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    amt = ((r.get("pay") or {}).get("amount_usd")) if side == "open" else ((r.get("payment") or {}).get("amount_usd"))
    fee = checkout.fee(amt)
    try:
        left = credits.charge(cid, ckey, fee, f"checkout {side}")
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    request.state.extra.update({"credit_fee": fee})
    return {**r, "billing": {"method": "credits", "fee_usd": fee, "balance_usd": left, "rule": "1% of the purchase, minimum $0.0002, per side"}}


@app.post(BASE + "/v1/checkout/open/credit")
def checkout_open_credit(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None),
                         x_credit_id: str | None = Header(None), x_credit_key: str | None = Header(None)):
    request.state.extra["action"] = "checkout_open_credit"
    return _credit_checkout(request, checkout.open_, body, x_budget_key, x_credit_id, x_credit_key, "open")


@app.post(BASE + "/v1/checkout/close/credit")
def checkout_close_credit(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None),
                          x_credit_id: str | None = Header(None), x_credit_key: str | None = Header(None)):
    request.state.extra["action"] = "checkout_close_credit"
    return _credit_checkout(request, checkout.close, body, x_budget_key, x_credit_id, x_credit_key, "close")


@app.get(BASE + "/v1/seller-record")
def seller_record(request: Request, host: str = Query(...)):
    request.state.extra["action"] = "seller_record"
    return _locker_call(checkout.seller_record, host)


@app.get(BASE + "/v1/facilitators")
def facilitators_route(request: Request, network: str | None = None, scheme: str | None = None, x402_version: int | None = None,
                       url: str | None = None):
    request.state.extra["action"] = "facilitators"
    return facilitators.status(network, scheme, x402_version, url)


@app.post(BASE + "/v1/sale/record")
def sale_record_route(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "sale_record"
    return _locker_call(checkout.sale_record, body)


@app.get(BASE + "/v1/tx/decode")
def tx_decode_route(request: Request, tx_hash: str = Query(...)):
    request.state.extra["action"] = "tx_decode"
    return chain_tools.tx_decode(tx_hash)


@app.get(BASE + "/v1/name/resolve")
def name_resolve_route(request: Request, q: str | None = None, name: str | None = None, address: str | None = None,
                       expected_address: str | None = None):
    """0.2.0 (11-22): original q= shape kept; name_check adds MATCH/MISMATCH, Basename reverse, 7702/contract, OFAC, look-alikes."""
    request.state.extra["action"] = "name_resolve"
    q = q or name or address
    if not q:
        return {"status": "BAD_INPUT", "verdict": "BAD_INPUT", "reasons": ["send q (a name like vitalik.eth / jesse.base.eth, or a 0x address)"]}
    is_addr = bool(name_check.ADDR_RE.match(q.strip()))
    base = chain_tools.name_resolve(q)
    try:
        extra = name_check.check(None if is_addr else q, q.strip() if is_addr else None, expected_address)
    except Exception as e:
        extra = {"enrichment_error": type(e).__name__}
    return {**extra, **{k: v for k, v in base.items() if v is not None}, "version": "0.2.0"}


@app.get(BASE + "/v1/weather")
def weather_route(request: Request, lat: str = Query(...), lon: str = Query(...), days: str | None = None):
    request.state.extra["action"] = "weather"
    r = weather.forecast(lat, lon, days)
    if r.get("error") and "unavailable" in r["error"]:
        return JSONResponse(r, status_code=503)
    if r.get("error"):
        return JSONResponse(r, status_code=422)
    return r


@app.get(BASE + "/v1/ip/check")
def ip_check_route(request: Request, ip: str = Query(...)):
    r = ip_check.check(ip)
    request.state.extra.update({"action": "ip_check", "verdict": r.get("verdict")})
    return r


@app.get(BASE + "/v1/fx/convert")
def fx_convert_route(request: Request, amount: str | None = None, date: str | None = None,
                     from_: str = Query("USD", alias="from"), to: str = Query("EUR")):
    request.state.extra["action"] = "fx_convert"
    r = fx_rates.convert(amount, from_, to, date)
    if r.get("error") and "unavailable" in r["error"]:
        return JSONResponse(r, status_code=503)
    return r


@app.post(BASE + "/v1/lead/check")
def lead_check_route(request: Request, body: dict = Body(...)):
    r = lead_check.check(body)
    request.state.extra.update({"action": "lead_check", "verdict": r.get("verdict")})
    return r


@app.get(BASE + "/v1/link/check")
def link_check_route(request: Request, url: str = Query(...)):
    request.state.extra["action"] = "link_check"
    return link_check.check(url)


@app.get(BASE + "/v1/email/check")
def email_check_route(request: Request, email: str = Query(...)):
    request.state.extra["action"] = "email_check"
    return email_check.check(email)


@app.get(BASE + "/v1/phone/check")
def phone_check_route(request: Request, number: str = Query(...), country: str | None = None):
    request.state.extra["action"] = "phone_check"
    return phone_check.check(number, country)


@app.get(BASE + "/v1/domain/check")
def domain_check_route(request: Request, domain: str = Query(...)):
    request.state.extra["action"] = "domain_check"
    return domain_check.check(domain)


@app.get(BASE + "/v1/package/check")
def package_check_route(request: Request, ecosystem: str = Query(...), name: str = Query(...), version: str | None = None):
    request.state.extra["action"] = "package_check"
    return package_check.check(ecosystem, name, version)


@app.get(BASE + "/v1/token/check")
def token_check_route(request: Request, token: str = Query(...)):
    request.state.extra["action"] = "token_check"
    return token_check.check(token)


@app.get(BASE + "/v1/token/balance")
def token_balance_route(request: Request, address: str = Query(...), token: str | None = None):
    request.state.extra["action"] = "token_balance"
    return chain_tools.token_balance(address, token)


@app.get(BASE + "/v1/allowance")
def allowance_route(request: Request, owner: str = Query(...), token: str = Query(...), spender: str = Query(...), intended_usd: float | None = None):
    request.state.extra["action"] = "allowance_check"
    return chain_tools.allowance_check(owner, token, spender, intended_usd)


@app.post(BASE + "/v1/seller/acceptance-check")
async def acceptance_check_route(request: Request):
    from starlette.concurrency import run_in_threadpool
    import acceptance
    request.state.extra["action"] = "seller_acceptance_check"
    try:
        b = await request.json()
    except Exception:
        b = {}
    return await run_in_threadpool(acceptance.check, str(b.get("url") or ""), str(b.get("method") or "GET"))


@app.get(BASE + "/v1/settlement-cost")
def settlement_cost_route(request: Request, amount_usd: float | None = None, payments_per_day: int | None = None):
    request.state.extra["action"] = "settlement_cost"
    return gas.settlement_cost(amount_usd, payments_per_day)


@app.post(BASE + "/v1/guard")
def guard_route(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "guard"
    return _locker_call(guard.guard, body, x_budget_key)


@app.post(BASE + "/v1/guard/credit")
def guard_credit(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None),
                 x_credit_id: str | None = Header(None), x_credit_key: str | None = Header(None)):
    """Value-priced Guard from prepaid credits: max($0.01, 10 bps of the protected value), capped at $5."""
    request.state.extra["action"] = "guard_credit"
    try:
        credits._load(x_credit_id, x_credit_key)
        r = guard.guard(body, x_budget_key)
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    f = guard.fee(r.get("protected_value_usd"))
    try:
        left = credits.charge(x_credit_id, x_credit_key, f, "guard " + str((r.get("pay") or {}).get("url"))[:50])
    except locker.LockerError as e:
        return JSONResponse({"error": e.msg}, status_code=e.status)
    request.state.extra.update({"credit_fee": f, "decision": r.get("decision")})
    return {**r, "billing": {"method": "credits", "fee_usd": f, "balance_usd": left, "rule": "max($0.01, 10 bps of the protected value), cap $5"}}


@app.post(BASE + "/v1/budget/delegate")
def budget_delegate(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "budget_delegate"
    return _locker_call(buyer.budget_delegate, body.get("budget_id"), x_budget_key, body)


@app.post(BASE + "/v1/settlement/rescue")
def settlement_rescue(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "settlement_rescue"
    return rescue.rescue(body)


@app.post(BASE + "/v1/market/job")
def market_job(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "market_job"
    request.state.extra["need_words"] = market.need_words(body.get("need") or body.get("q"))
    return checkout.market_job({**body, "guard": False})


@app.post(BASE + "/v1/market/job/guarded")
def market_job_guarded(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "market_job_guarded"
    request.state.extra["need_words"] = market.need_words(body.get("need") or body.get("q"))
    return _locker_call(checkout.market_job, {**body, "guard": True}, x_budget_key)


@app.get("/.well-known/mcp.json")
def well_known_mcp():
    """MCP discovery card for crawlers and marketplaces that look for /.well-known/mcp.json."""
    return {"name": "org.omenz.www/agent-tools", "title": "OMENZ agent tools",
            "description": "Pay-per-call tools for AI agents that buy things: Transaction Guard, Checkout, Settlement Rescue, Delegation Budget, payment verification, market job desk, facts and more. x402, USDC on Base.",
            "version": "1.0.2", "websiteUrl": "https://omenz.org",
            "remotes": [{"type": "streamable-http", "url": "https://www.omenz.org/mcp"}],
            "tools": len(ROUTES), "playzone": "https://www.omenz.org/api/tollbooth/ayne/v1",
            "x402": "https://www.omenz.org/.well-known/x402", "openapi": "https://www.omenz.org/openapi.json",
            "documentation": "https://www.omenz.org/llms.txt", "registry": "https://registry.modelcontextprotocol.io (org.omenz.www/agent-tools)",
            "contact": "hello@omenz.org"}


@app.post(BASE + "/v1/dispute/packet")
def dispute_packet(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "dispute_packet"
    return _locker_call(dispute.packet, body)


@app.post(BASE + "/v1/po/issue")
def po_issue(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "po_issue"
    return _locker_call(po.issue, body, x_budget_key)


@app.post(BASE + "/v1/po/redeem")
def po_redeem(request: Request, body: dict = Body(...), x_budget_key: str | None = Header(None)):
    request.state.extra["action"] = "po_redeem"
    return _locker_call(po.redeem, body, x_budget_key)


@app.get(BASE + "/v1/loadouts")
def loadouts_catalog(request: Request):
    request.state.extra["action"] = "loadouts_catalog"
    return loadout.catalog()


def _lo_log(request, body, action):
    request.state.extra["action"] = action
    lo, pf = (body or {}).get("loadout"), (body or {}).get("platform")
    request.state.extra["loadout"] = lo if isinstance(lo, str) and lo in loadout.PRESETS else ("custom" if lo else None)
    request.state.extra["platform"] = pf if isinstance(pf, str) and pf in loadout.PLATFORMS else ("custom" if pf else None)


@app.post(BASE + "/v1/loadout/check")
def loadout_check(request: Request, body: dict = Body(...)):
    _lo_log(request, body, "loadout_check")
    r = _locker_call(loadout.check, body)
    if isinstance(r, dict):
        request.state.extra["verdict"] = r.get("verdict")
        request.state.extra["missing_caps"] = (r.get("summary") or {}).get("blocking", [])[:8]
    return r


@app.post(BASE + "/v1/loadout/compile")
def loadout_compile(request: Request, body: dict = Body(...)):
    _lo_log(request, body, "loadout_compile")
    return _locker_call(loadout.compile_, body)


@app.post(BASE + "/v1/loadout/simulate")
def loadout_simulate(request: Request, body: dict = Body(...)):
    _lo_log(request, body, "loadout_simulate")
    return _locker_call(loadout.simulate, body)


@app.post(BASE + "/v1/robot/action-gate")
def robot_action_gate(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "robot_action_gate"
    r = _locker_call(loadout.gate, body)
    if isinstance(r, dict):
        request.state.extra["verdict"] = r.get("decision")
        request.state.extra["cap"] = ((body or {}).get("action") or {}).get("cap") if isinstance((body or {}).get("action"), dict) else None
    return r


@app.get(BASE + "/v1/market/cheapest")
def market_cheapest(request: Request, q: str = Query(...), max_price_usd: float | None = None, network: str | None = None,
                    want: int = 3, min_match: float = 0.75):
    request.state.extra["action"] = "market_cheapest"
    request.state.extra["need_words"] = market.need_words(q)
    return buyer.cheapest_working(q, max_price_usd, network, want, None, min_match)


@app.post(BASE + "/v1/spend-receipt")
def spend_receipt(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "spend_receipt"
    return buyer.spend_receipt(body)


@app.post(BASE + "/v1/delivery-check")
def delivery_check(request: Request, body: dict = Body(...)):
    request.state.extra["action"] = "delivery_check"
    return buyer.delivery_check(body)


@app.get(BASE + "/v1/uptime/run")
def uptime_run():
    try:
        fac = facilitators.snapshot()
    except Exception as e:
        fac = {"error": str(e)[:120]}
    try:
        try:
            ww = wallet_watch.run_due()
        except Exception as e:
            ww = {"error": str(e)[:120]}
        return {**uptime.run_due(), "facilitators": fac, "wallet_watch": ww}
    except Exception as e:
        return JSONResponse({"error": "uptime run failed", "detail": str(e)[:160]}, status_code=503)


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


# doubled_path_fix (2026-11-16): some clients join paths wrongly (e.g. /api/tollbooth/v1/local-facts/api/tollbooth/v1/pobox/inbox,
# about 530 hits in 2 days). Redirect (308 keeps the method + body) to the last /api/tollbooth/ segment so they reach the real route.
from starlette.responses import RedirectResponse  # noqa: E402


@app.middleware("http")
async def doubled_path_fix(request: Request, call_next):
    p = request.url.path
    i = p.rfind("/api/tollbooth/")
    if i > 0 and p.count("/api/tollbooth/") >= 2:
        q = ("?" + request.url.query) if request.url.query else ""
        return RedirectResponse(p[i:] + q, status_code=308)
    return await call_next(request)


# CORS (2026-11-16): browser-based agents send an OPTIONS preflight before POST/custom headers; it was getting 405,
# so they could never reach the paywall. Added last = outermost, so preflight is answered before x402/AYNE.
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "HEAD", "OPTIONS"], allow_headers=["*"],
                   expose_headers=["PAYMENT-REQUIRED", "Payment-Required", "PAYMENT-RESPONSE", "X-PAYMENT-RESPONSE", "x-ayne", "X-OMENZ-Request-Id", "X-OMENZ-Tool", "X-OMENZ-Feedback"], max_age=86400)
