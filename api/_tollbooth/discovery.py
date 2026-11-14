"""OMENZ machine discovery: the standard places agents, scanners and registries look on our own domain.

- openapi(routes)        /openapi.json: OpenAPI 3.1 of every paid route, with x-payment-info (x402) per operation.
- well_known_x402(...)   /.well-known/x402: x402 resource list (url, method, price, network, payTo, description).
- agent_card(...)        /.well-known/agent-card.json: A2A agent card (skills = tool families; endpoint = tollbooth; playzone = AYNE).
- MCP                    /mcp: remote MCP server (streamable HTTP, JSON responses). tools/list = every OMENZ tool;
                         tools/call runs through AYNE (free, capped) and returns the paid x402 URL for production use.
"""
import json
import re

ORIGIN = "https://www.omenz.org"
MCP_PROTOCOL = "2025-06-18"
FAMILIES = [
    ("facts", "Local business facts & web checks", ["local-facts", "branch", "agent-ready", "site-check", "changed", "terms-changed", "event-check", "claim-evidence"]),
    ("payments", "Payment safety for machine buyers", ["alive", "quote", "tx-preflight", "spend-gate", "cost-estimate", "finance/"]),
    ("market", "x402 market search & vendor trust", ["market/", "vendor-check", "capability-card"]),
    ("workforce", "Agent employment: work queues, leases, recovery, escalation, bidding", ["queue/"]),
    ("trust", "Permissions, contracts, acceptance, reputation, evidence", ["passport/", "contract/", "reputation", "evidence/", "secret-scan"]),
    ("memory", "Agent state, mailboxes, handoffs, ledgers, failures", ["locker/", "pobox/", "handoff/", "ledger/", "failure/", "receipt/"]),
    ("hygiene", "Data hygiene: freshness, dedupe, context diet, terms/licenses", ["freshness", "dedupe", "context-diet", "terms-extract", "preflight"]),
]


def _split(key):
    m, p = key.split(" ", 1)
    return m, p


def _info(spec):
    return ((spec.get("extensions") or {}).get("bazaar") or {})


def tool_name(path, method):
    n = path.split("/v1/", 1)[1].replace("/", "_").replace("-", "_")
    return n


def openapi(routes, base):
    paths = {}
    for k, v in routes.items():
        m, p = _split(k)
        b = _info(v)
        schema = ((b.get("schema") or {}).get("properties") or {}).get("input", {}).get("properties", {})
        inp = (b.get("info") or {}).get("input") or {}
        op = {"operationId": tool_name(p, m), "summary": v["description"].split(":")[0][:120], "description": v["description"],
              "x-payment-info": {"protocol": "x402", "version": 2, "price": v["accepts"]["price"], "network": v["accepts"]["network"],
                                 "asset": "USDC", "payTo": v["accepts"]["payTo"], "scheme": v["accepts"]["scheme"]},
              "responses": {"200": {"description": "Result (JSON)"}, "402": {"description": "Payment required (x402 v2 'payment-required' header)"},
                            "422": {"description": "Invalid input (not charged)"}}}
        if m == "GET":
            qp = (schema.get("queryParams") or {}).get("properties") or {}
            req = (schema.get("queryParams") or {}).get("required") or []
            ex = inp.get("queryParams") or {}
            op["parameters"] = [{"name": n, "in": "query", "required": n in req, "schema": {"type": (d or {}).get("type", "string")},
                                 **({"example": ex[n]} if n in ex else {})} for n, d in qp.items()]
        else:
            bs = schema.get("body") or {"type": "object"}
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": bs, **({"example": inp["body"]} if inp.get("body") else {})}}}
        paths.setdefault(p, {})[m.lower()] = op
    return {"openapi": "3.1.0",
            "info": {"title": "OMENZ x402 tollbooth", "version": "1.0.0",
                     "description": "Small, tested, pay-per-call tools for AI agents (USDC on Base via x402; no account, no API key). "
                                    f"Free playzone: {ORIGIN}{base}/ayne/v1 . Pricing policy: {ORIGIN}{base}/v1/pricing-policy .",
                     "contact": {"name": "OMENZ", "email": "hello@omenz.org", "url": "https://omenz.org"}},
            "servers": [{"url": ORIGIN}], "paths": paths,
            "x-discovery": {"agent_card": ORIGIN + "/.well-known/agent-card.json", "x402": ORIGIN + "/.well-known/x402",
                            "mcp": ORIGIN + "/mcp", "llms_txt": ORIGIN + "/llms.txt"}}


