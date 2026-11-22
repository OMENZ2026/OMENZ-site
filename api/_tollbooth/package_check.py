"""OMENZ Package Check: is this software package safe for an agent to install? (2026-11-22)

Evidence: an x402 "package advisories" service had 37 paying wallets at ~85 calls each and growing week over week (repeat
demand from coding agents). Free public sources, no keys: Google deps.dev (existence, versions, deprecation, licenses)
and OSV.dev (known vulnerabilities, fixed versions). Deterministic, read-only.

  BLOCK      package does not exist (hallucinated name = slopsquatting risk) or the version has HIGH/CRITICAL vulns
  CAUTION    deprecated, very new (< 30 days), any known vuln, no license, or the name looks like a popular package
  SAFE_TO_INSTALL  none of the above
"""
import datetime as dt
import json
import time
import urllib.parse
import urllib.request

VERSION = "0.1.0"
SYSTEMS = {"pypi": ("PYPI", "PyPI"), "npm": ("NPM", "npm"), "go": ("GO", "Go"), "cargo": ("CARGO", "crates.io"),
           "maven": ("MAVEN", "Maven"), "nuget": ("NUGET", "NuGet")}
POPULAR = {  # typosquat reference lists (most-installed names); a near-miss of one of these is a classic attack
    "pypi": ["requests", "numpy", "pandas", "urllib3", "boto3", "botocore", "setuptools", "certifi", "idna", "charset-normalizer",
             "python-dateutil", "pyyaml", "typing-extensions", "six", "s3transfer", "cryptography", "pip", "wheel", "packaging",
             "attrs", "jinja2", "markupsafe", "click", "flask", "django", "fastapi", "pydantic", "sqlalchemy", "pytest", "scipy",
             "matplotlib", "pillow", "openai", "anthropic", "langchain", "transformers", "torch", "tensorflow", "selenium",
             "beautifulsoup4", "lxml", "httpx", "aiohttp", "colorama", "tqdm", "web3", "eth-account", "solana", "x402"],
    "npm": ["react", "react-dom", "lodash", "express", "axios", "chalk", "commander", "debug", "moment", "uuid", "typescript",
            "webpack", "next", "vue", "jquery", "dotenv", "body-parser", "cors", "mongoose", "redux", "eslint", "prettier",
            "jest", "mocha", "yargs", "glob", "fs-extra", "request", "async", "underscore", "bluebird", "ethers", "web3", "viem",
            "openai", "@anthropic-ai/sdk", "zod", "socket.io", "nodemon", "dayjs", "colors", "inquirer", "x402"],
}


def _get(url, data=None, timeout=12):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"User-Agent": "OMENZ Package Check", "Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout)), None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, type(e).__name__


def _lev(a, b):
    if abs(len(a) - len(b)) > 2:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _sev(v):
    s = str((v.get("database_specific") or {}).get("severity") or "").upper()
    if s:
        return s
    for a in v.get("affected") or []:
        s = str((a.get("ecosystem_specific") or {}).get("severity") or "").upper()
        if s:
            return s
    return "UNKNOWN"


def _fixed(v, eco):
    out = set()
    for a in v.get("affected") or []:
        if (a.get("package") or {}).get("ecosystem") not in (None, eco):
            continue
        for r in a.get("ranges") or []:
            if r.get("type") == "GIT":  # commit hashes are not installable versions
                continue
            for e in r.get("events") or []:
                if e.get("fixed"):
                    out.add(e["fixed"])
    return sorted(out, key=_vkey)


def _vkey(v):
    """Natural version order (2.20.0 > 2.3.0); non-numeric parts sort after numbers."""
    import re
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"[.\-+]", str(v))]


