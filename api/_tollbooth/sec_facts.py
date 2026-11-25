"""OMENZ SEC Facts: a US public company's key reported numbers, straight from its own SEC filings.

Research dept brief 2026-11-24 (tool-stock-equities): 'stock / equities' = 1,639 payers/30d, 263 sellers, median $0.01,
but real-time quotes and vendor fundamentals carry redistribution licensing blockers. The clean lane is SEC EDGAR
(public US government data) + arithmetic we compute ourselves, with provenance on every number.

Input: ticker (or a numeric CIK). Output: company profile (name, CIK, SIC/industry), latest fiscal-year and
latest-quarter figures (revenue, net income, diluted EPS, total assets, total liabilities, cash, shares outstanding,
operating cash flow), each with period end, form, filed date, accession and the XBRL tag used; computed metrics
(YoY revenue growth, net margin, debt-to-assets) labeled as computed; the latest 10 filings with links; a freshness
note. Not a price quote, not investment advice. Deterministic, no AI calls.
SEC fair access: identified User-Agent with contact, <=~9 requests/s per process, company_tickers.json cached,
results cached 15 minutes per company, whole call bounded to ~18 s.
"""
import gzip
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import date

import event_check  # shares the company_tickers.json cache (garage reuse: GET /v1/event-check)

VERSION = "0.1.0"
UA = {"User-Agent": "OMENZ hello@omenz.org", "Accept-Encoding": "gzip", "Accept": "application/json"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
BUDGET_S = 18.0
MIN_GAP_S = 0.11           # SEC asks for <10 requests/second
RESULT_TTL_S = 900
TICKER_TTL_S = 86400
NOTICE = ("Not a price quote and not investment advice: these are figures the company reported in its SEC filings, "
          "plus simple arithmetic OMENZ computed from them.")

# metric -> [(taxonomy, concept, unit), ...] in priority order; the concept with the most recent period wins
CONCEPTS = {
    "revenue": [("us-gaap", "Revenues", "USD"), ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
                ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax", "USD"), ("us-gaap", "SalesRevenueNet", "USD"),
                ("us-gaap", "SalesRevenueGoodsNet", "USD"), ("us-gaap", "RevenuesNetOfInterestExpense", "USD"),
                ("ifrs-full", "Revenue", None)],
    "net_income": [("us-gaap", "NetIncomeLoss", "USD"), ("us-gaap", "ProfitLoss", "USD"),
                   ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic", "USD"), ("ifrs-full", "ProfitLoss", None)],
    "eps_diluted": [("us-gaap", "EarningsPerShareDiluted", "USD/shares"), ("us-gaap", "EarningsPerShareBasicAndDiluted", "USD/shares"),
                    ("ifrs-full", "DilutedEarningsLossPerShare", None)],
    "total_assets": [("us-gaap", "Assets", "USD"), ("ifrs-full", "Assets", None)],
    "total_liabilities": [("us-gaap", "Liabilities", "USD"), ("ifrs-full", "Liabilities", None)],
    "cash": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"),
             ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "USD"), ("us-gaap", "Cash", "USD"),
             ("ifrs-full", "CashAndCashEquivalents", None)],
    "shares_outstanding": [("dei", "EntityCommonStockSharesOutstanding", "shares"), ("us-gaap", "CommonStockSharesOutstanding", "shares")],
    "operating_cash_flow": [("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD"),
                            ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", "USD"),
                            ("ifrs-full", "CashFlowsFromUsedInOperatingActivities", None)],
}
INSTANT = {"total_assets", "total_liabilities", "cash", "shares_outstanding"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT", "10-KT/A"}
QUARTER_FORMS = {"10-Q", "10-Q/A", "6-K"}
KEY_FORMS = ["10-K", "10-Q", "8-K", "20-F", "6-K", "DEF 14A", "S-1", "424B4"]

_lock = threading.Lock()
_last = [0.0]
_results = {}


class _Busy(Exception):
    pass


def _get(url, deadline):
    left = deadline - time.time()
    if left < 1.0:
        raise TimeoutError("time budget used up")
    with _lock:
        wait = _last[0] + MIN_GAP_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=min(12.0, left)) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding", "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            raise _Busy(str(e.code))
        raise


