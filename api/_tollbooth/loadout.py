"""OMENZ Loadouts: "what do you want your agent / robot to be able to do right now?"

Founder 2026-11-18/19: Agent Skins (job loadouts that OMENZ keeps up to date) + robot loadouts (HOST MODE for a Saturday
barbecue, PERSONAL TRAINER tomorrow...) + the order to get OMENZ into the third-party robot capability layer.

One provider-neutral spec, omenz.loadout.v0:  HUMAN REQUEST -> LOADOUT -> PLATFORM ADAPTER -> ROBOT CAPABILITIES
  layers: skin, persona, voice, job, tools, workflows, context, permissions, behaviors (+ per-platform adapters here)
  requires: capability words from one shared vocabulary (CAPS), so a loadout never names a vendor API.

Routes (deterministic, no AI calls, OMENZ never touches hardware):
  GET  loadouts                 free   catalog of presets + platform profiles + capability vocabulary
  POST loadout/check            $0.01  loadout x platform -> READY / DEGRADED / NOT_COMPATIBLE, per capability and workflow,
                                       safety-declaration gaps, what the human must confirm
  POST loadout/compile          $0.02  the platform plan (ROS 2 goals for ros-mcp / unitree_sdk2 calls / MCP tool list) +
                                       a signed install receipt (omenz.loadout-install.v0): what was installed, with which limits
  POST loadout/simulate         $0.005 run a workflow in the OMENZ sim home; step trace + gate decision for every step
  POST robot/action-gate        $0.002 before ONE physical action: ALLOW / CONFIRM_FIRST / DENY + signed receipt
Adapter mappings are dry-run plans built from public SDK docs; none is verified on hardware (each says so).
"""
import copy
import hashlib
import json
import time

import contracts
from locker import LockerError

VERSION = "0.1.0"

# ---- capability vocabulary (provider-neutral) ----------------------------------------------------------------------
CAPS = {
    "move.navigate_to": "go to a named place or pose",
    "move.follow": "follow a person at a distance",
    "move.patrol": "walk a route of waypoints",
    "sense.detect_objects": "find objects (cups, plates, trash) in view",
    "sense.detect_people": "know where people are (no identity)",
    "sense.recognize_person": "know WHO someone is (face/voice ID; consent needed)",
    "sense.camera_snapshot": "take a picture",
    "arm.pick": "pick up a small object",
    "arm.place": "put an object down",
    "arm.handover": "hand an object to a person",
    "arm.carry_tray": "carry a tray steadily",
    "speech.say": "speak out loud",
    "speech.listen": "hear and transcribe a request",
    "gesture.wave": "wave hello",
    "gesture.point": "point at something",
    "gesture.demo_exercise": "demonstrate an exercise move",
    "display.show": "show text/image on a screen",
    "home.music": "control music (smart speaker / app)",
    "home.lights": "control lights",
    "notify.owner": "message the owner's phone",
    "timer.count": "count reps / time intervals",
    "safety.estop": "emergency stop the body",
    "safety.speed_limit": "enforce a max speed",
    "sense.battery": "report battery",
}
PHYSICAL = {c for c in CAPS if c.split(".")[0] in ("move", "arm", "gesture")}
CONTACT = {"arm.handover", "move.follow"}
# Agent-side capabilities: served by the agent's own tools (smart-home API, phone notify, scheduler), not the body.
AGENT_SIDE = {"home.music", "home.lights", "notify.owner", "timer.count"}

