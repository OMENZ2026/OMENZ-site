// Serves OMENZ flyer files and logs each fetch (time, path, user-agent, referer, country; NO IP) for Experiment B.
const CONTENT = require("./_content.js");
const DATASET = "uO9teiO37CevrQOUy";
module.exports = async (req, res) => {
  const key = String((req.query && req.query.f) || "");
  const hit = CONTENT[key];
  const h = req.headers || {};
  const item = { ts: new Date().toISOString(), key, path: h["x-forwarded-uri"] || req.url, ua: h["user-agent"] || "",
                 referer: h["referer"] || "", accept: h["accept"] || "", country: h["x-vercel-ip-country"] || "", status: hit ? 200 : 404 };
  const token = process.env.APIFY_LOG_TOKEN;
  if (token) {
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 1500);
      await fetch("https://api.apify.com/v2/datasets/" + DATASET + "/items", { method: "POST", signal: ctl.signal,
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify(item) });
      clearTimeout(t);
    } catch (e) { console.log("log-failed", String(e)); }
  } else { console.log("hit", JSON.stringify(item)); }
  if (!hit) { res.statusCode = 404; res.setHeader("Content-Type", "text/plain"); return res.end("not found"); }
  res.statusCode = 200;
  res.setHeader("Content-Type", hit[0]);
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.end(typeof hit[1] === "string" ? hit[1] : JSON.stringify(hit[1], null, 1));
};