def _tickers(deadline):
    if event_check._tickers is not None:
        return event_check._tickers
    path = os.path.join(tempfile.gettempdir(), "omenz_sec_company_tickers.json")
    try:
        if time.time() - os.path.getmtime(path) < TICKER_TTL_S:
            with open(path, encoding="utf-8") as f:
                event_check._tickers = list(json.load(f).values())
                return event_check._tickers
    except (OSError, ValueError):
        pass
    raw = _get(TICKERS_URL, deadline)
    data = json.loads(raw)
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError:
        pass
    event_check._tickers = list(data.values())
    return event_check._tickers


def _find(q, deadline):
    rows = _tickers(deadline)
    if q.isdigit():
        n = int(q)
        hit = next((t for t in rows if int(t["cik_str"]) == n), None)
        return hit or {"cik_str": n, "ticker": None, "title": None}
    variants = [q, q.replace(".", "-"), q.replace("-", "."), q.replace(".", ""), q.replace("/", "-")]
    for v in variants:
        for t in rows:
            if t["ticker"].upper() == v:
                return t
    return None


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _series(facts, metric):
    """[(tag, unit, entries)] for every candidate concept the company actually reports."""
    out = []
    for tax, concept, unit in CONCEPTS[metric]:
        node = (facts.get(tax) or {}).get(concept)
        if not node:
            continue
        units = node.get("units") or {}
        if unit:
            if units.get(unit):
                out.append((f"{tax}:{concept}", unit, units[unit]))
        else:  # IFRS filers: every currency unit (USD first); the latest period wins in _pick (per-share units for EPS)
            pool = sorted((k for k in units if (metric == "eps_diluted") == ("/" in k) and units[k]), key=lambda k: not k.startswith("USD"))
            out.extend((f"{tax}:{concept}", k, units[k]) for k in pool)
    return out


def _kind(e, metric):
    """'annual' | 'quarter' | 'ytd' | 'instant' | None for one fact entry."""
    if metric in INSTANT:
        return "instant"
    if not e.get("start"):
        return None
    d = _days(e["start"], e["end"])
    if 350 <= d <= 380:
        return "annual"
    if 80 <= d <= 100:
        return "quarter"
    if 170 <= d <= 280:
        return "ytd"
    return None


def _pick(facts, metric, basis):
    """Latest fact for metric. basis 'annual' = from 10-K-type forms, 'quarter' = from 10-Q-type forms."""
    forms = ANNUAL_FORMS if basis == "annual" else QUARTER_FORMS
    best = None
    for tag, unit, entries in _series(facts, metric):
        cand = []
        for e in entries:
            if e.get("form") not in forms or not e.get("end"):
                continue
            k = _kind(e, metric)
            if basis == "annual" and k not in ("annual", "instant"):
                continue
            if basis == "quarter" and k not in ("quarter", "ytd", "instant"):
                continue
            cand.append((e["end"], k == "quarter" or k == "instant", e.get("filed", ""), e, k))
        if not cand:
            continue
        end = max(c[0] for c in cand)
        same = [c for c in cand if c[0] == end]
        # prefer the true 3-month value over year-to-date, then the most recently filed (restated) number
        same.sort(key=lambda c: (c[1], c[2]))
        _, _, _, e, k = same[-1]
        row = (end, tag, unit, e, k)
        if best is None or end > best[0]:
            best = row
    if not best:
        return None
    end, tag, unit, e, k = best
    r = {"value": e["val"], "unit": unit, "period_end": end, "form": e.get("form"), "filed": e.get("filed"),
         "accession": e.get("accn"), "xbrl_tag": tag}
    if e.get("start"):
        r["period_start"] = e["start"]
        r["period_days"] = _days(e["start"], end)
    if k == "ytd":
        r["basis"] = "year_to_date"
        r["note"] = "the filing reports this only as a fiscal year-to-date total, not a single quarter"
    elif k == "quarter":
        r["basis"] = "three_months"
    elif k == "annual":
        r["basis"] = "fiscal_year"
    else:
        r["basis"] = "as_of_date"
    return r