# ---- platform profiles ----------------------------------------------------------------------------------------------
# native = documented in the vendor's public SDK/stack; addon = needs an extra package/node/service; missing = not there.
P_ROS2 = {
    "id": "ros2-mobile-manipulator", "name": "Generic ROS 2 mobile manipulator (via ros-mcp / rosbridge)",
    "bridge": "rosbridge WebSocket + ros-mcp (MCP server): agent -> MCP -> ROS topics/services/actions",
    "native": {"move.navigate_to": "nav2 action /navigate_to_pose (nav2_msgs/action/NavigateToPose)",
               "move.patrol": "nav2 action /follow_waypoints (nav2_msgs/action/FollowWaypoints)",
               "sense.camera_snapshot": "subscribe sensor_msgs/Image (camera topic)",
               "sense.battery": "subscribe sensor_msgs/BatteryState",
               "safety.speed_limit": "nav2 speed_limit topic (nav2_msgs/SpeedLimit)",
               "safety.estop": "vendor e-stop topic/service (name varies per robot)"},
    "addon": {"arm.pick": "no standard ROS 2 pick interface: needs the robot's MoveIt pick/place server (name varies)",
              "arm.place": "same as arm.pick", "arm.carry_tray": "MoveIt constraint planning (orientation lock)",
              "arm.handover": "custom handover node (rare)", "sense.detect_objects": "vision node (e.g. YOLO -> vision_msgs/Detection2DArray)",
              "sense.detect_people": "people detection node", "speech.say": "TTS node", "speech.listen": "ASR node",
              "move.follow": "person-following node", "gesture.point": "arm pose via MoveIt", "gesture.wave": "scripted arm motion via MoveIt", "display.show": "screen node if fitted"},
    "verified_on_hardware": False,
}
P_G1 = {
    "id": "unitree-g1", "name": "Unitree G1 humanoid (unitree_sdk2 / UniStore)",
    "bridge": "unitree_sdk2 (C++) / unitree_sdk2_python over DDS; store apps via UniStore Developer Center",
    "native": {"move.navigate_to": "LocoClient.Move(vx, vy, vyaw) + your own localization (no built-in named places)",
               "gesture.wave": "LocoClient.WaveHand() / G1ArmActionClient.ExecuteAction(wave)",
               "arm.handover": "G1ArmActionClient preset arm actions (handshake-style); not a grasp",
               "speech.say": "AudioClient.TtsMaker(text)", "sense.camera_snapshot": "head camera stream",
               "sense.battery": "LowState battery fields", "safety.estop": "Damp() / remote e-stop",
               "safety.speed_limit": "cap vx/vy in the adapter (no global limit API assumed)"},
    "addon": {"arm.pick": "dexterous hand + your grasp policy (e.g. a LeRobot/GR00T fine-tune): experimental",
              "arm.place": "same as arm.pick", "arm.carry_tray": "policy needed; high risk",
              "sense.detect_objects": "vision model on the camera stream", "sense.detect_people": "vision model",
              "speech.listen": "mic array + ASR", "move.follow": "people detection + Move()", "move.patrol": "waypoint loop over Move()",
              "gesture.point": "arm action or low-level arm control", "gesture.demo_exercise": "recorded motion clip (UniStore-style action package)"},
    "verified_on_hardware": False,
}
P_GO2 = {
    "id": "unitree-go2", "name": "Unitree Go2 quadruped (unitree_sdk2 SportClient)",
    "bridge": "unitree_sdk2 / unitree_sdk2_python; ros-mcp has a Go2-in-Isaac-Sim demo",
    "native": {"move.navigate_to": "SportClient.Move(vx, vy, vyaw) + localization", "move.follow": "follow mode (model dependent)",
               "gesture.wave": "SportClient.Hello()", "sense.camera_snapshot": "front camera", "sense.battery": "LowState",
               "safety.estop": "SportClient.Damp() / StandDown()", "safety.speed_limit": "SpeedLevel / adapter cap",
               "speech.say": "speaker (VUI / audio, model dependent)"},
    "addon": {"move.patrol": "waypoint loop", "sense.detect_objects": "vision model", "sense.detect_people": "vision model",
              "speech.listen": "mic + ASR"},
    "verified_on_hardware": False,
}
P_SIM = {
    "id": "omenz-sim-home", "name": "OMENZ sim home (2D, deterministic; for testing loadouts without hardware)",
    "bridge": "POST /v1/loadout/simulate", "native": {c: "simulated" for c in CAPS if c != "sense.recognize_person"},
    "addon": {}, "verified_on_hardware": False,
}
P_DIGITAL = {
    "id": "digital-agent-mcp", "name": "Digital agent (MCP / x402 tools, no body)",
    "bridge": "MCP tools/list + x402 routes; permissions via OMENZ Authorize passport",
    "native": {"speech.say": "text reply", "speech.listen": "text input", "display.show": "rich output",
               "notify.owner": "message / email tool", "timer.count": "scheduler", "home.music": "smart-home API tool",
               "home.lights": "smart-home API tool"},
    "addon": {}, "verified_on_hardware": False, "body": False,
}
PLATFORMS = {p["id"]: p for p in (P_ROS2, P_G1, P_GO2, P_SIM, P_DIGITAL)}

# ---- presets --------------------------------------------------------------------------------------------------------
SAFE_HOME = {"max_speed_mps": 0.6, "max_payload_kg": 1.0, "no_go_zones": ["stairs", "pool edge", "grill"],
             "require_human_confirm": ["arm.handover", "move.follow", "sense.camera_snapshot"],
             "forbidden": ["sense.recognize_person"], "contact_with_people": "handover only, never touch"}


def _wf(name, *steps):
    return {"name": name, "steps": [{"cap": s[0], "args": s[1] if len(s) > 1 else {}} for s in steps]}


