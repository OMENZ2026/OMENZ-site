// OMENZ first-party site analytics (page views, outbound clicks, 404s). Added 2026-11-01 (founder-approved ecosystem project).
// Same storage and token as Experiment B's hit.js: one Apify dataset, separated by key="site".
// Privacy: no cookies; the IP address is never stored. "visitor" is a one-way hash of IP + user agent + date + a server-side
// secret, so the same visitor counts once per day and can't be followed across days or identified.
const crypto = require("crypto");
const DATASET = "uO9teiO37CevrQOUy";
const KINDS = new Set(["pv", "click", "404"]);

function host(u) { try { return new URL(u).hostname; } catch (e) { return ""; } }
function clip(s, n) { return String(s || "").slice(0, n); }

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") { res.statusCode = 405; return res.end(); }
  let d = req.body;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch (e) { d = null; } }
  if (!d || !KINDS.has(d.t)) { res.statusCode = 204; return res.end(); }
  const h = req.headers || {};
  const ip = String(h["x-forwarded-for"] || "").split(",")[0].trim();
  const ua = clip(h["user-agent"], 300);
  const day = new Date().toISOString().slice(0, 10);
  const token = process.env.APIFY_LOG_TOKEN || "";
  const visitor = crypto.createHash("sha256").update(ip + "|" + ua + "|" + day + "|" + token).digest("hex").slice(0, 16);
  const ref = clip(d.r, 300);
  const item = {
    ts: new Date().toISOString(), key: "site", kind: d.t, path: clip(d.p, 200),
    ref_host: host(ref), ref_path: host(ref).endsWith("omenz.org") ? clip(new URL(ref).pathname, 120) : "",
    utm_source: clip(d.utm_source, 60), utm_medium: clip(d.utm_medium, 60), utm_campaign: clip(d.utm_campaign, 80), utm_content: clip(d.utm_content, 80),
    dest: clip(d.dest, 80), dest_host: host(d.href), width: Number(d.w) || 0,
    ua, country: h["x-vercel-ip-country"] || "", visitor, status: 200,
  };
  if (token) {
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 1500);
      await fetch("https://api.apify.com/v2/datasets/" + DATASET + "/items", { method: "POST", signal: ctl.signal,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify(item) });
      clearTimeout(t);
    } catch (e) { console.log("t-log-failed", String(e)); }
  }
  res.statusCode = 204;
  res.end();
};