def _prior(facts, metric, cur):
    """Same-length period ending ~1 year before cur (same XBRL tag first), most recently filed value."""
    if not cur or not cur.get("period_start"):
        return None
    want = cur["period_days"]
    tags = [cur["xbrl_tag"]] + [f"{t}:{c}" for t, c, _ in CONCEPTS[metric] if f"{t}:{c}" != cur["xbrl_tag"]]
    series = {(tag, unit): entries for tag, unit, entries in _series(facts, metric)}
    for tag in tags:
        entries = series.get((tag, cur["unit"]))
        if not entries:
            continue
        hits = []
        for e in entries:
            if not e.get("start") or not e.get("end"):
                continue
            gap = _days(e["end"], cur["period_end"])
            if 330 <= gap <= 400 and abs(_days(e["start"], e["end"]) - want) <= 10:
                hits.append(e)
        if hits:
            # closest to one year back, then the most recently filed (restated) value
            e = max(hits, key=lambda x: (-abs(_days(x["end"], cur["period_end"]) - 364), x.get("filed", "")))
            return {"value": e["val"], "period_start": e["start"], "period_end": e["end"], "form": e.get("form"),
                    "filed": e.get("filed"), "accession": e.get("accn"), "xbrl_tag": tag}
    return None


def _ratio(n, d, digits=4):
    try:
        if n is None or d in (None, 0):
            return None
        return round(n / d, digits)
    except (TypeError, ZeroDivisionError):
        return None


def _computed(facts, fy, q):
    out = {"label": "COMPUTED by OMENZ from the reported figures in this response; not numbers the company reported"}
    for basis, block in (("annual", fy), ("quarter", q)):
        f = (block or {}).get("figures") or {}
        rev, ni, ta, tl = (f.get(k) for k in ("revenue", "net_income", "total_assets", "total_liabilities"))
        # growth: only a like-for-like period (fiscal year vs prior year, or 3 months vs the same 3 months a year ago)
        if rev and rev.get("basis") in ("fiscal_year", "three_months"):
            p = _prior(facts, "revenue", rev)
            g = _ratio(rev["value"] - p["value"], abs(p["value"]), 6) if p and p["value"] else None
            out[f"revenue_growth_yoy_{basis}"] = {"value": g, "percent": None if g is None else round(g * 100, 2),
                                                  "formula": "(revenue - revenue same period prior year) / |prior|",
                                                  "current_period_end": rev["period_end"], "prior": p}
        else:
            out[f"revenue_growth_yoy_{basis}"] = None
        same = rev and ni and rev.get("period_end") == ni.get("period_end") and rev.get("period_days") == ni.get("period_days")
        nm = _ratio(ni["value"], rev["value"]) if same else None
        out[f"net_margin_{basis}"] = None if nm is None else {
            "value": nm, "percent": round(nm * 100, 2), "formula": "net_income / revenue (same period)", "period_end": rev["period_end"]}
        same_bs = ta and tl and ta.get("period_end") == tl.get("period_end")
        da = _ratio(tl["value"], ta["value"]) if same_bs else None
        out[f"debt_to_assets_{basis}"] = None if da is None else {
            "value": da, "formula": "total_liabilities / total_assets (ALL liabilities, not only interest-bearing debt)",
            "as_of": ta["period_end"]}
    return out