PRESETS = {
    "host-mode": {
        "schema": "omenz.loadout.v0", "id": "host-mode", "name": "HOST MODE", "kind": "embodied",
        "for": "Help host a backyard barbecue: greet guests, take drink requests, bring cups, clear trash, run the music.",
        "layers": {
            "skin": {"name": "Backyard Host", "look": {"accent_color": "#0aa0ff", "outfit": "apron, where the hardware allows"}},
            "persona": {"tone": "relaxed, funny, polite", "boundaries": ["no alcohol to minors", "no personal questions", "never argues"]},
            "voice": {"style": "warm, short sentences", "greeting": "Welcome! Grab a plate, I'll bring you a drink."},
            "job": {"title": "party host", "goals": ["every guest greeted", "drinks requested -> delivered", "trash cleared"]},
            "tools": ["home.music", "notify.owner"],
            "context": {"jacket_fields": ["menu", "house_rules", "drink_station", "trash_spot", "guest_count"],
                        "note": "Guest names only if guests agree. Kept in an OMENZ Job Jacket, checked back in after the party."},
            "permissions": SAFE_HOME,
            "behaviors": ["greet_at_gate", "drink_run", "trash_sweep", "music_request"],
        },
        "requires": ["move.navigate_to", "speech.say", "speech.listen", "sense.detect_people", "gesture.wave", "safety.estop", "safety.speed_limit"],
        "optional": ["arm.pick", "arm.place", "arm.handover", "arm.carry_tray", "sense.detect_objects", "home.music"],
        "workflows": [
            _wf("greet_at_gate", ("move.navigate_to", {"place": "gate"}), ("sense.detect_people",), ("gesture.wave",), ("speech.say", {"text": "Welcome!"})),
            _wf("drink_run", ("speech.listen",), ("move.navigate_to", {"place": "drink_station"}), ("arm.pick", {"object": "cup"}),
                ("move.navigate_to", {"place": "guest"}), ("arm.handover", {"object": "cup"})),
            _wf("trash_sweep", ("move.navigate_to", {"place": "tables"}), ("sense.detect_objects", {"object": "trash"}),
                ("arm.pick", {"object": "trash"}), ("move.navigate_to", {"place": "trash_spot"}), ("arm.place", {"object": "trash"})),
            _wf("music_request", ("speech.listen",), ("home.music", {"action": "play"}), ("speech.say", {"text": "Turning it up."})),
        ],
    },
    "personal-trainer": {
        "schema": "omenz.loadout.v0", "id": "personal-trainer", "name": "PERSONAL TRAINER", "kind": "both",
        "for": "Lead a home workout: demo moves, count reps, keep time, cheer. Not medical advice.",
        "layers": {"skin": {"name": "Coach", "look": {"accent_color": "#ff6a00"}},
                   "persona": {"tone": "high energy, encouraging", "boundaries": ["no medical or injury advice", "stop on pain"]},
                   "voice": {"style": "short cues"}, "job": {"title": "trainer", "goals": ["session planned", "reps counted", "cool-down"]},
                   "tools": ["timer.count", "home.music"], "context": {"jacket_fields": ["fitness_level", "session_length_min", "avoid_moves"]},
                   "permissions": {**SAFE_HOME, "require_human_confirm": ["gesture.demo_exercise"], "no_go_zones": ["stairs"]},
                   "behaviors": ["warm_up", "set", "cool_down"]},
        "requires": ["speech.say", "speech.listen", "timer.count"],
        "optional": ["gesture.demo_exercise", "display.show", "home.music", "sense.detect_people"],
        "workflows": [_wf("set", ("speech.say", {"text": "10 squats, with me!"}), ("gesture.demo_exercise", {"move": "squat"}),
                          ("timer.count", {"reps": 10}), ("speech.say", {"text": "Nice. Water break."}))],
    },
    "receptionist": {
        "schema": "omenz.loadout.v0", "id": "receptionist", "name": "RECEPTIONIST", "kind": "both",
        "for": "Front desk: greet visitors, answer the business's own FAQ, notify the right person, point the way.",
        "layers": {"skin": {"name": "Front Desk", "look": {"accent_color": "#22c55e"}},
                   "persona": {"tone": "professional, friendly"}, "voice": {"style": "clear"},
                   "job": {"title": "receptionist", "goals": ["visitor greeted", "host notified", "visitor directed"]},
                   "tools": ["notify.owner", "local-facts (OMENZ: the business's own hours/address)"],
                   "context": {"jacket_fields": ["faq", "staff_directory", "visitor_policy"]},
                   "permissions": {**SAFE_HOME, "require_human_confirm": ["sense.camera_snapshot"]}, "behaviors": ["greet", "notify_host"]},
        "requires": ["speech.say", "speech.listen", "notify.owner"], "optional": ["gesture.wave", "gesture.point", "display.show", "sense.detect_people"],
        "workflows": [_wf("greet", ("sense.detect_people",), ("gesture.wave",), ("speech.say", {"text": "Hi, who are you here to see?"}),
                          ("speech.listen",), ("notify.owner", {"text": "Visitor at the front desk"}), ("gesture.point", {"place": "waiting area"}))],
    },
    "security-patrol-observe": {
        "schema": "omenz.loadout.v0", "id": "security-patrol-observe", "name": "SECURITY PATROL (observe + report only)", "kind": "embodied",
        "for": "Walk a route, look, report to the owner. Never confronts, blocks or touches anyone.",
        "layers": {"skin": {"name": "Night Watch"}, "persona": {"tone": "calm"}, "job": {"title": "patrol", "goals": ["route walked", "anomalies reported"]},
                   "tools": ["notify.owner"], "context": {"jacket_fields": ["route", "normal_hours"]},
                   "permissions": {**SAFE_HOME, "forbidden": ["sense.recognize_person", "arm.pick", "arm.handover", "move.follow"],
                                   "contact_with_people": "never"}, "behaviors": ["patrol_loop"]},
        "requires": ["move.patrol", "sense.camera_snapshot", "notify.owner", "safety.estop"], "optional": ["sense.detect_people", "speech.say"],
        "workflows": [_wf("patrol_loop", ("move.patrol", {"route": "perimeter"}), ("sense.detect_people",), ("sense.camera_snapshot",),
                          ("notify.owner", {"text": "Patrol done; snapshot attached"}))],
    },
    "skin-accountant": {
        "schema": "omenz.loadout.v0", "id": "skin-accountant", "name": "ACCOUNTANT skin (digital agent)", "kind": "digital",
        "for": "Put on any agent: books, spend tracking, receipts, forecasts. Bookkeeping help, not tax or legal advice.",
        "layers": {"skin": {"name": "Ledger Pro", "look": {"accent_color": "#0aa0ff", "badge": "OMENZ ACCOUNTANT"}},
                   "persona": {"tone": "precise, plain words"},
                   "job": {"title": "bookkeeper", "goals": ["every spend recorded", "receipts kept", "monthly runway known"]},
                   "tools": ["POST /v1/ledger/create", "POST /v1/ledger/append", "POST /v1/spend-receipt", "POST /v1/finance/forecast",
                             "POST /v1/budget/create", "GET /v1/wallet/runway", "POST /v1/authorize"],
                   "context": {"jacket_fields": ["chart_of_accounts", "fiscal_year", "currency"]},
                   "permissions": {"spend_cap_usd_per_day": 1.0, "require_human_confirm": ["notify.owner"], "forbidden": []},
                   "behaviors": ["record_spend", "month_close"]},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf("month_close", ("display.show", {"what": "ledger totals"}), ("notify.owner", {"text": "Month closed"}))],
    },
    "skin-daycare-starter": {
        "schema": "omenz.loadout.v0", "id": "skin-daycare-starter", "name": "DAYCARE STARTER package (digital agent)", "kind": "digital",
        "for": "Founder example: 'I plan on starting a daycare.' Research jurisdiction rules, organize the paperwork checklist, track costs. Prepares; a licensed human files and signs.",
        "layers": {"skin": {"name": "Business Starter: Daycare"}, "persona": {"tone": "organized"},
                   "job": {"title": "startup assistant", "goals": ["licensing checklist for the city/state", "budget", "document folder"]},
                   "tools": ["POST /v1/claim-evidence", "POST /v1/ledger/create", "POST /v1/finance/forecast", "POST /v1/handoff/pack"],
                   "context": {"jacket_fields": ["city", "state", "capacity_target", "budget_usd"]},
                   "permissions": {"forbidden": ["file_legal_documents", "sign_on_behalf"], "require_human_confirm": ["notify.owner"]},
                   "behaviors": ["research_rules", "checklist", "budget"]},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf("checklist", ("display.show", {"what": "licensing checklist with sources"}), ("notify.owner", {"text": "Checklist ready for review"}))],
    },
    "skin-researcher": {
        "schema": "omenz.loadout.v0", "id": "skin-researcher", "name": "RESEARCHER skin (digital agent)", "kind": "digital",
        "for": 'Find sources, check that they say what you cite, keep results fresh. Research help with receipts, not opinions.',
        "layers": {"skin": {"name": 'Field Researcher', "look": {"accent_color": "#0aa0ff", "badge": 'OMENZ RESEARCHER'}},
                   "persona": {"tone": 'careful, cites everything'},
                   "job": {"title": 'researcher', "goals": ['every claim has a source sentence', 'stale sources refreshed', 'no duplicate work']},
                   "tools": ['GET /v1/market/find', 'POST /v1/claim-evidence', 'GET /v1/freshness', 'GET /v1/changed', 'POST /v1/dedupe', 'POST /v1/context-diet', 'GET /v1/event-check'],
                   "context": {"jacket_fields": ['question', 'deadline', 'allowed_sources']},
                   "permissions": {'spend_cap_usd_per_day': 0.5, 'require_human_confirm': ['notify.owner'], 'forbidden': []},
                   "behaviors": ['source_check', 'refresh']},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf('brief', ("display.show", {"what": 'findings with quoted sources'}), ("notify.owner", {"text": 'Research brief ready'}))],
    },
    "skin-sales-operator": {
        "schema": "omenz.loadout.v0", "id": "skin-sales-operator", "name": "SALES OPERATOR skin (digital agent)", "kind": "digital",
        "for": 'Prospect local businesses: check their sites, pull contact facts, qualify, prepare one-touch outreach for a human to send.',
        "layers": {"skin": {"name": 'Pipeline Builder', "look": {"accent_color": "#0aa0ff", "badge": 'OMENZ SALES OPERATOR'}},
                   "persona": {"tone": 'friendly, brief'},
                   "job": {"title": 'sales operator', "goals": ['qualified prospect list', 'contact facts with sources', 'outreach drafts for human approval']},
                   "tools": ['GET /v1/site-check', 'GET /v1/local-facts', 'GET /v1/agent-ready', 'GET /v1/branch', 'POST /v1/dedupe', 'POST /v1/pobox/drop'],
                   "context": {"jacket_fields": ['territory', 'offer', 'ideal_customer']},
                   "permissions": {'spend_cap_usd_per_day': 1.0, 'require_human_confirm': ['notify.owner', 'send_outreach'], 'forbidden': ['send_without_approval']},
                   "behaviors": ['prospect', 'qualify', 'draft']},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf('pipeline', ("display.show", {"what": 'qualified prospects + drafts'}), ("notify.owner", {"text": 'Prospects ready for your review'}))],
    },
    "skin-marketing-operator": {
        "schema": "omenz.loadout.v0", "id": "skin-marketing-operator", "name": "MARKETING OPERATOR skin (digital agent)", "kind": "digital",
        "for": "Audit how findable a business is, watch competitors' pages for real changes, prep campaign facts. Drafts only; a human publishes.",
        "layers": {"skin": {"name": 'Signal Booster', "look": {"accent_color": "#0aa0ff", "badge": 'OMENZ MARKETING OPERATOR'}},
                   "persona": {"tone": 'clear, on-brand'},
                   "job": {"title": 'marketing operator', "goals": ['agent-readiness score up', 'competitor changes tracked', 'campaign facts verified']},
                   "tools": ['GET /v1/agent-ready', 'GET /v1/site-check', 'GET /v1/changed', 'GET /v1/terms-changed', 'POST /v1/claim-evidence', 'POST /v1/uptime/watch'],
                   "context": {"jacket_fields": ['brand', 'competitors', 'channels']},
                   "permissions": {'spend_cap_usd_per_day': 1.0, 'require_human_confirm': ['notify.owner', 'publish'], 'forbidden': ['publish_without_approval']},
                   "behaviors": ['audit', 'watch', 'draft']},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf('campaign_prep', ("display.show", {"what": 'audit + competitor changes'}), ("notify.owner", {"text": 'Marketing prep ready'}))],
    },
    "skin-customer-service": {
        "schema": "omenz.loadout.v0", "id": "skin-customer-service", "name": "CUSTOMER SERVICE skin (digital agent)", "kind": "digital",
        "for": "Answer from the business's own published facts (hours, address, closures), log every case, hand hard ones to a human.",
        "layers": {"skin": {"name": 'Front Desk', "look": {"accent_color": "#0aa0ff", "badge": 'OMENZ CUSTOMER SERVICE'}},
                   "persona": {"tone": 'warm, exact'},
                   "job": {"title": 'customer service', "goals": ["answers match the business's own site", 'every case logged', 'escalations reach a human']},
                   "tools": ['GET /v1/local-facts', 'GET /v1/branch', 'POST /v1/ledger/append', 'POST /v1/queue/escalate', 'POST /v1/handoff/pack', 'POST /v1/failure/put'],
                   "context": {"jacket_fields": ['business_url', 'escalation_contact', 'policies']},
                   "permissions": {'spend_cap_usd_per_day': 0.5, 'require_human_confirm': ['notify.owner', 'refund'], 'forbidden': ['promise_refunds']},
                   "behaviors": ['answer', 'log', 'escalate']},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf('shift_report', ("display.show", {"what": 'cases handled + escalations'}), ("notify.owner", {"text": 'Shift report ready'}))],
    },
    "skin-purchasing": {
        "schema": "omenz.loadout.v0", "id": "skin-purchasing", "name": "PURCHASING / SHOPPER skin (digital agent)", "kind": "digital",
        "for": 'Buy what the job needs: cheapest working seller, authorize, pay through Guard, verify delivery, keep the receipt. Every spend inside the budget.',
        "layers": {"skin": {"name": 'Smart Buyer', "look": {"accent_color": "#0aa0ff", "badge": 'OMENZ PURCHASING AGENT'}},
                   "persona": {"tone": 'frugal, careful'},
                   "job": {"title": 'purchasing agent', "goals": ['cheapest working seller', 'no duplicate payments', 'receipt for every spend']},
                   "tools": ['GET /v1/market/cheapest', 'POST /v1/market/job', 'POST /v1/authorize', 'POST /v1/guard', 'POST /v1/checkout/open', 'POST /v1/checkout/close', 'POST /v1/settlement/rescue', 'GET /v1/allowance', 'POST /v1/budget/spend'],
                   "context": {"jacket_fields": ['budget_id', 'approved_vendors', 'max_price_usd']},
                   "permissions": {'spend_cap_usd_per_day': 5.0, 'require_human_confirm': ['notify.owner'], 'forbidden': ['spend_over_budget']},
                   "behaviors": ['shop', 'guard', 'receipt']},
        "requires": ["notify.owner"], "optional": ["display.show"],
        "workflows": [_wf('buy', ("display.show", {"what": 'purchase + receipt'}), ("notify.owner", {"text": 'Purchase done, receipt saved'}))],
    },
}

