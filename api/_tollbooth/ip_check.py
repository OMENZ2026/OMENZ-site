"""OMENZ IP Check: who is behind this IP address, and is it a person, a server, or an anonymizer? (2026-11-22)

Evidence (11-22 category scan): IP lookup/geolocation x402 services, 425 paying wallets at ~127 calls each (heavy repeat
use: signup screening, fraud checks, rate limiting, log triage). Public, license-clean sources only:
  - owner, network range, country of registration: RDAP (regional internet registries) via rdap.org
  - reverse DNS: Cloudflare DNS-over-HTTPS (PTR)
  - cloud / CDN membership: AWS, Google Cloud, Cloudflare published ranges (bundled, refreshed daily)
  - Tor exit: Tor Project bulk exit list (bundled, refreshed daily)
Country is the REGISTRY country of the network owner, not a street-level location (we don't guess cities).
"""
import gzip
import ipaddress
import os
import time
import urllib.parse

import domain_check

VERSION = "0.1.0"
_B = None


def _bundle():
    global _B
    if _B is None:
        import json
        d = json.load(gzip.open(os.path.join(os.path.dirname(__file__), "ip_ranges.json.gz")))
        nets = {p: [ipaddress.ip_network(c, strict=False) for c in cs] for p, cs in d["providers"].items()}
        _B = {"generated_at": d.get("generated_at"), "nets": nets, "tor": set(d.get("tor_exits") or [])}
    return _B


def _ptr(ip):
    name = ip.reverse_pointer
    d, _ = domain_check._json(f"https://cloudflare-dns.com/dns-query?name={urllib.parse.quote(name)}&type=PTR", {"accept": "application/dns-json"}, 6)
    ans = [a.get("data", "").rstrip(".") for a in (d or {}).get("Answer") or [] if a.get("type") == 12]
    return ans[0] if ans else None


def check(ip):
    out = {"service": "OMENZ IP Check", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "stored": False}
    try:
        a = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return {**out, "verdict": "BAD_INPUT", "reasons": ["send ip (an IPv4 or IPv6 address)"]}
    out["ip"] = str(a)
    if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
        return {**out, "verdict": "PRIVATE_OR_RESERVED", "reasons": ["private/reserved address: not reachable on the public internet, no owner to look up"]}
    b = _bundle()
    provider = next((p for p, nets in b["nets"].items() if any(a in n for n in nets if n.version == a.version)), None)
    tor = str(a) in b["tor"]
    rd, err = domain_check._json(f"https://rdap.org/ip/{a}", timeout=8)
    owner = {}
    if rd:
        owner = {"network_name": rd.get("name"), "handle": rd.get("handle"), "country": rd.get("country"),
                 "range": f"{rd.get('startAddress')} - {rd.get('endAddress')}", "type": rd.get("type")}
        regs = [e for e in rd.get("entities") or [] if "registrant" in (e.get("roles") or [])]
        regs.sort(key=lambda e: (str(e.get("handle") or "").upper().endswith("-MNT"), not str(e.get("handle") or "").upper().startswith("ORG-")))
        for ent in regs[:1]:  # real organisation first; RIPE maintainer handles (-MNT) last
            v = ent.get("vcardArray") or []
            card = v[1] if len(v) > 1 else []
            owner["organization"] = next((x[3] for x in card if x and x[0] == "fn"), None)
            if not owner.get("country"):
                lab = next((x[1].get("label") for x in card if x and x[0] == "adr" and isinstance(x[1], dict) and x[1].get("label")), None)
                if lab:
                    owner["country"] = lab.strip().splitlines()[-1].strip()
        ev = {e.get("eventAction"): e.get("eventDate") for e in rd.get("events") or []}
        owner["registered"] = ev.get("registration")
    ptr = _ptr(a)
    signals = []
    if tor:
        signals.append("Tor exit node: traffic is anonymized; the real user is hidden")
    if provider:
        signals.append(f"{provider.replace('_', ' ')} address: a server or cloud service, usually not a person browsing")
    hosting_words = ("amazon", "google", "microsoft", "azure", "digitalocean", "ovh", "hetzner", "linode", "akamai", "vultr", "oracle", "alibaba", "contabo", "leaseweb", "choopa", "cloudflare", "vercel", "fastly", "netlify", "heroku", "apnic research")
    org_l = " ".join(str(owner.get(k) or "") for k in ("organization", "network_name")).lower()
    hosting = bool(provider) or any(w in org_l for w in hosting_words) or any(w in (ptr or "").lower() for w in ("compute", "cloud", "server", "vps", "host"))
    if hosting and not provider:
        signals.append("owner or reverse DNS looks like a hosting company: likely a server, not a person")
    verdict = "ANONYMIZER" if tor else "DATACENTER" if hosting else "NOT_A_KNOWN_DATACENTER"
    return {**out, "verdict": verdict, "owner": owner or {"note": f"registry lookup unavailable ({err})"}, "reverse_dns": ptr,
            "cloud_provider": provider, "tor_exit": tor, "signals": signals,
            "ranges_as_of": b["generated_at"],
            "limits": "Registry country of the network owner, not a precise location. NOT_A_KNOWN_DATACENTER means home, mobile, business or unlisted hosting; VPNs not listed here are not detected.",
            "next": {"ANONYMIZER": "treat as high risk for signups/payments", "DATACENTER": "likely automated traffic or a server",
                     "NOT_A_KNOWN_DATACENTER": "no anonymizer or cloud signals found"}[verdict]}
