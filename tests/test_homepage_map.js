const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../docs/index.html'), 'utf8');
const script = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).find(text => text.includes('var CONTACT'));

async function runGeo(latitude, longitude) {
  const circles = [];
  const nodes = {};
  const events = [];
  const context = {
    document: {
      addEventListener() {},
      getElementById(id) { return nodes[id] ||= { style: {}, textContent: '' }; },
    },
    location: { search: '?wybor', hash: '' },
    localStorage: { getItem() { return null; } },
    matchMedia() { return { matches: false }; },
    gtag(...args) { events.push(args); },
    setTimeout() { return 1; }, clearTimeout() {},
    AbortController: class { constructor() { this.signal = {}; } abort() {} },
    fetch: async () => ({ json: async () => ({ latitude, longitude }) }),
    L: {
      map() { return { fitBounds() {}, flyTo() {} }; },
      control: { zoom() { return { addTo() {} }; } },
      tileLayer() { return { addTo() {} }; },
      divIcon(options) { return options; },
      marker() {
        return { addTo() { return this; }, getElement() {
          return { firstChild: { classList: { add() {} } } };
        } };
      },
      circleMarker(coords, options) {
        const marker = {
          options: { ...options }, addTo() { return this; },
          bindPopup() { return this; }, on() { return this; },
          setStyle(style) { Object.assign(this.options, style); },
          setRadius(radius) { this.options.radius = radius; },
        };
        circles.push(marker);
        return marker;
      },
    },
  };
  vm.runInNewContext(script, context);
  await new Promise(resolve => setImmediate(resolve));
  const colors = circles.slice(0, 6).map(marker => marker.options.fillColor);
  assert.equal(new Set(colors).size, 6);
  context.APS.forEach((airport, i) => {
    assert.equal(circles[i].options.fillColor,
      airport[5] ? context.AP_COLORS[airport[0]] : '#9aa3b2');
  });
  assert(events.some(event => event[1] === 'geo_suggest'));
  return circles;
}

(async () => {
  const warsaw = await runGeo(52.30, 20.80);
  assert.equal(warsaw[0].options.radius, 20);
  assert.equal(warsaw[0].options.color, '#0b1733');
  const szczecin = await runGeo(53.5847, 14.9022);
  assert.equal(szczecin[9].options.radius, 9);
  assert.equal(szczecin[9].options.fillColor, '#9aa3b2');
  console.log('Homepage marker colors and geolocation: OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