# Department packs (founder handoff 11-20 sec 15/16): several skins + ONE delegation budget (child caps narrow the parent).
PACKS = {
    "pack-finance": {"id": "pack-finance", "name": "FINANCE DEPARTMENT", "members": ['skin-accountant', 'skin-purchasing'],
               "budget": "POST /v1/budget/create (department cap) then POST /v1/budget/delegate per member: a member can never exceed the department"},
    "pack-sales": {"id": "pack-sales", "name": "SALES DEPARTMENT", "members": ['skin-sales-operator', 'skin-researcher'],
               "budget": "POST /v1/budget/create (department cap) then POST /v1/budget/delegate per member: a member can never exceed the department"},
    "pack-marketing": {"id": "pack-marketing", "name": "MARKETING DEPARTMENT", "members": ['skin-marketing-operator', 'skin-researcher'],
               "budget": "POST /v1/budget/create (department cap) then POST /v1/budget/delegate per member: a member can never exceed the department"},
    "pack-small-business": {"id": "pack-small-business", "name": "SMALL BUSINESS PACK", "members": ['skin-accountant', 'skin-sales-operator', 'skin-marketing-operator', 'skin-customer-service', 'skin-purchasing'],
               "budget": "POST /v1/budget/create (department cap) then POST /v1/budget/delegate per member: a member can never exceed the department"},
}