def _block(facts, basis):
    figs = {m: _pick(facts, m, basis) for m in CONCEPTS}
    ends = [v["period_end"] for k, v in figs.items() if v and k != "shares_outstanding"]
    if not ends:
        return None
    ref = max(ends)
    # a tag the company stopped using leaves an old "latest" value (e.g. cover-page shares last tagged in 2011): skip it
    limit = 400 if basis == "annual" else 200
    stale = {}
    for k, v in figs.items():
        if v and _days(v["period_end"], ref) > limit:
            stale[k] = {"period_end": v["period_end"], "xbrl_tag": v["xbrl_tag"]}
            figs[k] = None
    missing = [k for k, v in figs.items() if v is None]
    blk = {"period_end": ref, "figures": figs, "not_reported": missing or None, "skipped_stale": stale or None}
    if "shares_outstanding" in missing:
        blk["shares_note"] = ("companies with several share classes tag cover-page shares per class, which SEC's companyfacts "
                              "API leaves out; read the cover page of the filing linked in key_filings")
    return blk


def _filings(sub, cik):
    r = (sub.get("filings") or {}).get("recent") or {}
    forms = r.get("form") or []
    n = len(forms)
    col = lambda k: r.get(k) or [""] * n  # noqa: E731
    acc, filed, rep, doc, desc = col("accessionNumber"), col("filingDate"), col("reportDate"), col("primaryDocument"), col("primaryDocDescription")
    rows = []
    for i in range(n):
        a = acc[i]
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{a.replace('-', '')}/"
        rows.append({"form": forms[i], "filed": filed[i], "report_date": rep[i] or None, "accession": a,
                     "description": desc[i] or None, "url": base + doc[i] if doc[i] else base,
                     "index_url": base + f"{a}-index.htm"})
    key = {}
    for f in KEY_FORMS:
        hit = next((x for x in rows if x["form"] == f), None)
        if hit:
            key[f] = {k: hit[k] for k in ("filed", "report_date", "url")}
    return rows[:10], key