def well_known_x402(routes, base):
    res = []
    for k, v in routes.items():
        m, p = _split(k)
        res.append({"resource": ORIGIN + p, "method": m, "description": v["description"], "price": v["accepts"]["price"],
                    "network": v["accepts"]["network"], "asset": "USDC", "payTo": v["accepts"]["payTo"], "scheme": v["accepts"]["scheme"],
                    "input": (_info(v).get("info") or {}).get("input")})
    return {"x402Version": 2, "publisher": "OMENZ", "homepage": "https://omenz.org", "resources": res, "count": len(res),
            "playzone": ORIGIN + base + "/ayne/v1", "openapi": ORIGIN + "/openapi.json"}


def agent_card(routes, base):
    skills = []
    for sid, name, keys in FAMILIES:
        tools = [k for k in routes if any(x in k.split(" ", 1)[1] for x in keys)]
        if not tools:
            continue
        prices = sorted({routes[t]["accepts"]["price"] for t in tools}, key=lambda s: float(s.strip("$")))
        skills.append({"id": sid, "name": name, "description": f"{len(tools)} pay-per-call tools ({prices[0]}–{prices[-1]} each).",
                       "tags": [sid, "x402", "pay-per-call"],
                       "examples": [routes[t]["description"].split(":")[0] for t in tools[:3]]})
    return {"name": "OMENZ", "description": "Small, tested, pay-per-call tools for AI agents: facts, payment safety, market search, "
                                            "agent workforce, contracts, memory and data hygiene. x402, USDC on Base.",
            "url": ORIGIN + base, "provider": {"organization": "OMENZ", "url": "https://omenz.org"}, "version": "1.0.0",
            "documentationUrl": ORIGIN + "/llms.txt", "protocolVersion": "0.3.0", "preferredTransport": "HTTP+JSON",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["application/json"], "defaultOutputModes": ["application/json"], "skills": skills,
            "additionalInterfaces": [{"url": ORIGIN + "/mcp", "transport": "MCP (streamable HTTP)"},
                                     {"url": ORIGIN + "/openapi.json", "transport": "OpenAPI 3.1 + x402"}],
            "x-payment": {"protocol": "x402", "asset": "USDC", "network": "eip155:8453", "account_needed": False,
                          "pricing_policy": ORIGIN + base + "/v1/pricing-policy"},
            "x-playzone": {"name": "AYNE", "url": ORIGIN + base + "/ayne/v1", "price": "free", "cap": "2000 requests/day"},
            "x-tell-us": ORIGIN + base + "/v1/needs"}


def mcp_tools(routes):
    tools = []
    for k, v in routes.items():
        m, p = _split(k)
        b = _info(v)
        schema = ((b.get("schema") or {}).get("properties") or {}).get("input", {}).get("properties", {})
        props = (schema.get("queryParams") if m == "GET" else schema.get("body")) or {}
        js = {"type": "object", "properties": props.get("properties") or {}, **({"required": props["required"]} if props.get("required") else {})}
        if "/ledger/" in p or "/queue/" in p:  # header keys travel as arguments over MCP
            key = "x_ledger_key" if "/ledger/" in p else "x_queue_key"
            js["properties"][key] = {"type": "string", "description": "the key returned by create (sent as a header on HTTP)"}
        if "/locker/get" in p:
            js["properties"]["x_locker_key"] = {"type": "string"}
        if "/pobox/inbox" in p:
            js["properties"]["x_owner_key"] = {"type": "string"}
        tools.append({"name": tool_name(p, m), "description": v["description"] + f" (MCP calls run in AYNE, the free playzone; production: {m} {ORIGIN}{p}, {v['accepts']['price']} via x402.)",
                      "inputSchema": js, "_method": m, "_path": p})
    return tools


HEADER_ARGS = {"x_ledger_key": "X-Ledger-Key", "x_queue_key": "X-Queue-Key", "x_locker_key": "X-Locker-Key", "x_owner_key": "X-Owner-Key"}


def rpc_error(id_, code, msg):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": msg}}