def catalog():
    return {"version": VERSION, "schema": "omenz.loadout.v0",
            "flow": "HUMAN REQUEST -> OMENZ LOADOUT -> PLATFORM ADAPTER -> ROBOT CAPABILITIES",
            "presets": [{"id": p["id"], "name": p["name"], "kind": p["kind"], "for": p["for"], "requires": p["requires"],
                         "optional": p["optional"],
                         "job": ((p.get("layers") or {}).get("job") or {}),
                         "tools": ((p.get("layers") or {}).get("tools") or []),
                         "limits": {k: v for k, v in ((p.get("layers") or {}).get("permissions") or {}).items()
                                    if k in ("spend_cap_usd_per_day", "forbidden", "require_human_confirm", "max_speed_mps", "contact_with_people")}}
                        for p in PRESETS.values()],
            "platforms": [{"id": p["id"], "name": p["name"], "bridge": p["bridge"], "verified_on_hardware": p["verified_on_hardware"]}
                          for p in PLATFORMS.values()],
            "packs": list(PACKS.values()),
            "capabilities": CAPS,
            "routes": {"check": "POST /v1/loadout/check $0.01", "compile": "POST /v1/loadout/compile $0.02",
                       "simulate": "POST /v1/loadout/simulate $0.005", "gate": "POST /v1/robot/action-gate $0.002"},
            "honesty": "Adapter mappings are dry-run plans from public SDK docs; none is verified on hardware. OMENZ never sends commands to a robot."}


