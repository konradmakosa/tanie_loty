const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync("templates/app.html", "utf8");
const start = html.indexOf("function loadStaticDeals()");
const end = html.indexOf("loadDeals().then(", start);
assert.ok(start >= 0 && end > start);
const code = html.slice(start, end) + "\nloadDeals()";
const tabs = {
  okazje: { generated_at: "now", config: {}, deals: [1] },
  daleko: { generated_at: "now", config: {}, deals: [2] },
  oneway: { generated_at: "now", config: {}, deals: [3] },
};

async function check(apiGet, expectedStaticRequests) {
  const requested = [];
  const result = await vm.runInNewContext(code, {
    apiGet,
    PORT: "zkatowic",
    encodeURIComponent,
    fetch: async (url) => {
      requested.push(url);
      return { ok: true, json: async () =>
        tabs[{ "deals.json": "okazje", "far.json": "daleko",
               "oneway.json": "oneway" }[url]] };
    },
  });
  assert.deepEqual(JSON.parse(JSON.stringify(result)),
                   Object.values(tabs));
  assert.equal(requested.length, expectedStaticRequests);
}

(async () => {
  await check(async (path) => {
    assert.equal(path, "/snapshot.php?port=zkatowic");
    return tabs;
  }, 0);
  await check(async () => { throw new Error("API unavailable"); }, 3);
  await check(async () => ({ okazje: tabs.okazje }), 3);
})().catch(e => { console.error(e); process.exitCode = 1; });
