"""OMENZ Secret-Leak Preflight: before an agent sends a handoff / prompt / payload outside its boundary, check it
for credentials and private material. Returns CLEAN / BLOCK / REVIEW with where each finding sits.

Born from our own handling rules (keys go through hidden input or Password Drop, never chat or handoffs).
Nothing is stored or logged: the payload is scanned in memory and only redacted previews (first 4 chars) come back.
Deterministic, no AI calls.
"""
import json
import math
import re

VERSION = "0.1.0"
MAX_BYTES = 256 * 1024

# (type, severity, regex). BLOCK = almost certainly a live secret; REVIEW = likely sensitive, a person/agent should look.
PATTERNS = [
    ("private_key_pem", "BLOCK", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    ("aws_access_key_id", "BLOCK", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github_token", "BLOCK", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    ("anthropic_api_key", "BLOCK", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openai_api_key", "BLOCK", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}"),
    ("stripe_secret_key", "BLOCK", r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"),
    ("slack_token", "BLOCK", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("slack_webhook", "BLOCK", r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"),
    ("google_api_key", "BLOCK", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("apify_token", "BLOCK", r"\bapify_api_[A-Za-z0-9]{30,}"),
    ("twilio_key", "BLOCK", r"\bSK[0-9a-f]{32}\b"),
    ("sendgrid_key", "BLOCK", r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
    ("huggingface_token", "BLOCK", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("npm_token", "BLOCK", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("discord_bot_token", "BLOCK", r"\b[MNO][A-Za-z\d_\-]{23,25}\.[A-Za-z\d_\-]{6}\.[A-Za-z\d_\-]{27,38}\b"),
    ("evm_private_key", "BLOCK", r"(?<![0-9a-fA-Fx])(?:0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])"),
    ("db_url_with_password", "BLOCK", r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@/]{3,}@[^\s/]+"),
    ("jwt", "REVIEW", r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ("bearer_token", "REVIEW", r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{24,}"),
    ("password_assignment", "REVIEW", r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)\b[\"']?\s*[:=]\s*[\"']?[^\s\"',;]{6,}"),
    ("credit_card", "REVIEW", r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2}|6011)[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,4}\b"),
    ("us_ssn", "REVIEW", r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
]
COMPILED = [(t, s, re.compile(p)) for t, s, p in PATTERNS]
SEED_HINT = re.compile(r"(?i)\b(seed|mnemonic|recovery|secret)\s*(phrase|words)?\b")
KEY_HINT = re.compile(r"(?i)(priv|secret|key|wallet|signer|mnemonic|seed)[\w\s\"':=]{0,24}$")
EVM_TX_CONTEXT =re.compile(r"(?i)(tx|transaction|hash|block|sha256|digest|checksum|commit)[\w\s\"':=]{0,20}$")


from bip39_words import WORDS as BIP39  # noqa: E402
WORD = re.compile(r"[A-Za-z]+")


def _seed_runs(text):
    """Runs of >=12 consecutive words that are ALL in the BIP-39 list (separated only by spaces/newlines/numbering)."""
    runs, cur, start, last_end = [], 0, None, 0
    for m in WORD.finditer(text):
        gap = text[last_end:m.start()]
        w = m.group(0).lower()
        joined = re.fullmatch(r"[\s\d.,)\-]*", gap) is not None
        if w in BIP39 and (cur == 0 or joined):
            if cur == 0:
                start = m.start()
            cur += 1
        else:
            if cur >= 12:
                runs.append((start, cur))
            cur, start = (1, m.start()) if w in BIP39 else (0, None)
        last_end = m.end()
    if cur >= 12:
        runs.append((start, cur))
    return runs


def _luhn(num):
    d = [int(c) for c in re.sub(r"\D", "", num)][::-1]
    return len(d) >= 13 and sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


def _entropy(s):
    if not s:
        return 0.0
    f = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in f.values())


def _redact(v):
    v = v.strip()
    return (v[:4] + "…" + f"[{len(v)} chars]") if len(v) > 4 else "…"


def _walk(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
            if isinstance(k, str):
                yield f"{path}.<key>", k
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj
    elif obj is not None:
        yield path, str(obj)


def scan(payload):
    if isinstance(payload, (dict, list)):
        size = len(json.dumps(payload, ensure_ascii=False).encode())
        parts = list(_walk(payload))
    else:
        text = payload if isinstance(payload, str) else str(payload)
        size = len(text.encode())
        parts = [("$", text)]
    out = {"version": VERSION, "bytes": size, "stored": False}
    if size > MAX_BYTES:
        return {**out, "verdict": "REVIEW", "findings": [], "note": f"payload over {MAX_BYTES // 1024} KB; not scanned"}
    findings = []
    for path, text in parts:
        for typ, sev, rx in COMPILED:
            for m in rx.finditer(text):
                v = m.group(0)
                if typ == "credit_card" and not _luhn(v):
                    continue
                if typ == "evm_private_key":
                    before = text[max(0, m.start() - 40):m.start()]
                    if EVM_TX_CONTEXT.search(before) or _entropy(v.lower().removeprefix("0x")) < 3.0:
                        continue  # a tx hash / digest, or low-entropy filler
                    key_named = m.start() == 0 and re.search(r"(?i)priv|secret|key|wallet|signer|mnemonic|seed", path.split(".")[-1])
                    if not (KEY_HINT.search(before) or key_named):  # bare 64-hex could be a hash: flag for a look, don't block
                        findings.append({"type": "hex64_unlabeled", "severity": "REVIEW", "path": path, "offset": m.start(),
                                         "preview": _redact(v), "note": "64 hex chars: a wallet private key or just a hash"})
                        continue
                if typ == "openai_api_key" and v.startswith("sk-ant-"):
                    continue
                findings.append({"type": typ, "severity": sev, "path": path, "offset": m.start(), "preview": _redact(v)})
        for start, n in _seed_runs(text):
            hinted = bool(SEED_HINT.search(text[max(0, start - 60):start]))
            findings.append({"type": "recovery_phrase", "severity": "BLOCK", "path": path, "offset": start,
                             "preview": f"[{n} wallet words in a row" + (", labeled as a phrase]" if hinted else "]")})
    # one finding per (path, offset): prefer the more specific/severe type
    seen, uniq = set(), []
    for f in sorted(findings, key=lambda f: (f["path"], f["offset"], f["severity"] != "BLOCK")):
        k = (f["path"], f["offset"])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    verdict = "BLOCK" if any(f["severity"] == "BLOCK" for f in uniq) else "REVIEW" if uniq else "CLEAN"
    counts = {}
    for f in uniq:
        counts[f["type"]] = counts.get(f["type"], 0) + 1
    return {**out, "verdict": verdict, "counts": counts, "findings": uniq[:50],
            "next_action": {"CLEAN": "send", "REVIEW": "check the listed spots before sending",
                            "BLOCK": "remove or rotate the listed secrets before sending"}[verdict],
            "limits": "Pattern-based: catches known key formats, PEM keys, wallet keys, recovery phrases, card numbers and "
                      "password assignments. A secret in an unknown format can pass; CLEAN means none of these were found."}


if __name__ == "__main__":
    import sys
    print(json.dumps(scan(sys.stdin.read()), indent=2))