# ---- helpers --------------------------------------------------------------------------------------------------------
def _resolve(body):
    lo = body.get("loadout")
    if isinstance(lo, str):
        if lo not in PRESETS:
            raise LockerError(400, f"unknown preset '{lo}'; GET /v1/loadouts lists them")
        lo = copy.deepcopy(PRESETS[lo])
    if not isinstance(lo, dict):
        raise LockerError(400, "loadout: a preset id (e.g. 'host-mode') or an omenz.loadout.v0 object")
    req = [c for c in lo.get("requires") or [] if isinstance(c, str)]
    unknown = [c for c in req + list(lo.get("optional") or []) if c not in CAPS]
    pf = body.get("platform") or "omenz-sim-home"
    if isinstance(pf, str):
        if pf not in PLATFORMS:
            raise LockerError(400, f"unknown platform '{pf}'; GET /v1/loadouts lists them (or send a custom {{native, addon}} manifest)")
        pf = PLATFORMS[pf]
    if not isinstance(pf, dict) or not isinstance(pf.get("native", {}), dict):
        raise LockerError(400, "platform: a profile id or {id, native:{cap: how}, addon:{cap: how}}")
    pf = {"id": str(pf.get("id") or "custom")[:60], "name": pf.get("name") or "custom", "native": pf.get("native") or {},
          "addon": pf.get("addon") or {}, "bridge": pf.get("bridge"), "verified_on_hardware": bool(pf.get("verified_on_hardware")),
          "body": pf.get("body", True) is not False}
    # Bodies: any physical step makes the e-stop required. No body: safety.* and physical steps don't apply.
    caps_all = set(req) | set(lo.get("optional") or [])
    if pf["body"] and caps_all & PHYSICAL and "safety.estop" not in req:
        lo = {**lo, "requires": req + ["safety.estop"]}
    if not pf["body"]:
        lo = {**lo, "requires": [c for c in req if not c.startswith("safety.")],
              "optional": [c for c in lo.get("optional") or [] if not c.startswith("safety.") and c not in PHYSICAL]}
    return lo, pf, unknown


def _status(cap, pf, allow_addons):
    if cap in AGENT_SIDE and cap not in pf["native"]:
        return "native", "agent-side tool (smart-home API / notify / scheduler), works on any body"
    if cap in pf["native"]:
        return "native", pf["native"][cap]
    if cap in pf["addon"]:
        return ("addon" if allow_addons else "addon_needed"), pf["addon"][cap]
    return "missing", None


def _safety_gaps(lo, pf):
    perm = (lo.get("layers") or {}).get("permissions") or {}
    caps = set(lo.get("requires") or []) | set(lo.get("optional") or [])
    gaps = []
    physical = caps & PHYSICAL
    if physical and lo.get("kind") != "digital" and pf.get("body", True):
        if "safety.estop" not in pf["native"]:
            gaps.append("platform shows no e-stop: do not run physical behaviors")
        if "max_speed_mps" not in perm:
            gaps.append("permissions.max_speed_mps not declared")
        if "contact_with_people" not in perm:
            gaps.append("permissions.contact_with_people not declared")
        if not perm.get("no_go_zones"):
            gaps.append("permissions.no_go_zones empty (stairs, pools, stoves?)")
    for c in caps & CONTACT:
        if c not in (perm.get("require_human_confirm") or []):
            gaps.append(f"{c} touches or follows people but is not in require_human_confirm")
    if "sense.recognize_person" in caps and "sense.recognize_person" not in (perm.get("forbidden") or []):
        gaps.append("sense.recognize_person (identity) needs written consent from everyone recognized; OMENZ presets forbid it")
    return gaps


def check(body):
    body = body if isinstance(body, dict) else {}
    lo, pf, unknown = _resolve(body)
    allow_addons = bool(body.get("allow_addons", True))
    caps, blocking, degraded = [], [], []
    for c in lo.get("requires") or []:
        s, how = _status(c, pf, allow_addons)
        caps.append({"cap": c, "required": True, "status": s, "how": how})
        if s in ("missing", "addon_needed"):
            blocking.append(c)
    for c in lo.get("optional") or []:
        s, how = _status(c, pf, allow_addons)
        caps.append({"cap": c, "required": False, "status": s, "how": how})
        if s in ("missing", "addon_needed"):
            degraded.append(c)
    have = {x["cap"] for x in caps if x["status"] in ("native", "addon")}
    wfs = []
    for w in lo.get("workflows") or []:
        miss = sorted({s["cap"] for s in w.get("steps") or [] if s.get("cap") not in have})
        wfs.append({"workflow": w.get("name"), "runnable": not miss, "missing": miss})
    gaps = _safety_gaps(lo, pf)
    addons = [x for x in caps if x["status"] == "addon"]
    verdict = "NOT_COMPATIBLE" if blocking else ("DEGRADED" if degraded or any(not w["runnable"] for w in wfs) else "READY")
    if gaps and verdict == "READY":
        verdict = "READY_WITH_SAFETY_GAPS"
    perm = (lo.get("layers") or {}).get("permissions") or {}
    return {"verdict": verdict, "loadout": lo.get("id") or lo.get("name"), "platform": pf["id"],
            "summary": {"required_ok": len([x for x in caps if x["required"] and x["status"] in ("native", "addon")]),
                        "required_total": len(lo.get("requires") or []), "blocking": blocking, "degraded_optional": degraded,
                        "addons_to_install": [x["cap"] for x in addons]},
            "capabilities": caps, "workflows": wfs, "safety_gaps": gaps,
            "human_must_confirm": perm.get("require_human_confirm") or [], "forbidden": perm.get("forbidden") or [],
            "unknown_capability_words": unknown, "verified_on_hardware": pf["verified_on_hardware"],
            "next": "POST /v1/loadout/compile for the platform plan + signed install receipt; /v1/loadout/simulate to test it; "
                    "call /v1/robot/action-gate before every physical step."}