def check(ticker):
    t0 = time.time()
    deadline = t0 + BUDGET_S
    q = re.sub(r"\s+", "", str(ticker or "")).upper()[:12]
    out = {"service": "OMENZ SEC Facts", "version": VERSION, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "query": q, "source": "SEC EDGAR (XBRL companyfacts + submissions), public US government data; no exchange or vendor data",
           "notice": NOTICE}
    if not q or not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-/]{0,11}", q):
        return {**out, "status": "ERROR", "error": "ticker is required: a US-listed ticker like AAPL or BRK.B, or a numeric SEC CIK"}
    try:
        c = _find(q, deadline)
    except _Busy:
        return {**out, "status": "ERROR", "error": "SEC is rate-limiting right now; retry in a minute", "retry_after_s": 60}
    except Exception as e:
        return {**out, "status": "ERROR", "error": f"SEC ticker lookup failed ({type(e).__name__}); try again"}
    if not c:
        return {**out, "status": "ERROR", "error": "NOT_FOUND: no SEC registrant uses that ticker. Private and most non-US companies, "
                "OTC names without SEC filings, and delisted tickers are not in SEC's ticker map; try the numeric CIK"}
    cik = str(c["cik_str"]).zfill(10)
    hit = _results.get(cik)
    if hit and time.time() - hit[0] < RESULT_TTL_S:
        return {**hit[1], "query": q, "checked_at": out["checked_at"], "cached_for_s": int(time.time() - hit[0])}
    src = {"submissions": f"https://data.sec.gov/submissions/CIK{cik}.json",
           "companyfacts": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"}
    out["source_urls"] = src
    try:
        sub = json.loads(_get(src["submissions"], deadline))
    except _Busy:
        return {**out, "status": "ERROR", "error": "SEC is rate-limiting right now; retry in a minute", "retry_after_s": 60}
    except urllib.error.HTTPError as e:
        return {**out, "status": "ERROR", "error": f"NOT_FOUND: SEC has no filer record for CIK {cik} (HTTP {e.code})"}
    except Exception as e:
        return {**out, "status": "ERROR", "error": f"SEC filings fetch failed ({type(e).__name__}); try again"}
    out["company"] = {"name": sub.get("name") or c.get("title"), "cik": cik, "tickers": sub.get("tickers") or ([c["ticker"]] if c.get("ticker") else []),
                      "exchanges": sub.get("exchanges") or [], "sic": sub.get("sic") or None, "industry": sub.get("sicDescription") or None,
                      "fiscal_year_end_mmdd": sub.get("fiscalYearEnd") or None, "state_of_incorporation": sub.get("stateOfIncorporation") or None,
                      "filer_category": sub.get("category") or None, "entity_type": sub.get("entityType") or None}
    latest, key = _filings(sub, cik)
    out["latest_filings"] = latest
    out["key_filings"] = key
    try:
        cf = json.loads(_get(src["companyfacts"], deadline))
    except _Busy:
        return {**out, "status": "ERROR", "error": "SEC is rate-limiting right now; retry in a minute", "retry_after_s": 60}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {**out, "status": "ERROR", "error": "NO_XBRL: SEC has no XBRL financial data for this filer (funds/ETFs, trusts, "
                    "very new registrants and some foreign filers). Company profile and latest filings are included above."}
        return {**out, "status": "ERROR", "error": f"SEC XBRL fetch failed (HTTP {e.code}); try again"}
    except Exception as e:
        return {**out, "status": "ERROR", "error": f"SEC XBRL fetch failed ({type(e).__name__}); try again (large filers can be slow)"}
    facts = cf.get("facts") or {}
    fy, qt = _block(facts, "annual"), _block(facts, "quarter")
    if fy and qt and qt["period_end"] < fy["period_end"]:
        qt = {"note": f"latest quarterly XBRL figures (period ending {qt['period_end']}) are older than the latest annual report; "
                      "omitted so they are not mistaken for current numbers"}
    if not fy and not qt:
        return {**out, "status": "ERROR", "error": "NO_XBRL: this filer's XBRL data has none of the key figures (revenue, net income, "
                "assets...) from a 10-K/10-Q/20-F. Company profile and latest filings are included above."}
    out["status"] = "OK"
    out["latest_fiscal_year"] = fy or {"note": "no annual report (10-K/20-F/40-F) figures yet: new registrants file a first 10-K after their first full fiscal year"}
    out["latest_quarter"] = qt or {"note": "no quarterly report (10-Q) figures: foreign private issuers (20-F/40-F) usually do not file 10-Qs"}
    out["computed"] = _computed(facts, fy, qt)
    fin_filed = max([v["filed"] for b in (fy, qt) if b for v in (b.get("figures") or {}).values() if v and v.get("filed")] or [None])
    out["freshness"] = {
        "latest_filing_date": latest[0]["filed"] if latest else None,
        "financials_last_filed": fin_filed,
        "note": "Filing-date data, not real-time. Figures are as of each period_end and became public on each 'filed' date; "
                "10-Qs land up to 40-45 days and 10-Ks up to 60-90 days after period end. Results may be cached up to 15 minutes."}
    warn = []
    for blk, forms in ((fy, ("10-K", "20-F")), (qt if qt and qt.get("figures") else None, ("10-Q",))):
        if not blk:
            continue
        newer = [key[f]["report_date"] for f in forms if f in key and (key[f].get("report_date") or "") > blk["period_end"]]
        if newer:
            warn.append(f"a newer {'/'.join(forms)} (period {max(newer)}) is on file but its XBRL figures are not in SEC's "
                        f"companyfacts data yet; the block ending {blk['period_end']} is the latest machine-readable one")
    out["freshness"]["warnings"] = warn or None
    out["elapsed_ms"] = int((time.time() - t0) * 1000)
    _results[cik] = (time.time(), {k: v for k, v in out.items() if k not in ("checked_at", "query")})
    if len(_results) > 200:
        for k in sorted(_results, key=lambda k: _results[k][0])[:50]:
            _results.pop(k, None)
    return out
