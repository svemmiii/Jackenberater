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
    created_at: "2026-09-01T12:00:00+00:00",
    recommendation: { jacket_now: "light", jacket_later: "light" },
    weather: { temperature_c: 15 },
    feedback: null,
  };
  card._session = session;
  card._send = async () => ({ ok: true });
  card._refresh = async () => {};
  card._t = (key) => key;

  await card._feedback(session, "perfect");
  assert.equal(card._session, null, "answered local session must be cleared");
  assert.equal(card._notice, "submitted");

  // A newly opened recommendation must not immediately render rating buttons.
  card._session = session;
  card._preview = { latest_session: session };
  card._manualFeedbackVisible = false;
  const details = card._details(
    {
      reasons: [],
      rain_status: "none",
      current_temperature_c: 15,
      current_wind_kmh: 5,
      horizon_hours: 9,
      work_context: false,
    },
    { confidence: 0.5, total_feedback: 0 },
    [],
  );
  assert.match(details, /data-action="manual-feedback"/, "manual feedback remains explicitly available");
  assert.doesNotMatch(details, /data-feedback="perfect"/, "fresh session must not show rating buttons automatically");

  // Manual feedback must always create/reuse a current backend session, not
  // keep an hours-old session from when the details panel was opened.
  const freshSession = { ...session, id: "fresh456", created_at: "2026-09-01T14:00:00+00:00" };
  card._session = session;
  card._preview = { latest_session: session, recommendation: session.recommendation, feedback: [] };
  let manualOpenCalls = 0;
  card._render = () => {};
  card._send = async (type) => {
    if (type === "jackenberater/open_session") {
      manualOpenCalls += 1;
      return { session: freshSession, recommendation: freshSession.recommendation, feedback: [] };
    }
    throw new Error(`unexpected message: ${type}`);
  };
  await card._prepareManualFeedback();
  assert.equal(manualOpenCalls, 1, "manual feedback must request a current session");
  assert.equal(card._session.id, "fresh456", "manual feedback must replace stale local session context");
  assert.equal(card._manualFeedbackVisible, true, "fresh manual-feedback session should be shown");

  card._manualFeedbackVisible = true;
  const manualDetails = card._details(
    {
      reasons: [], rain_status: "none", current_temperature_c: 15,
      current_wind_kmh: 5, horizon_hours: 9, work_context: false,
    },
    { confidence: 0.5, total_feedback: 0 },
    [],
  );
  assert.match(manualDetails, /data-feedback="perfect"/, "explicit manual feedback reveals rating buttons");

  const sharedCard = new Card();
  sharedCard._render = () => {};
  sharedCard.setConfig({ type: "custom:jackenberater-card" });
  sharedCard._hass = {};
  sharedCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return { shared_account: true, profiles: [{ id: "user", name: "User" }] };
    }
    throw new Error("preview must not be requested before shared profile selection");
  };
  await sharedCard._refresh();
  assert.equal(sharedCard._sharedMode(), true, "configured shared HA account must enable shared mode automatically");
  assert.equal(sharedCard._preview, null, "shared account must wait for a real user profile selection");

  assert.match(source, /this\._autoShared = Boolean\(profiles\?\.shared_account\)/, "shared HA accounts must switch the card automatically");
  assert.match(source, /unusualDay:\s*"Today was unusual/, "English unusual-day label must exist");

  const hiddenCard = new Card();
  hiddenCard._preview = { recommendation: { display_mode: "hidden" }, profile: { setup_complete: true }, feedback: [] };
  hiddenCard._open = false;
  assert.equal(hiddenCard.getCardSize(), 0, "closed hidden card may report size zero");
  hiddenCard._open = true;
  assert.equal(hiddenCard.getCardSize(), 6, "opened hidden card must keep a real layout size");

  assert.match(source, /Wie aktiv bist du dabei\?/, "evening setup question must measure the activity used by the model");

  const textCard = new Card();
  textCard._hass = { language: "de" };
  const laterText = textCard._laterText({
    jacket_now: "none",
    jacket_later: "winter",
    later_at: "2026-09-01T18:00:00+00:00",
  });
  assert.match(laterText, /jetzt mitnehmen/, "later-warmer advice must make clear the jacket should be taken now");

  const gustDetails = textCard._details(
    {
      reasons: ["wind"], rain_status: "none", current_temperature_c: 10,
      current_wind_kmh: 10, current_gust_kmh: 30, horizon_hours: 9, work_context: false,
    },
    { confidence: 0.5, total_feedback: 0 },
    [],
  );
  assert.match(gustDetails, /Böen 30 km\/h/, "gusts used by the engine should be visible in details");
  assert.match(textCard._errorText(new Error("work_weather_unavailable")), /Arbeitswetter/, "work-weather outage should be explained instead of showing a raw backend code");

  console.log("frontend session contract OK");
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