def _plan_step(step, pf):
    c, a = step.get("cap"), step.get("args") or {}
    how = pf["native"].get(c) or pf["addon"].get(c) or ("agent-side tool" if c in AGENT_SIDE else None)
    if pf["id"] == "ros2-mobile-manipulator":
        if c == "move.navigate_to":
            call = {"via": "ros-mcp send_action_goal", "action": "/navigate_to_pose", "type": "nav2_msgs/action/NavigateToPose",
                    "goal": {"pose": {"header": {"frame_id": "map"}, "pose": f"<pose of '{a.get('place', '?')}' from the jacket's place map>"}}}
        elif c == "move.patrol":
            call = {"via": "ros-mcp send_action_goal", "action": "/follow_waypoints", "type": "nav2_msgs/action/FollowWaypoints",
                    "goal": {"poses": f"<waypoints for route '{a.get('route', '?')}'>"}}
        elif c == "safety.speed_limit":
            call = {"via": "ros-mcp publish", "topic": "/speed_limit", "type": "nav2_msgs/msg/SpeedLimit"}
        else:
            call = {"via": "ros-mcp (topic/service/action)", "how": how}
    elif pf["id"] in ("unitree-g1", "unitree-go2"):
        call = {"via": "unitree_sdk2_python", "how": how, "args": a}
    elif pf["id"] == "digital-agent-mcp":
        call = {"via": "MCP tool / x402 route", "how": how, "args": a}
    else:
        call = {"via": pf.get("bridge") or "adapter", "how": how, "args": a}
    return {"cap": c, "args": a, "call": call, "gate_first": c in PHYSICAL}


def compile_(body):
    body = body if isinstance(body, dict) else {}
    rep = check(body)
    lo, pf, _ = _resolve(body)
    if rep["verdict"] == "NOT_COMPATIBLE" and not body.get("force_plan"):
        return {"compiled": False, "reason": "required capabilities missing on this platform", "check": rep}
    have = {x["cap"] for x in rep["capabilities"] if x["status"] in ("native", "addon")}
    plans = []
    for w in lo.get("workflows") or []:
        plans.append({"workflow": w.get("name"), "runnable": all(s.get("cap") in have for s in w.get("steps") or []),
                      "steps": [_plan_step(s, pf) for s in w.get("steps") or []]})
    perm = (lo.get("layers") or {}).get("permissions") or {}
    now = int(time.time())
    digest = hashlib.sha256(json.dumps(lo, sort_keys=True, default=str).encode()).hexdigest()[:24]
    install = {"schema": "omenz.loadout-install.v0", "install_id": "li_" + hashlib.sha256(f"{digest}{pf['id']}{now}".encode()).hexdigest()[:16],
               "loadout": lo.get("id") or lo.get("name"), "loadout_digest": digest, "platform": pf["id"], "iat": now,
               "exp": now + int(min(float(body.get("valid_hours") or 24), 168) * 3600), "verdict": rep["verdict"],
               "permissions": {k: perm.get(k) for k in ("max_speed_mps", "max_payload_kg", "no_go_zones", "require_human_confirm",
                                                        "forbidden", "contact_with_people", "spend_cap_usd_per_day") if k in perm},
               "allowed_caps": sorted(have - set(perm.get("forbidden") or [])), "issuer": "omenz.org"}
    out = {"compiled": True, "check": {k: rep[k] for k in ("verdict", "summary", "safety_gaps")}, "plans": plans,
           "install_receipt": install, "install_token": contracts._sign(install),
           "verified_on_hardware": pf["verified_on_hardware"],
           "next": "Keep the install_token with the robot/agent; send it to /v1/robot/action-gate before each physical step. "
                   "Context fields go in an OMENZ Job Jacket (POST /v1/jacket/create)."}
    if pf["id"] == "digital-agent-mcp":
        out["mcp"] = {"tools": (lo.get("layers") or {}).get("tools") or [], "passport_request": {
            "POST /v1/passport/issue": {"scope": (lo.get("layers") or {}).get("tools") or [],
                                        "max_usd_per_day": perm.get("spend_cap_usd_per_day", 1.0)}}}
    return out