def check(ecosystem, name, version=None):
    out = {"service": "OMENZ Package Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    eco = str(ecosystem or "").strip().lower()
    name = str(name or "").strip()
    if eco not in SYSTEMS or not name or len(name) > 214:
        return {**out, "verdict": "BAD_INPUT", "reasons": [f"ecosystem must be one of {sorted(SYSTEMS)} and name a package name"]}
    sysk, osv_eco = SYSTEMS[eco]
    qname = name.lower() if eco in ("pypi", "npm") else name
    out.update(ecosystem=eco, name=qname)
    pkg, err = _get(f"https://api.deps.dev/v3/systems/{sysk.lower()}/packages/{urllib.parse.quote(qname, safe='')}")
    if pkg is None and err == 404:
        near = sorted([p for p in POPULAR.get(eco, []) if p != qname and _lev(qname, p) <= 2], key=lambda p: _lev(qname, p))
        return {**out, "verdict": "BLOCK", "exists": False,
                "block": ["package does not exist in the registry: if an AI suggested it, it may be hallucinated, and attackers "
                          "register such names (slopsquatting)" + (f"; did you mean {near[0]}?" if near else "")],
                "caution": [], "passed": []}
    if pkg is None:
        return {**out, "verdict": "UNAVAILABLE", "reasons": [f"registry lookup failed ({err})"]}
    vers = pkg.get("versions") or []
    default = next((v["versionKey"]["version"] for v in vers if v.get("isDefault")), vers[-1]["versionKey"]["version"] if vers else None)
    ver = str(version or default or "")
    first = min((v.get("publishedAt") or "9999" for v in vers), default=None)
    block, caution, passed = [], [], []
    vd, verr = _get(f"https://api.deps.dev/v3/systems/{sysk.lower()}/packages/{urllib.parse.quote(qname, safe='')}/versions/{urllib.parse.quote(ver, safe='')}")
    if vd is None:
        block.append(f"version {ver} not found for {qname}")
        vd = {}
    out.update(exists=True, checked_version=ver, latest_default=default, versions_published=len(vers), first_published=first,
               licenses=vd.get("licenses"))
    if vd.get("isDeprecated"):
        caution.append(f"version {ver} is deprecated" + (f": {vd.get('deprecatedReason')}" if vd.get("deprecatedReason") else ""))
    if vd and not vd.get("licenses"):
        caution.append("no license declared (legal risk for reuse)")
    elif vd.get("licenses"):
        passed.append("license: " + ", ".join(vd["licenses"]))
    if first and first != "9999":
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(first.replace("Z", "+00:00"))).days
        out["package_age_days"] = age
        if age < 30:
            caution.append(f"package is only {age} days old (new packages are where most malware hides)")
        else:
            passed.append(f"package has existed {age} days, {len(vers)} versions published")
    near = [p for p in POPULAR.get(eco, []) if p != qname and _lev(qname, p) <= (1 if len(qname) <= 5 else 2)]
    if near and qname not in POPULAR.get(eco, []):
        caution.append(f"name is one or two letters from the popular package '{near[0]}': make sure this is not a typosquat")
    vulns = []
    if ver and vd:
        o, oerr = _get("https://api.osv.dev/v1/query", {"package": {"name": qname, "ecosystem": osv_eco}, "version": ver})
        if o is None:
            caution.append(f"vulnerability lookup unavailable ({oerr})")
        else:
            for v in (o.get("vulns") or [])[:25]:
                vulns.append({"id": v.get("id"), "summary": (v.get("summary") or "")[:160], "severity": _sev(v), "fixed_in": _fixed(v, osv_eco)[:5]})
    out["vulnerabilities"] = vulns
    hi = [v for v in vulns if v["severity"] in ("HIGH", "CRITICAL")]
    if hi:
        block.append(f"{len(hi)} HIGH/CRITICAL known vulnerabilities in {ver}: " + ", ".join(v["id"] for v in hi[:5]))
    elif vulns:
        caution.append(f"{len(vulns)} known vulnerabilities in {ver} (moderate/low/unrated): " + ", ".join(v["id"] for v in vulns[:5]))
    elif vd:
        passed.append(f"no known vulnerabilities in {ver} (OSV)")
    fixes = sorted({f for v in vulns for f in v["fixed_in"]}, key=_vkey)
    if fixes:
        out["upgrade_to_at_least"] = fixes[-1]
    verdict = "BLOCK" if block else "CAUTION" if caution else "SAFE_TO_INSTALL"
    return {**out, "verdict": verdict, "block": block, "caution": caution, "passed": passed,
            "sources": ["deps.dev", "osv.dev"],
            "limits": "Known issues only: a clean result is not a guarantee the code is safe. Typosquat check covers popular PyPI/npm names.",
            "next": {"SAFE_TO_INSTALL": "ok to install this version", "CAUTION": "read the cautions before installing",
                     "BLOCK": "do not install; fix the reasons (upgrade or correct the name)"}[verdict]}
