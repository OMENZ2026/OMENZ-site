// Shirt links omenz.org/s/<shirt> (every ad + QR code points here). Logs the click, then 302s to the Fourthwall product.
// Sensor added 11-20: Fourthwall showed 0 sold on all shirts and the old static redirects logged nothing, so we couldn't
// tell "no clicks" from "clicks that don't buy". Logged: shirt, referer, utm, user-agent class, country. NO IP.
const SHIRTS = require("./_shirts.json");
const DATASET = "uO9teiO37CevrQOUy";
module.exports = async (req, res) => {
  const q = req.query || {};
  const slug = String(q.slug || "").toLowerCase().replace(/[^a-z0-9-]/g, "");
  const dest = SHIRTS[slug];
  const h = req.headers || {};
  const ua = h["user-agent"] || "";
  const item = { ts: new Date().toISOString(), key: "shirt", slug, found: !!dest, referer: (h["referer"] || "").slice(0, 200),
                 utm_source: String(q.utm_source || "").slice(0, 40), utm_campaign: String(q.utm_campaign || "").slice(0, 60),
                 ua_class: /omenz-/i.test(ua) ? "test" : /bot|crawl|spider|preview|facebookexternalhit|slack|whatsapp|telegram/i.test(ua) ? "bot" : /mozilla/i.test(ua) ? "browser" : "other",
                 ua: ua.slice(0, 160), country: h["x-vercel-ip-country"] || "" };
  const token = process.env.APIFY_LOG_TOKEN;
  if (token) {
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 1200);
      await fetch("https://api.apify.com/v2/datasets/" + DATASET + "/items", { method: "POST", signal: ctl.signal,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify(item) });
      clearTimeout(t);
    } catch (e) { console.log("shirt-log-failed", String(e)); }
  }
  res.statusCode = 302;
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Location", dest || "https://omenz-shop.fourthwall.com/");
  res.end();
};
