// OMENZ survey responses (founder-approved 2026-11-11): what tools people need + how current tools and OMENZ products rate.
// Same storage as t.js (one Apify dataset, key="survey"). No cookies; IP never stored; visitor = daily one-way hash.
const crypto = require("crypto");
const DATASET = "uO9teiO37CevrQOUy";
const clip = (s, n) => String(s == null ? "" : s).slice(0, n);

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") { res.statusCode = 405; return res.end(); }
  let d = req.body;
  if (typeof d === "string") { try { d = JSON.parse(d); } catch (e) { d = null; } }
  if (!d || d.hp) { res.statusCode = 204; return res.end(); } // hp = honeypot field that bots fill
  const h = req.headers || {};
  const ip = String(h["x-forwarded-for"] || "").split(",")[0].trim();
  const token = process.env.APIFY_LOG_TOKEN || "";
  const day = new Date().toISOString().slice(0, 10);
  const visitor = crypto.createHash("sha256").update(ip + "|" + clip(h["user-agent"], 300) + "|" + day + "|" + token).digest("hex").slice(0, 16);
  const item = {
    ts: new Date().toISOString(), key: "survey", visitor, country: h["x-vercel-ip-country"] || "",
    who: clip(d.who, 40), task: clip(d.task, 600), tools: clip(d.tools, 300), hate: clip(d.hate, 600),
    pay: clip(d.pay, 30), rate: clip(d.rate, 200), want: clip(d.want, 600), email: clip(d.email, 120), src: clip(d.src, 60),
  };
  if (token) {
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 2000);
      await fetch("https://api.apify.com/v2/datasets/" + DATASET + "/items", { method: "POST", signal: ctl.signal,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify(item) });
      clearTimeout(t);
    } catch (e) { console.log("survey-log-failed", String(e)); }
  }
  res.statusCode = 200;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({ ok: true }));
};
