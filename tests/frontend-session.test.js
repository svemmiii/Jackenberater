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
const localStorageData = new Map();
context.window.localStorage = {
  getItem(key) { return localStorageData.has(key) ? localStorageData.get(key) : null; },
  setItem(key, value) { localStorageData.set(key, String(value)); },
  removeItem(key) { localStorageData.delete(key); },
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
  assert.match(source, /Simulated profile values may affect display only/, "simulation must remain display-only");
  assert.match(source, /unusualDay:\s*"Today was unusual/, "English unusual-day label must exist");

  const hiddenCard = new Card();
  hiddenCard._preview = { recommendation: { display_mode: "hidden" }, profile: { setup_complete: true }, feedback: [] };
  hiddenCard._open = false;
  assert.equal(hiddenCard.getCardSize(), 0, "closed hidden card may report size zero");
  hiddenCard._open = true;
  assert.equal(hiddenCard.getCardSize(), 6, "opened hidden card must keep a real layout size");

  const calendarWarningCard = new Card();
  calendarWarningCard._config = { type: "custom:jackenberater-card" };
  calendarWarningCard._hass = { language: "de" };
  calendarWarningCard._preview = {
    recommendation: {
      display_mode: "hidden",
      jacket_now: "none",
      jacket_later: "none",
      context_calendar_status: "unavailable",
      vacation_calendar_status: "unavailable",
    },
    profile: { setup_complete: true },
    feedback: [],
  };
  calendarWarningCard._bind = () => {};
  assert.equal(calendarWarningCard.getCardSize(), 2, "calendar outages must keep an otherwise hidden card visible");
  calendarWarningCard._render();
  assert.match(calendarWarningCard.innerHTML, /Kontextkalender nicht verfügbar/, "context-calendar outage must be visible");
  assert.match(calendarWarningCard.innerHTML, /Abwesenheitskalender nicht verfügbar/, "vacation-calendar outage must be visible");

  assert.match(source, /Wie aktiv bist du dabei\?/, "evening setup question must measure the activity used by the model");

  const textCard = new Card();
  textCard._hass = { language: "de" };
  const laterText = textCard._laterText({
    jacket_now: "none",
    jacket_later: "winter",
    later_at: "2026-09-01T18:00:00+00:00",
  });
  const expectedLaterTime = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" }).format(new Date("2026-09-01T18:00:00+00:00"));
  assert.match(laterText, /Wenn du länger unterwegs bist/, "later-warmer advice must transparently state its unknown-stay assumption");
  assert.match(laterText, new RegExp(`ab etwa ${expectedLaterTime.replace(".", "\\.")}`), "later-warmer advice should use the browser's local time");


  // Shared wall-tablet selection is local to this browser/account and survives
  // closing/reloading until the user deliberately selects another profile.
  const persistentCard = new Card();
  persistentCard._config = { type: "custom:jackenberater-card" };
  persistentCard._autoShared = true;
  persistentCard._entryId = "entry-1";
  persistentCard._currentUserId = "wall-tablet";
  persistentCard._selectedProfile = "user";
  persistentCard._persistSharedProfile();
  assert.equal(
    context.window.localStorage.getItem("jackenberater:selected-profile:entry-1:wall-tablet"),
    "user",
    "shared profile selection must be stored locally",
  );
  const reloadedCard = new Card();
  reloadedCard._config = { type: "custom:jackenberater-card" };
  reloadedCard._autoShared = true;
  reloadedCard._entryId = "entry-1";
  reloadedCard._currentUserId = "wall-tablet";
  reloadedCard._restoreSharedProfile([{ id: "user", name: "User" }]);
  assert.equal(reloadedCard._selectedProfile, "user", "shared profile must restore after a browser/card restart");
  reloadedCard._open = true;
  reloadedCard._render = () => {};
  await reloadedCard._openAdvice();
  assert.equal(reloadedCard._selectedProfile, "user", "closing details must not forget the wall-tablet profile");

  // Info field explains assumptions and keeps profile backups disabled.
  textCard._currentUserId = "user";
  const infoHtml = textCard._infoPanel(
    {
      horizon_hours: 9, stay_context: "unknown", trend: "warming",
      forecast_coverage_complete: true, confidence: 0.64, transient_override: true,
      transient_until: "2026-09-01T12:15:00+00:00", seasonal_adjustment_c: 0.2,
    },
    { id: "user", confidence: 0.64 },
  );
  assert.doesNotMatch(infoHtml, /profile-export|profile-import/, "disabled profile backups must not be shown");
  assert.match(infoHtml, /Betrachtet/, "info panel must explain the current horizon");
  assert.match(source, /jackenberater\/profile_import/, "frontend must support profile restore");
  assert.match(source, /mdi:information-outline/, "card must expose the circled information control");

  const sharedReadOnlyCard = new Card();
  sharedReadOnlyCard._hass = { language: "de" };
  sharedReadOnlyCard._autoShared = true;
  sharedReadOnlyCard._isAdmin = false;
  sharedReadOnlyCard._currentUserId = "wall-tablet";
  sharedReadOnlyCard._selectedProfile = "user";
  sharedReadOnlyCard._preview = { profile: { id: "user", setup_complete: true } };
  sharedReadOnlyCard._render = () => {};
  let sharedOpenCalls = 0;
  sharedReadOnlyCard._send = async (type) => {
    assert.equal(type, "jackenberater/open_session");
    sharedOpenCalls += 1;
    return { session: null, recommendation: { reasons: [] }, feedback: [] };
  };
  await sharedReadOnlyCard._openAdvice();
  assert.equal(sharedOpenCalls, 1, "shared tablet details must open a profile-scoped session");
  assert.equal(sharedReadOnlyCard._session, null, "shared session internals must stay server-side");
  assert.equal(sharedReadOnlyCard._open, true, "shared tablet may open details");
  const sharedInfo = sharedReadOnlyCard._infoPanel(
    { horizon_hours: 9, stay_context: "unknown", trend: "stable", forecast_coverage_complete: true },
    { id: "user" },
  );
  assert.doesNotMatch(sharedInfo, /profile-export|data-maintenance/, "shared tablet must not expose profile write or export controls");

  const simulatedSharedCard = new Card();
  simulatedSharedCard._autoShared = true;
  simulatedSharedCard._isAdmin = false;
  simulatedSharedCard._selectedProfile = "user";
  simulatedSharedCard._preview = {
    profile: { id: "user", setup_complete: true },
    recommendation: { simulation_active: true },
  };
  simulatedSharedCard._render = () => {};
  simulatedSharedCard._send = async () => { throw new Error("simulation attempted to create a session"); };
  await simulatedSharedCard._openAdvice();
  assert.equal(simulatedSharedCard._open, true, "simulated values may still open display details");

  const feedbackHeading = textCard._details(
    {
      reasons: [], rain_status: "none", current_temperature_c: 15,
      current_wind_kmh: 5, horizon_hours: 9, work_context: false,
    },
    { name: "Sven", confidence: 0.5, total_feedback: 0 },
    [session],
  );
  assert.match(feedbackHeading, /Feedback für Sven/, "pending wall-tablet feedback must name its profile");

  const gustDetails = textCard._details(
    {
      reasons: ["wind"], rain_status: "none", current_temperature_c: 10,
      current_wind_kmh: 10, current_gust_kmh: 30, horizon_hours: 9, work_context: false,
    },
    { confidence: 0.5, total_feedback: 0 },
    [],
  );
  assert.match(gustDetails, /Böen 30 km\/h/, "gusts used by the engine should be visible in details");
  const partialWorkDetails = textCard._details(
    {
      reasons: [], rain_status: "none", current_temperature_c: 10,
      current_wind_kmh: 5, horizon_hours: 9, work_context: true,
      work_forecast_coverage: "partial", work_weather_available: false,
    },
    { confidence: 0.5, total_feedback: 0 },
    [],
  );
  assert.match(partialWorkDetails, /Arbeitsforecast nur teilweise abgedeckt/, "partial work coverage must be visible in normal details");
  assert.match(textCard._errorText(new Error("work_weather_unavailable")), /Arbeitswetter/, "work-weather outage should be explained instead of showing a raw backend code");

  console.log("frontend session contract OK");
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
