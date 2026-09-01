const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const registry = new Map();
const context = {
  console,
  setInterval,
  clearInterval,
  setTimeout,
  clearTimeout,
  Date,
  HTMLElement: class {},
  CustomEvent: class {},
  document: { createElement: () => ({}) },
  customElements: {
    define(name, cls) { registry.set(name, cls); },
    get(name) { return registry.get(name); },
  },
  window: {},
};
context.window.window = context.window;
vm.createContext(context);
const source = fs.readFileSync(
  "custom_components/jackenberater/frontend/jackenberater-card.js",
  "utf8",
);
vm.runInContext(source, context, { filename: "jackenberater-card.js" });

const Card = registry.get("jackenberater-card");
assert.ok(Card, "jackenberater-card must register itself");

(async () => {
  const card = new Card();
  const session = {
    id: "abc123",
    recommendation: { jacket_now: "light", jacket_later: "light" },
    feedback: null,
  };
  card._session = session;
  card._send = async () => ({ ok: true });
  card._refresh = async () => {};
  card._t = () => "saved";

  await card._feedback(session, "perfect");
  assert.equal(card._session, null, "answered local session must be cleared");
  assert.equal(card._notice, "saved");

  assert.match(
    source,
    /unusualDay:\s*"Today was unusual/,
    "English unusual-day label must exist",
  );

  console.log("frontend session contract OK");
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