def gate(body):
    body = body if isinstance(body, dict) else {}
    inst = contracts._open(body.get("install_token")) if body.get("install_token") else None
    if body.get("install_token") and (not inst or inst.get("schema") != "omenz.loadout-install.v0"):
        return {"decision": "DENY", "reasons": ["install_token is not a valid OMENZ install receipt (bad or forged signature)"]}
    if not inst:
        lo, pf, _ = _resolve(body)
        perm = (lo.get("layers") or {}).get("permissions") or {}
        allowed = set(lo.get("requires") or []) | set(lo.get("optional") or [])
        inst = {"install_id": None, "platform": pf["id"], "permissions": perm, "allowed_caps": sorted(allowed), "exp": None}
    act = body.get("action") or {}
    cap, args = act.get("cap"), act.get("args") or {}
    ctx = body.get("context") or {}
    perm = inst.get("permissions") or {}
    reasons, confirm = [], []
    if cap not in CAPS:
        reasons.append(f"unknown capability '{cap}'")
    if inst.get("exp") and time.time() >= inst["exp"]:
        reasons.append("install receipt expired: compile again")
    if cap in (perm.get("forbidden") or []):
        reasons.append(f"{cap} is forbidden by this loadout")
    elif cap not in (inst.get("allowed_caps") or []):
        reasons.append(f"{cap} is not part of this loadout")
    if cap in PHYSICAL:
        if ctx.get("estop_ok") is False:
            reasons.append("e-stop not confirmed working")
        sp = args.get("speed_mps", ctx.get("speed_mps"))
        if sp is not None and perm.get("max_speed_mps") is not None and float(sp) > float(perm["max_speed_mps"]):
            reasons.append(f"speed {sp} m/s above the loadout limit {perm['max_speed_mps']}")
        kg = args.get("payload_kg")
        if kg is not None and perm.get("max_payload_kg") is not None and float(kg) > float(perm["max_payload_kg"]):
            reasons.append(f"payload {kg} kg above the limit {perm['max_payload_kg']}")
        zone = str(args.get("place") or ctx.get("zone") or "").lower()
        if zone and any(z.lower() in zone for z in perm.get("no_go_zones") or []):
            reasons.append(f"'{zone}' is a no-go zone")
        if ctx.get("children_present") and cap in CONTACT | {"arm.carry_tray"}:
            confirm.append("children present: an adult confirms this step")
        if ctx.get("person_within_m") is not None and float(ctx["person_within_m"]) < 0.5 and cap.startswith("move."):
            confirm.append("a person is closer than 0.5 m")
    if cap in (perm.get("require_human_confirm") or []) and not ctx.get("human_confirmed"):
        confirm.append(f"{cap} needs a human yes for this step")
    decision = "DENY" if reasons else ("CONFIRM_FIRST" if confirm else "ALLOW")
    rec = {"schema": "omenz.action-gate.v0", "decision": decision, "cap": cap, "install_id": inst.get("install_id"),
           "platform": inst.get("platform"), "at": int(time.time()), "reasons": reasons + confirm}
    return {"decision": decision, "reasons": reasons, "confirm": confirm, "receipt": rec, "signed_receipt": contracts._sign(rec),
            "note": "OMENZ decides and signs; the robot's own safety system still has the last word."}


# ---- sim home -------------------------------------------------------------------------------------------------------
PLACES = {"gate": (0, 0), "drink_station": (6, 2), "guest": (4, 6), "tables": (3, 4), "trash_spot": (8, 0), "grill": (7, 5),
          "front desk": (1, 1), "waiting area": (2, 3), "perimeter": (0, 8), "stairs": (9, 9)}


def simulate(body):
    body = body if isinstance(body, dict) else {}
    lo, pf, _ = _resolve({**body, "platform": body.get("platform") or "omenz-sim-home"})
    comp = compile_({**body, "loadout": lo, "platform": pf})
    if not comp.get("compiled"):
        return {"ran": False, **comp}
    names = [w.get("name") for w in lo.get("workflows") or []]
    want = body.get("workflow") or (names[0] if names else None)
    wf = next((w for w in lo.get("workflows") or [] if w.get("name") == want), None)
    if not wf:
        raise LockerError(400, f"workflow '{want}' not in this loadout ({names})")
    ctx = dict(body.get("context") or {})
    pos, held, t, trace, blocked = (0.0, 0.0), None, 0.0, [], False
    for i, s in enumerate(wf.get("steps") or []):
        cap, a = s.get("cap"), s.get("args") or {}
        g = gate({"install_token": comp["install_token"], "action": {"cap": cap, "args": a}, "context": ctx})
        entry = {"step": i, "cap": cap, "args": a, "gate": g["decision"], "reasons": g["reasons"] + g["confirm"]}
        if g["decision"] == "DENY" or (g["decision"] == "CONFIRM_FIRST" and not body.get("auto_confirm")):
            entry["result"] = "stopped: " + ("denied" if g["decision"] == "DENY" else "waiting for a human yes (send auto_confirm=true to simulate the yes)")
            trace.append(entry)
            blocked = True
            break
        if cap == "move.navigate_to":
            dest = PLACES.get(str(a.get("place")), (5, 5))
            d = ((dest[0] - pos[0]) ** 2 + (dest[1] - pos[1]) ** 2) ** 0.5
            sp = min(float((lo["layers"].get("permissions") or {}).get("max_speed_mps") or 0.6), 0.6)
            t += d / sp
            pos = dest
            entry["result"] = f"at {a.get('place')} {dest} after {d:.1f} m"
        elif cap == "arm.pick":
            held = a.get("object")
            t += 4
            entry["result"] = f"holding {held}"
        elif cap in ("arm.place", "arm.handover"):
            entry["result"] = f"released {held or a.get('object')}"
            held = None
            t += 3
        else:
            t += 2
            entry["result"] = "ok (simulated)"
        entry["t_s"] = round(t, 1)
        trace.append(entry)
    return {"ran": True, "loadout": lo.get("id"), "workflow": want, "completed": not blocked, "sim_seconds": round(t, 1),
            "trace": trace, "check_verdict": comp["check"]["verdict"],
            "note": "Deterministic 2D sim: shows the plan, the gate on every step and where a human must say yes. Not physics."}
