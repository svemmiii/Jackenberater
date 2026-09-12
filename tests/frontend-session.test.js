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

  const workWarningCard = new Card();
  workWarningCard._config = { type: "custom:jackenberater-card" };
  workWarningCard._hass = { language: "de" };
  workWarningCard._preview = {
    recommendation: {
      display_mode: "hidden", jacket_now: "none", jacket_later: "none",
      work_forecast_coverage: "missing", work_weather_available: false,
    },
    profile: { setup_complete: true }, feedback: [],
  };
  workWarningCard._bind = () => {};
  assert.equal(workWarningCard.getCardSize(), 2, "missing work forecast must keep an otherwise hidden card visible");
  workWarningCard._render();
  assert.match(workWarningCard.innerHTML, /Arbeitsforecast fehlt/, "missing work forecast warning must name the missing forecast, not live work weather");

  // Missing work forecast is one warning, even when both details and info are open.
  workWarningCard._open = true;
  workWarningCard._infoOpen = true;
  workWarningCard._render();
  assert.equal(
    (workWarningCard.innerHTML.match(/Arbeitsforecast fehlt/g) || []).length,
    1,
    "the same work-forecast warning must not be duplicated across card sections",
  );

  // The internal effective/thermal temperature stays an engine value and must
  // not leak into the normal user-facing card as a second pseudo-temperature.
  const thermalCard = new Card();
  thermalCard._config = { type: "custom:jackenberater-card" };
  thermalCard._hass = { language: "de" };
  thermalCard._preview = {
    recommendation: {
      display_mode: "full", jacket_now: "light", jacket_later: "light",
      current_temperature_c: 12, effective_now_c: 123.45,
      current_wind_kmh: 4, horizon_hours: 9,
    },
    profile: { setup_complete: true, learning_progress: 0.4, total_feedback: 2 },
    feedback: [],
  };
  thermalCard._bind = () => {};
  thermalCard._render();
  assert.match(thermalCard.innerHTML, /12 °C/, "real air temperature remains visible");
  assert.doesNotMatch(thermalCard.innerHTML, /123\.45/, "internal effective temperature must stay out of the user card");
  assert.doesNotMatch(source, /thermisch etwa/, "the old thermal-value label must be removed from the user UI");

  // Info and recommendation details must be mutually exclusive. Opening the
  // details while Info is visible closes Info before creating/reusing a session.
  const exclusiveCard = new Card();
  exclusiveCard._config = { type: "custom:jackenberater-card" };
  exclusiveCard._hass = { language: "de" };
  exclusiveCard._preview = {
    recommendation: { display_mode: "full", simulation_active: false },
    profile: { setup_complete: true },
    feedback: [],
  };
  exclusiveCard._infoOpen = true;
  exclusiveCard._open = false;
  exclusiveCard._render = () => {};
  exclusiveCard._send = async (type) => {
    if (type === "jackenberater/open_session") {
      return { session, recommendation: exclusiveCard._preview.recommendation, feedback: [] };
    }
    throw new Error(`unexpected message: ${type}`);
  };
  await exclusiveCard._openAdvice();
  assert.equal(exclusiveCard._open, true, "opening details must open the details panel");
  assert.equal(exclusiveCard._infoOpen, false, "opening details must close Info");

  exclusiveCard._open = true;
  exclusiveCard._infoOpen = false;
  exclusiveCard._phasePending = { fake: true };
  exclusiveCard._notice = "old notice";
  exclusiveCard._toggleInfo();
  assert.equal(exclusiveCard._infoOpen, true, "opening Info must open the Info panel");
  assert.equal(exclusiveCard._open, false, "opening Info must close the details panel");
  assert.equal(exclusiveCard._phasePending, null, "switching to Info must close an in-progress details subpanel");
  assert.equal(exclusiveCard._notice, "", "switching to Info must clear details-only notices");

  // A profile deleted while a wall tablet is open must invalidate the local
  // selection instead of getting stuck on profile_not_found until reload.
  const deletedProfileCard = new Card();
  deletedProfileCard._config = { type: "custom:jackenberater-card" };
  deletedProfileCard._hass = { language: "de" };
  deletedProfileCard._autoShared = true;
  deletedProfileCard._entryId = "entry-deleted";
  deletedProfileCard._currentUserId = "tablet";
  deletedProfileCard._selectedProfile = "deleted-user";
  deletedProfileCard._render = () => {};
  let deletedPreviewCalls = 0;
  deletedProfileCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return { entry_id: "entry-deleted", current_user_id: "tablet", shared_account: true, is_admin: false, profiles: [{ id: "other", name: "Other" }] };
    }
    if (type === "jackenberater/preview") deletedPreviewCalls += 1;
    throw new Error(`unexpected message: ${type}`);
  };
  await deletedProfileCard._refresh();
  assert.equal(deletedProfileCard._selectedProfile, null, "deleted shared profile selection must be cleared live");
  assert.equal(deletedPreviewCalls, 0, "no preview may be sent with a deleted profile id");

  // Runtime normal -> shared reconfigure must switch into profile-selection mode.
  const becameSharedCard = new Card();
  becameSharedCard._config = { type: "custom:jackenberater-card" };
  becameSharedCard._hass = { language: "de" };
  becameSharedCard._autoShared = false;
  becameSharedCard._render = () => {};
  let becameSharedPreviewCalls = 0;
  becameSharedCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return { entry_id: "entry", current_user_id: "tablet", shared_account: true, is_admin: false, profiles: [{ id: "sven", name: "Sven" }] };
    }
    if (type === "jackenberater/preview") becameSharedPreviewCalls += 1;
    throw new Error(`unexpected message: ${type}`);
  };
  await becameSharedCard._refresh();
  assert.equal(becameSharedCard._autoShared, true, "live normal-to-shared reconfigure must be detected");
  assert.equal(becameSharedPreviewCalls, 0, "newly shared account must wait for explicit profile selection");

  // Runtime shared -> normal must discard the foreign profile and use own preview.
  const becameNormalCard = new Card();
  becameNormalCard._config = { type: "custom:jackenberater-card" };
  becameNormalCard._hass = { language: "de" };
  becameNormalCard._autoShared = true;
  becameNormalCard._selectedProfile = "sven";
  becameNormalCard._render = () => {};
  becameNormalCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return { entry_id: "entry", current_user_id: "tablet", shared_account: false, is_admin: false, profiles: [{ id: "tablet", name: "Tablet" }] };
    }
    if (type === "jackenberater/preview") return { recommendation: { display_mode: "full" }, profile: { id: "tablet", setup_complete: true }, feedback: [] };
    throw new Error(`unexpected message: ${type}`);
  };
  await becameNormalCard._refresh();
  assert.equal(becameNormalCard._autoShared, false, "live shared-to-normal reconfigure must be detected");
  assert.equal(becameNormalCard._selectedProfile, null, "foreign shared selection must be cleared when account becomes normal");
  assert.equal(becameNormalCard._preview.profile.id, "tablet", "normal account must resume its own preview without reload");

  const legacySharedCard = new Card();
  legacySharedCard._config = { type: "custom:jackenberater-card", shared: true };
  legacySharedCard._autoShared = false;
  assert.equal(legacySharedCard._sharedMode(), false, "Lovelace shared:true must not create shared-device permissions or behaviour");

  const retryCard = new Card();
  retryCard._config = { type: "custom:jackenberater-card" };
  retryCard._hass = { language: "de" };
  retryCard._profileMetaLoaded = true;
  retryCard._render = () => {};
  retryCard._send = async () => { throw new Error("offline"); };
  await retryCard._refresh();
  assert.equal(retryCard._refreshFailures, 1, "failed refresh must be tracked");
  assert.equal(retryCard._retryIntervalMs(), 60 * 1000, "first retry should be rate-limited to one minute");
  await retryCard._refresh();
  assert.equal(retryCard._refreshFailures, 2, "repeated failures must increase backoff");
  assert.equal(retryCard._retryIntervalMs(), 120 * 1000, "repeated failures should back off instead of retrying on every HA state update");


  const timerCard = new Card();
  timerCard._config = { type: "custom:jackenberater-card" };
  timerCard._hass = { language: "de" };
  timerCard._render = () => {};
  timerCard._stateRefreshTimer = setTimeout(() => {}, 60 * 1000);
  timerCard._send = async (type) => {
    if (type === "jackenberater/profiles") return { current_user_id: "user", shared_account: false, is_admin: false, profiles: [] };
    if (type === "jackenberater/preview") return { recommendation: {}, profile: { setup_complete: true }, feedback: [] };
    throw new Error(`unexpected message: ${type}`);
  };
  await timerCard._refresh();
  assert.equal(timerCard._stateRefreshTimer, null, "an already pending state timer must be cancelled by any real refresh");

  assert.match(source, /Wie aktiv bist du abends typischerweise draußen\?/, "evening setup question must match the broad evening activity correction");

  const textCard = new Card();
  textCard._hass = { language: "de" };
  const laterText = textCard._laterText({
    jacket_now: "none",
    jacket_later: "winter",
    later_at: "2026-09-01T18:00:00+00:00",
  });
  const expectedLaterTime = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" }).format(new Date("2026-09-01T18:00:00+00:00"));
  assert.match(laterText, /Wenn du dann noch unterwegs bist/, "later-warmer advice must transparently state its unknown-stay assumption");
  assert.match(laterText, /jetzt mitnehmen/, "later-warmer advice must explicitly say to take the warmer jacket now");
  assert.match(laterText, new RegExp(`ab etwa ${expectedLaterTime.replace(".", "\.")}`), "later-warmer advice should use the browser's local time");

  const workBufferText = textCard._laterText({
    jacket_now: "light",
    jacket_later: "warm",
    later_at: "2026-09-01T15:15:00+00:00",
    later_context: "work",
    work_start: "2026-09-01T13:00:00+00:00",
    work_end: "2026-09-01T15:00:00+00:00",
  });
  assert.match(workBufferText, /Rund um deine Arbeit/, "work-buffer advice after the real shift must not call that time Arbeitszeit");
  assert.doesNotMatch(workBufferText, /Für deine Arbeitszeit/, "post-shift buffer must not be described as actual work time");

  const actualWorkText = textCard._laterText({
    jacket_now: "light",
    jacket_later: "warm",
    later_at: "2026-09-01T14:15:00+00:00",
    later_context: "work",
    work_start: "2026-09-01T13:00:00+00:00",
    work_end: "2026-09-01T15:00:00+00:00",
  });
  assert.match(actualWorkText, /Für deine Arbeitszeit/, "advice inside the real shift should still name the work period");


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
  assert.doesNotMatch(partialWorkDetails, /Arbeitsforecast nur teilweise abgedeckt/, "work-forecast coverage warning is rendered once at card level, not duplicated in details");
  assert.match(textCard._errorText(new Error("work_weather_unavailable")), /Arbeitswetter/, "work-weather outage should be explained instead of showing a raw backend code");

  const feedbackUxCard = new Card();
  feedbackUxCard._hass = { language: "de" };
  feedbackUxCard._t = (key) => ({
    phaseAsk: "Was hat nicht gepasst?", cancel: "Abbrechen",
    light: "Leichte Jacke", none: "Keine Jacke nötig", warmJacket: "Warme Jacke", winter: "Winterjacke",
    oldRecommendation: "frühere Empfehlung", unusualDay: "Heute war ungewöhnlich",
    tooCold: "Zu kalt", perfect: "Perfekt", tooWarm: "Zu warm", notUsed: "Nicht genutzt",
  }[key] || key);
  const warmMorningSession = {
    id: "ux1",
    created_at: "2026-09-07T06:00:00+02:00",
    recommendation: {
      jacket_now: "light",
      jacket_later: "none",
      later_at: "2026-09-07T10:00:00+02:00",
    },
    weather: { temperature_c: 12 },
  };
  const feedbackHtml = feedbackUxCard._feedbackCard(warmMorningSession, true);
  assert.match(feedbackHtml, /Leichte Jacke.*→.*Keine Jacke nötig/, "feedback must show the full original jacket transition");
  feedbackUxCard._phasePending = { session: warmMorningSession, rating: "too_warm" };
  const warmPhase = feedbackUxCard._phasePanel();
  assert.match(warmPhase, /Jacke früher ausziehen/, "later warm feedback should describe an earlier transition");
  assert.match(warmPhase, /Schon am Anfang war mir zu warm/, "start feedback should use normal user language");
  assert.match(warmPhase, /über längere Zeit zu warm/, "long-duration feedback should use normal user language");

  // A relevant HA state update that arrives while a refresh is running must
  // be remembered and picked up immediately afterwards instead of being lost.
  const dirtyCard = new Card();
  dirtyCard._hass = { language: "de" };
  dirtyCard._loading = true;
  dirtyCard._scheduleStateRefresh();
  assert.equal(dirtyCard._refreshPending, true, "state changes during refresh must mark a follow-up refresh pending");

  const pendingCard = new Card();
  pendingCard._hass = { language: "de" };
  pendingCard._render = () => {};
  let scheduledFollowups = 0;
  pendingCard._scheduleStateRefresh = () => { scheduledFollowups += 1; };
  pendingCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      pendingCard._refreshPending = true;
      return { profiles: [], shared_account: false };
    }
    if (type === "jackenberater/preview") return { recommendation: { display_mode: "full" }, profile: { setup_complete: true }, feedback: [] };
    throw new Error(`unexpected message: ${type}`);
  };
  await pendingCard._refresh();
  assert.equal(scheduledFollowups, 1, "pending state refresh must re-enter through the throttle scheduler, not recurse directly");

  const explicitBufferText = textCard._laterText({
    jacket_now: "light", jacket_later: "warm",
    later_at: "2026-09-01T14:15:00+00:00", later_context: "work",
    work_start: "2026-09-01T12:30:00+00:00", work_end: "2026-09-01T15:30:00+00:00",
    later_work_period: "buffer",
  });
  assert.match(explicitBufferText, /Rund um deine Arbeit/, "explicit backend buffer context must override timestamp inference");

  const lastPointText = textCard._laterText({
    jacket_now: "warm", jacket_later: "light",
    later_at: "2026-09-01T18:00:00+00:00",
    later_change_confirmed: false,
  });
  assert.match(lastPointText, /letzte Forecastwert/, "a single unconfirmed last forecast point must be phrased cautiously");
  assert.doesNotMatch(lastPointText, /Ab etwa/, "single unconfirmed endpoint must not sound like a confirmed trend start");

  assert.match(source, /if \(!customElements\.get\("jackenberater-card"\)\)/, "main custom element registration must be duplicate-load safe");
  assert.match(source, /if \(!customElements\.get\("jackenberater-card-editor"\)\)/, "editor custom element registration must be duplicate-load safe");
  assert.match(source, /!window\.customCards\.some/, "customCards metadata must not be duplicated");

  // Irrelevant HA state churn must not drive the card into one backend refresh
  // per minute. Only entities explicitly returned by the backend are watched.
  const selectiveCard = new Card();
  selectiveCard._watchedEntities = ["weather.home"];
  let selectiveRefreshes = 0;
  selectiveCard._scheduleStateRefresh = () => { selectiveRefreshes += 1; };
  const sameWeather = { state: "sunny" };
  selectiveCard._hass = { states: { "weather.home": sameWeather, "sensor.noisy": { state: "1" } } };
  selectiveCard.hass = { states: { "weather.home": sameWeather, "sensor.noisy": { state: "2" } } };
  assert.equal(selectiveRefreshes, 0, "unrelated HA state changes must not schedule a JackenBerater refresh");
  selectiveCard.hass = { states: { "weather.home": { state: "cloudy" }, "sensor.noisy": { state: "2" } } };
  assert.equal(selectiveRefreshes, 1, "watched weather/calendar/input changes must schedule a refresh");

  // A profile change made on another device must be noticed without waiting
  // for the five-minute full-refresh fallback. The lightweight revision token
  // schedules a normal throttled refresh only when it actually changes.
  const revisionCard = new Card();
  revisionCard._hass = { language: "de" };
  revisionCard._profileRevision = 4;
  revisionCard._render = () => {};
  let revisionRefreshes = 0;
  revisionCard._scheduleStateRefresh = () => { revisionRefreshes += 1; };
  revisionCard._send = async (type) => {
    assert.equal(type, "jackenberater/profile_revision");
    return { revision: 5 };
  };
  await revisionCard._checkProfileRevision();
  assert.equal(revisionCard._profileRevision, 4, "revision poll must not mark unapplied profile data as current");
  assert.equal(revisionCard._seenProfileRevision, "5", "revision poll should remember the newest server token");
  assert.equal(revisionRefreshes, 1, "remote profile changes must schedule a card refresh promptly");
  await revisionCard._checkProfileRevision();
  assert.equal(revisionRefreshes, 2, "a failed/unapplied refresh must remain retryable on the next revision poll");

  // Voluntary feedback before a predicted future jacket switch can only rate
  // the current/start state; the future state has not been experienced yet.
  const pausedFeedbackCard = new Card();
  pausedFeedbackCard._preview = { latest_session: session };
  pausedFeedbackCard._session = session;
  pausedFeedbackCard._manualFeedbackVisible = false;
  pausedFeedbackCard._t = (key) => key;
  const pausedDetails = pausedFeedbackCard._details(
    { reasons: [], rain_status: "none", current_temperature_c: 15, current_wind_kmh: 5, horizon_hours: 1 },
    { confidence: 0.5, total_feedback: 0, learning_enabled: false },
    [],
  );
  assert.doesNotMatch(pausedDetails, /data-action="manual-feedback"/, "paused learning must not offer voluntary feedback");

  const futureFeedbackCard = new Card();
  futureFeedbackCard._t = (key) => key;
  futureFeedbackCard._refresh = async () => {};
  futureFeedbackCard._render = () => {};
  let feedbackPayload = null;
  futureFeedbackCard._send = async (type, payload) => {
    if (type === "jackenberater/feedback") feedbackPayload = payload;
    return { ok: true };
  };
  const futureSession = {
    id: "future123",
    recommendation: {
      jacket_now: "light",
      jacket_later: "warm",
      later_at: "2099-09-01T18:00:00+00:00",
    },
  };
  await futureFeedbackCard._feedback(futureSession, "perfect", true);
  assert.equal(feedbackPayload.phase, "start", "voluntary feedback must not confirm an unexperienced future jacket change");

  // Reconfiguring a connected card must not orphan the 30-second revision
  // interval (or a pending state-refresh timeout). After disconnect, every
  // interval created by this card instance must be gone.
  const originalSetInterval = context.setInterval;
  const originalClearInterval = context.clearInterval;
  const originalSetTimeout = context.setTimeout;
  const originalClearTimeout = context.clearTimeout;
  let timerSeq = 0;
  const activeIntervals = new Set();
  const activeTimeouts = new Set();
  context.setInterval = () => { const id = ++timerSeq; activeIntervals.add(id); return id; };
  context.clearInterval = (id) => { activeIntervals.delete(id); };
  context.setTimeout = () => { const id = ++timerSeq; activeTimeouts.add(id); return id; };
  context.clearTimeout = (id) => { activeTimeouts.delete(id); };
  try {
    const timerCard = new Card();
    timerCard._render = () => {};
    timerCard.isConnected = true;
    timerCard.connectedCallback();
    assert.equal(activeIntervals.size, 2, "connected card should own full-refresh and revision intervals");
    timerCard._stateRefreshTimer = context.setTimeout(() => {}, 1000);
    timerCard.setConfig({ type: "custom:jackenberater-card" });
    assert.equal(activeIntervals.size, 2, "setConfig must replace, not leak, the revision interval");
    assert.equal(activeTimeouts.size, 0, "setConfig must clear an outstanding state-refresh timeout");
    timerCard.disconnectedCallback();
    assert.equal(activeIntervals.size, 0, "disconnect after reconfiguration must leave no orphan intervals");
  } finally {
    context.setInterval = originalSetInterval;
    context.clearInterval = originalClearInterval;
    context.setTimeout = originalSetTimeout;
    context.clearTimeout = originalClearTimeout;
  }


  // A revision token seen while no full profile state has been applied must
  // trigger a full refresh, not become the local applied baseline by itself.
  const emptyRevisionCard = new Card();
  emptyRevisionCard._hass = { language: "de" };
  emptyRevisionCard._profileRevision = null;
  emptyRevisionCard._render = () => {};
  let emptyRevisionRefreshes = 0;
  emptyRevisionCard._scheduleStateRefresh = () => { emptyRevisionRefreshes += 1; };
  emptyRevisionCard._send = async () => ({ revision: "runtime-x:7" });
  await emptyRevisionCard._checkProfileRevision();
  assert.equal(emptyRevisionCard._profileRevision, null, "seeing a revision without full state must not mark it applied");
  assert.equal(emptyRevisionCard._seenProfileRevision, "runtime-x:7");
  assert.equal(emptyRevisionRefreshes, 1, "empty card state must request a full refresh after seeing server revision");

  // Profile changes invalidate in-flight async results. An old profile A result
  // may finish after B was selected, but it must never overwrite B's preview.
  const raceCard = new Card();
  raceCard._hass = { language: "de" };
  raceCard._render = () => {};
  raceCard._autoShared = true;
  raceCard._selectedProfile = "A";
  raceCard._requestGeneration = 1;
  const deferred = () => {
    let resolve;
    const promise = new Promise(r => { resolve = r; });
    return { promise, resolve };
  };
  const previewA = deferred();
  const previewB = deferred();
  raceCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return {
        profiles: [{ id: "A" }, { id: "B" }], shared_account: true,
        entry_id: "entry", profile_revision: "runtime:1", watched_entities: [],
      };
    }
    if (type === "jackenberater/preview") {
      return raceCard._selectedProfile === "A" ? previewA.promise : previewB.promise;
    }
    throw new Error(`unexpected ${type}`);
  };
  const oldRefresh = raceCard._refresh();
  await Promise.resolve();
  await Promise.resolve();
  raceCard._requestGeneration += 1;
  raceCard._loading = false;
  raceCard._loadingGeneration = null;
  raceCard._selectedProfile = "B";
  const newRefresh = raceCard._refresh();
  await Promise.resolve();
  await Promise.resolve();
  previewB.resolve({ recommendation: { marker: "B" }, profile: { setup_complete: true }, feedback: [] });
  await newRefresh;
  previewA.resolve({ recommendation: { marker: "A" }, profile: { setup_complete: true }, feedback: [] });
  await oldRefresh;
  assert.equal(raceCard._selectedProfile, "B");
  assert.equal(raceCard._preview?.recommendation?.marker, "B", "stale A response must not render after switching to B");

  // setConfig invalidates an in-flight request and starts a full refresh for the
  // new config as soon as hass is available. The late old response is ignored.
  const configRaceCard = new Card();
  configRaceCard._hass = { language: "de" };
  configRaceCard._render = () => {};
  configRaceCard._config = { entry_id: "old" };
  configRaceCard._requestGeneration = 1;
  const oldProfiles = deferred();
  configRaceCard._send = async (type) => {
    if (type === "jackenberater/profiles" && configRaceCard._config?.entry_id === "old") return oldProfiles.promise;
    if (type === "jackenberater/profiles") {
      return { profiles: [], shared_account: false, entry_id: "new", profile_revision: "new-runtime:0", watched_entities: ["weather.new"] };
    }
    if (type === "jackenberater/preview") return { recommendation: { marker: "new" }, profile: { setup_complete: true }, feedback: [] };
    throw new Error(`unexpected ${type}`);
  };
  const staleRefresh = configRaceCard._refresh();
  await Promise.resolve();
  configRaceCard.setConfig({ type: "custom:jackenberater-card", entry_id: "new" });
  await Promise.resolve();
  await Promise.resolve();
  oldProfiles.resolve({ profiles: [], shared_account: false, entry_id: "old", profile_revision: "old-runtime:5", watched_entities: ["weather.old"] });
  await staleRefresh;
  // Let the refresh started by setConfig settle.
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
  assert.equal(configRaceCard._entryId, "new", "stale config response must not restore old entry metadata");
  assert.deepEqual(configRaceCard._watchedEntities, ["weather.new"]);
  assert.equal(configRaceCard._preview?.recommendation?.marker, "new", "setConfig must load and keep the new preview");


  // open_session responses are generation/profile bound just like preview. A
  // late response for A must never overwrite B after a shared-profile switch.
  const openRaceCard = new Card();
  openRaceCard._hass = { language: "de" };
  openRaceCard._render = () => {};
  openRaceCard._autoShared = true;
  openRaceCard._isAdmin = true;
  openRaceCard._selectedProfile = "A";
  openRaceCard._requestGeneration = 10;
  openRaceCard._config = { entry_id: "entry" };
  openRaceCard._preview = {
    recommendation: { marker: "A", simulation_active: false },
    profile: { setup_complete: true }, feedback: [],
  };
  const openA = deferred();
  openRaceCard._send = async (type) => {
    if (type === "jackenberater/open_session") return openA.promise;
    throw new Error(`unexpected ${type}`);
  };
  const staleOpen = openRaceCard._openAdvice();
  await Promise.resolve();
  openRaceCard._requestGeneration += 1;
  openRaceCard._selectedProfile = "B";
  openRaceCard._open = false;
  openRaceCard._session = null;
  openRaceCard._preview = {
    recommendation: { marker: "B", simulation_active: false },
    profile: { setup_complete: true }, feedback: [],
  };
  openA.resolve({
    session: { id: "sessA" }, recommendation: { marker: "A-late" },
    feedback: [{ id: "feedbackA" }], profile_revision: "runtime:d1:p1",
  });
  await staleOpen;
  assert.equal(openRaceCard._selectedProfile, "B");
  assert.equal(openRaceCard._preview.recommendation.marker, "B", "late open_session(A) must not overwrite B");
  assert.equal(openRaceCard._session, null, "late open_session(A) must not install A's session under B");

  // The manual-feedback open_session path has the same generation guard.
  const manualRaceCard = new Card();
  manualRaceCard._hass = { language: "de" };
  manualRaceCard._render = () => {};
  manualRaceCard._selectedProfile = "A";
  manualRaceCard._requestGeneration = 3;
  manualRaceCard._config = { entry_id: "entry" };
  manualRaceCard._preview = { recommendation: { marker: "A" }, feedback: [] };
  const manualA = deferred();
  manualRaceCard._send = async (type) => {
    if (type === "jackenberater/open_session") return manualA.promise;
    throw new Error(`unexpected ${type}`);
  };
  const staleManual = manualRaceCard._prepareManualFeedback();
  await Promise.resolve();
  manualRaceCard._requestGeneration += 1;
  manualRaceCard._selectedProfile = "B";
  manualRaceCard._preview = { recommendation: { marker: "B" }, feedback: [] };
  manualA.resolve({ session: { id: "old-A" }, recommendation: { marker: "A-late" }, feedback: [] });
  await staleManual;
  assert.equal(manualRaceCard._preview.recommendation.marker, "B");
  assert.notEqual(manualRaceCard._session?.id, "old-A", "stale manual feedback session must be discarded");

  // A revision poll started for an old profile/config must be ignored after a
  // generation change and must not schedule a redundant refresh.
  const revisionRaceCard = new Card();
  revisionRaceCard._hass = { language: "de" };
  revisionRaceCard._config = { entry_id: "entry" };
  revisionRaceCard._selectedProfile = "A";
  revisionRaceCard._requestGeneration = 4;
  revisionRaceCard._profileRevision = "runtime:d0:p0";
  let staleRevisionRefreshes = 0;
  revisionRaceCard._scheduleStateRefresh = () => { staleRevisionRefreshes += 1; };
  const revisionA = deferred();
  revisionRaceCard._send = async (type) => {
    if (type === "jackenberater/profile_revision") return revisionA.promise;
    throw new Error(`unexpected ${type}`);
  };
  const stalePoll = revisionRaceCard._checkProfileRevision();
  await Promise.resolve();
  revisionRaceCard._requestGeneration += 1;
  revisionRaceCard._selectedProfile = "B";
  revisionA.resolve({ revision: "runtime:d9:p9" });
  await stalePoll;
  assert.equal(staleRevisionRefreshes, 0, "stale revision poll must not refresh the new profile");
  assert.notEqual(revisionRaceCard._seenProfileRevision, "runtime:d9:p9");

  // Preview returns the post-advice revision. If season bootstrap changes the
  // model during preview, that newer token must become the applied baseline.
  const bootstrapRevisionCard = new Card();
  bootstrapRevisionCard._hass = { language: "de" };
  bootstrapRevisionCard._render = () => {};
  bootstrapRevisionCard._config = { entry_id: "entry" };
  bootstrapRevisionCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return { profiles: [], shared_account: false, entry_id: "entry", profile_revision: "runtime:p:4", watched_entities: [] };
    }
    if (type === "jackenberater/preview") {
      return { recommendation: { marker: "seeded" }, profile: { setup_complete: true }, feedback: [], profile_revision: "runtime:p:5" };
    }
    throw new Error(`unexpected ${type}`);
  };
  await bootstrapRevisionCard._refresh();
  assert.equal(bootstrapRevisionCard._profileRevision, "runtime:p:5", "post-advice revision must prevent redundant bootstrap refresh");



  // Async actions that were started for profile A must not mutate profile B's
  // local UI state when they finish after a shared-profile switch.
  const actionRaceCard = new Card();
  actionRaceCard._hass = { language: "de" };
  actionRaceCard._render = () => {};
  actionRaceCard._config = { entry_id: "entry" };
  actionRaceCard._selectedProfile = "A";
  actionRaceCard._requestGeneration = 1;
  actionRaceCard._preview = { recommendation: { jacket_now: "light", jacket_later: "light" } };
  const feedbackDone = deferred();
  actionRaceCard._send = async (type) => {
    if (type === "jackenberater/feedback") return feedbackDone.promise;
    throw new Error(`unexpected ${type}`);
  };
  const oldSession = { id: "sessA", recommendation: { jacket_now: "light", jacket_later: "light" } };
  const staleFeedback = actionRaceCard._feedback(oldSession, "perfect", false);
  await Promise.resolve();
  actionRaceCard._requestGeneration += 1;
  actionRaceCard._selectedProfile = "B";
  actionRaceCard._session = { id: "sessB" };
  actionRaceCard._manualFeedbackVisible = true;
  actionRaceCard._notice = "";
  feedbackDone.resolve({});
  await staleFeedback;
  assert.equal(actionRaceCard._selectedProfile, "B");
  assert.equal(actionRaceCard._session?.id, "sessB", "late feedback(A) must not clear B's session");
  assert.equal(actionRaceCard._manualFeedbackVisible, true, "late feedback(A) must not close B's manual panel");
  assert.equal(actionRaceCard._notice, "", "late feedback(A) must not show A's success notice on B");

  const setupRaceCard = new Card();
  setupRaceCard._hass = { language: "de" };
  setupRaceCard._render = () => {};
  setupRaceCard._config = { entry_id: "entry" };
  setupRaceCard._selectedProfile = "A";
  setupRaceCard._requestGeneration = 2;
  const setupDone = deferred();
  setupRaceCard._send = async (type) => {
    if (type === "jackenberater/profile_setup") return setupDone.promise;
    throw new Error(`unexpected ${type}`);
  };
  const staleSetup = setupRaceCard._saveSetup();
  await Promise.resolve();
  setupRaceCard._requestGeneration += 1;
  setupRaceCard._selectedProfile = "B";
  setupRaceCard._open = true;
  setupDone.resolve({});
  await staleSetup;
  assert.equal(setupRaceCard._open, true, "late setup(A) must not close B's detail/setup state");

  const maintenanceRaceCard = new Card();
  maintenanceRaceCard._hass = { language: "de" };
  maintenanceRaceCard._render = () => {};
  maintenanceRaceCard._config = { entry_id: "entry" };
  maintenanceRaceCard._selectedProfile = "A";
  maintenanceRaceCard._requestGeneration = 3;
  const maintenanceDone = deferred();
  maintenanceRaceCard._send = async (type) => {
    if (type === "jackenberater/profile_maintenance") return maintenanceDone.promise;
    throw new Error(`unexpected ${type}`);
  };
  const staleMaintenance = maintenanceRaceCard._maintainProfile("learning_off");
  await Promise.resolve();
  maintenanceRaceCard._requestGeneration += 1;
  maintenanceRaceCard._selectedProfile = "B";
  maintenanceRaceCard._notice = "B-notice";
  maintenanceDone.resolve({});
  await staleMaintenance;
  assert.equal(maintenanceRaceCard._notice, "B-notice", "late maintenance(A) must not overwrite B's notice");

  // The revision-poll lock belongs to the generation that acquired it. An old
  // poll finishing after setConfig/profile change must not unlock a newer poll.
  const pollOwnerCard = new Card();
  pollOwnerCard._hass = { language: "de" };
  pollOwnerCard._config = { entry_id: "entry" };
  pollOwnerCard._selectedProfile = "A";
  pollOwnerCard._requestGeneration = 1;
  pollOwnerCard._profileRevision = "old:0";
  pollOwnerCard._scheduleStateRefresh = () => {};
  const pollOld = deferred();
  const pollNew = deferred();
  let pollCalls = 0;
  pollOwnerCard._send = async (type) => {
    assert.equal(type, "jackenberater/profile_revision");
    pollCalls += 1;
    return pollCalls === 1 ? pollOld.promise : pollNew.promise;
  };
  const oldPoll = pollOwnerCard._checkProfileRevision();
  await Promise.resolve();
  pollOwnerCard._requestGeneration = 2;
  pollOwnerCard._selectedProfile = "B";
  pollOwnerCard._revisionCheckingGeneration = null;
  const newPoll = pollOwnerCard._checkProfileRevision();
  await Promise.resolve();
  assert.equal(pollOwnerCard._revisionCheckingGeneration, 2);
  pollOld.resolve({ revision: "old:1" });
  await oldPoll;
  assert.equal(pollOwnerCard._revisionCheckingGeneration, 2, "old poll must not release new poll's lock");
  pollNew.resolve({ revision: "new:1" });
  await newPoll;
  assert.equal(pollOwnerCard._revisionCheckingGeneration, null);

  // Access revoked while a foreign profile is selected: revision polling should
  // nudge a full metadata refresh so the recovery-capable profiles endpoint can
  // clear the stale selection promptly.
  const revokedSharedCard = new Card();
  revokedSharedCard._hass = { language: "de" };
  revokedSharedCard._config = { entry_id: "entry" };
  revokedSharedCard._selectedProfile = "foreign";
  revokedSharedCard._requestGeneration = 5;
  revokedSharedCard._profileRevision = "shared:old";
  let revokedRefreshes = 0;
  revokedSharedCard._scheduleStateRefresh = () => { revokedRefreshes += 1; };
  revokedSharedCard._send = async () => { throw new Error("shared_profile_access_denied"); };
  await revokedSharedCard._checkProfileRevision();
  assert.equal(revokedRefreshes, 1, "revoked shared access should trigger profiles recovery refresh");

  // A shared profile directory that changes between profiles and preview must
  // not be marked current by the newer preview token. The card immediately
  // repeats the full transaction and renders only the coherent second snapshot.
  const directoryRaceCard = new Card();
  directoryRaceCard._hass = { language: "de" };
  directoryRaceCard._render = () => {};
  directoryRaceCard._config = { entry_id: "entry" };
  directoryRaceCard._selectedProfile = "A";
  let directoryProfilesCalls = 0;
  let directoryPreviewCalls = 0;
  directoryRaceCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      directoryProfilesCalls += 1;
      const dir = directoryProfilesCalls === 1 ? "runtime:d:1" : "runtime:d:2";
      return {
        profiles: [{ id: "A" }, { id: "B" }], shared_account: true,
        entry_id: "entry", profile_revision: `${dir}:p1`, directory_revision: dir,
        watched_entities: [],
      };
    }
    if (type === "jackenberater/preview") {
      directoryPreviewCalls += 1;
      const first = directoryPreviewCalls === 1;
      return {
        recommendation: { marker: first ? "stale-directory" : "fresh-directory" },
        profile: { setup_complete: true }, feedback: [],
        profile_revision: first ? "runtime:d:2:p1" : "runtime:d:2:p1",
        directory_revision: "runtime:d:2",
      };
    }
    throw new Error(`unexpected ${type}`);
  };
  await directoryRaceCard._refresh();
  for (let i = 0; i < 12; i += 1) await Promise.resolve();
  assert.equal(directoryProfilesCalls, 2, "directory mismatch should repeat profiles transaction once");
  assert.equal(directoryPreviewCalls, 2, "directory mismatch should discard stale preview and retry");
  assert.equal(directoryRaceCard._preview?.recommendation?.marker, "fresh-directory");

  // Same-profile actions need their own generation too. A slow S1 feedback
  // response must not close or relabel a newer manual S2 feedback surface.
  const sameProfileActionCard = new Card();
  sameProfileActionCard._hass = { language: "de" };
  sameProfileActionCard._render = () => {};
  sameProfileActionCard._config = { entry_id: "entry" };
  sameProfileActionCard._selectedProfile = "A";
  sameProfileActionCard._requestGeneration = 1;
  sameProfileActionCard._preview = {
    recommendation: { jacket_now: "light", jacket_later: "light" }, feedback: [],
  };
  const oldSameProfileFeedback = deferred();
  sameProfileActionCard._send = async (type) => {
    if (type === "jackenberater/feedback") return oldSameProfileFeedback.promise;
    if (type === "jackenberater/open_session") {
      return {
        session: { id: "S2", recommendation: { jacket_now: "light", jacket_later: "light" } },
        recommendation: { jacket_now: "light", jacket_later: "light" }, feedback: [],
      };
    }
    throw new Error(`unexpected ${type}`);
  };
  const oldSameAction = sameProfileActionCard._feedback(
    { id: "S1", recommendation: { jacket_now: "light", jacket_later: "light" } },
    "perfect", false,
  );
  await Promise.resolve();
  await sameProfileActionCard._prepareManualFeedback();
  assert.equal(sameProfileActionCard._session?.id, "S2");
  assert.equal(sameProfileActionCard._manualFeedbackVisible, true);
  sameProfileActionCard._notice = "";
  oldSameProfileFeedback.resolve({});
  await oldSameAction;
  assert.equal(sameProfileActionCard._session?.id, "S2", "old S1 response must not clear S2");
  assert.equal(sameProfileActionCard._manualFeedbackVisible, true, "old S1 response must not close S2 UI");
  assert.equal(sameProfileActionCard._notice, "", "old S1 response must not show stale success notice");


  // View ordering is shared between background preview refreshes and explicit
  // open_session/manual-feedback requests. Whichever request starts later owns
  // the visible recommendation; an older response must never roll it back.
  const oldOpenAfterRefreshCard = new Card();
  oldOpenAfterRefreshCard._hass = { language: "de" };
  oldOpenAfterRefreshCard._render = () => {};
  oldOpenAfterRefreshCard._config = { entry_id: "entry" };
  oldOpenAfterRefreshCard._preview = {
    profile: { setup_complete: true },
    recommendation: { marker: "initial", jacket_now: "light", jacket_later: "light" },
    feedback: [],
  };
  const staleOpenResponse = deferred();
  oldOpenAfterRefreshCard._send = async (type) => {
    if (type === "jackenberater/open_session") return staleOpenResponse.promise;
    if (type === "jackenberater/profiles") {
      return { profiles: [], shared_account: false, entry_id: "entry", profile_revision: "r:1", watched_entities: [] };
    }
    if (type === "jackenberater/preview") {
      return { profile: { setup_complete: true }, recommendation: { marker: "newer", jacket_now: "light", jacket_later: "light" }, feedback: [], profile_revision: "r:2" };
    }
    throw new Error(`unexpected ${type}`);
  };
  const oldOpenRequest = oldOpenAfterRefreshCard._openAdvice();
  await Promise.resolve();
  await oldOpenAfterRefreshCard._refresh();
  assert.equal(oldOpenAfterRefreshCard._preview?.recommendation?.marker, "newer");
  staleOpenResponse.resolve({
    session: { id: "old-session" },
    recommendation: { marker: "older-open", jacket_now: "light", jacket_later: "light" },
    feedback: [], profile_revision: "r:1",
  });
  await oldOpenRequest;
  assert.equal(
    oldOpenAfterRefreshCard._preview?.recommendation?.marker,
    "newer",
    "older open_session response must not overwrite a later-started full refresh",
  );
  assert.notEqual(oldOpenAfterRefreshCard._session?.id, "old-session");

  const oldRefreshAfterOpenCard = new Card();
  oldRefreshAfterOpenCard._hass = { language: "de" };
  oldRefreshAfterOpenCard._render = () => {};
  oldRefreshAfterOpenCard._config = { entry_id: "entry" };
  oldRefreshAfterOpenCard._preview = {
    profile: { setup_complete: true },
    recommendation: { marker: "initial", jacket_now: "light", jacket_later: "light" },
    feedback: [],
  };
  const stalePreviewResponse = deferred();
  oldRefreshAfterOpenCard._send = async (type) => {
    if (type === "jackenberater/profiles") {
      return { profiles: [], shared_account: false, entry_id: "entry", profile_revision: "r:1", watched_entities: [] };
    }
    if (type === "jackenberater/preview") return stalePreviewResponse.promise;
    if (type === "jackenberater/open_session") {
      return {
        session: { id: "new-session" },
        recommendation: { marker: "newer-open", jacket_now: "light", jacket_later: "light" },
        feedback: [], profile_revision: "r:2",
      };
    }
    throw new Error(`unexpected ${type}`);
  };
  const oldRefreshRequest = oldRefreshAfterOpenCard._refresh();
  await Promise.resolve();
  await oldRefreshAfterOpenCard._openAdvice();
  assert.equal(oldRefreshAfterOpenCard._preview?.recommendation?.marker, "newer-open");
  stalePreviewResponse.resolve({
    profile: { setup_complete: true },
    recommendation: { marker: "older-refresh", jacket_now: "light", jacket_later: "light" },
    feedback: [], profile_revision: "r:1",
  });
  await oldRefreshRequest;
  assert.equal(
    oldRefreshAfterOpenCard._preview?.recommendation?.marker,
    "newer-open",
    "older background refresh must not overwrite a later-started open_session result",
  );
  assert.equal(oldRefreshAfterOpenCard._session?.id, "new-session");

  const staleManualAfterRefreshCard = new Card();
  staleManualAfterRefreshCard._hass = { language: "de" };
  staleManualAfterRefreshCard._render = () => {};
  staleManualAfterRefreshCard._config = { entry_id: "entry" };
  staleManualAfterRefreshCard._manualFeedbackVisible = false;
  staleManualAfterRefreshCard._preview = {
    profile: { setup_complete: true },
    recommendation: { marker: "initial", jacket_now: "light", jacket_later: "light" },
    feedback: [],
  };
  const staleManualResponse = deferred();
  staleManualAfterRefreshCard._send = async (type) => {
    if (type === "jackenberater/open_session") return staleManualResponse.promise;
    if (type === "jackenberater/profiles") {
      return { profiles: [], shared_account: false, entry_id: "entry", profile_revision: "r:1", watched_entities: [] };
    }
    if (type === "jackenberater/preview") {
      return { profile: { setup_complete: true }, recommendation: { marker: "manual-newer", jacket_now: "light", jacket_later: "light" }, feedback: [], profile_revision: "r:2" };
    }
    throw new Error(`unexpected ${type}`);
  };
  const oldManualRequest = staleManualAfterRefreshCard._prepareManualFeedback();
  await Promise.resolve();
  await staleManualAfterRefreshCard._refresh();
  staleManualResponse.resolve({
    session: { id: "stale-manual" },
    recommendation: { marker: "manual-old", jacket_now: "light", jacket_later: "light" },
    feedback: [], profile_revision: "r:1",
  });
  await oldManualRequest;
  assert.equal(staleManualAfterRefreshCard._preview?.recommendation?.marker, "manual-newer");
  assert.notEqual(staleManualAfterRefreshCard._session?.id, "stale-manual");
  assert.equal(staleManualAfterRefreshCard._manualFeedbackVisible, false);

  // open_session is an action snapshot, not a full profiles+preview snapshot.
  // A newer action revision may update recommendation/session immediately, but
  // it must not be marked as the fully applied profile/directory revision.
  const partialRevisionCard = new Card();
  partialRevisionCard._hass = { language: "de" };
  partialRevisionCard._render = () => {};
  partialRevisionCard._config = { entry_id: "entry" };
  partialRevisionCard._profileRevision = "r:1";
  partialRevisionCard._seenProfileRevision = "r:1";
  partialRevisionCard._profiles = [{ id: "A", name: "A-old" }, { id: "B", name: "B-old" }];
  partialRevisionCard._preview = {
    profile: { setup_complete: true, total_feedback: 10, learning_progress: 0.5 },
    recommendation: { marker: "old", jacket_now: "light", jacket_later: "light" },
    feedback: [],
  };
  let partialRefreshSchedules = 0;
  partialRevisionCard._scheduleStateRefresh = () => { partialRefreshSchedules += 1; };
  partialRevisionCard._send = async (type) => {
    if (type === "jackenberater/open_session") {
      return {
        session: { id: "action-session", feedback: null },
        profile: { setup_complete: true, total_feedback: 11, learning_progress: 0.6 },
        recommendation: { marker: "action-new", jacket_now: "light", jacket_later: "light" },
        feedback: [],
        profile_revision: "r:2",
        directory_revision: "d:2",
      };
    }
    throw new Error(`unexpected ${type}`);
  };
  await partialRevisionCard._openAdvice();
  assert.equal(partialRevisionCard._preview?.recommendation?.marker, "action-new");
  assert.equal(partialRevisionCard._preview?.profile?.total_feedback, 11, "action may apply returned profile metadata opportunistically");
  assert.equal(partialRevisionCard._profileRevision, "r:1", "open_session must not mark a partial action snapshot as fully applied");
  assert.equal(partialRevisionCard._seenProfileRevision, "r:2", "newer action revision should be remembered as seen");
  assert.equal(partialRefreshSchedules, 1, "newer partial action revision must schedule a full snapshot refresh");
  assert.deepEqual(
    partialRevisionCard._profiles.map((item) => item.name),
    ["A-old", "B-old"],
    "open_session must not pretend it replaced the shared profile directory",
  );

  // Manual feedback uses the same partial-snapshot rule.
  const partialManualCard = new Card();
  partialManualCard._hass = { language: "de" };
  partialManualCard._render = () => {};
  partialManualCard._config = { entry_id: "entry" };
  partialManualCard._profileRevision = "r:3";
  partialManualCard._seenProfileRevision = "r:3";
  partialManualCard._preview = {
    profile: { setup_complete: true, total_feedback: 20 },
    recommendation: { marker: "manual-old", jacket_now: "light", jacket_later: "light" },
    feedback: [],
  };
  let manualRefreshSchedules = 0;
  partialManualCard._scheduleStateRefresh = () => { manualRefreshSchedules += 1; };
  partialManualCard._send = async (type) => {
    if (type === "jackenberater/open_session") {
      return {
        session: { id: "manual-current", feedback: null },
        profile: { setup_complete: true, total_feedback: 21 },
        recommendation: { marker: "manual-action", jacket_now: "light", jacket_later: "light" },
        feedback: [],
        profile_revision: "r:4",
      };
    }
    throw new Error(`unexpected ${type}`);
  };
  await partialManualCard._prepareManualFeedback();
  assert.equal(partialManualCard._profileRevision, "r:3");
  assert.equal(partialManualCard._seenProfileRevision, "r:4");
  assert.equal(partialManualCard._manualFeedbackVisible, true);
  assert.equal(manualRefreshSchedules, 1);

  // Mutating actions are single-flight. A fast double click on Undo must send
  // only one backend request, otherwise two historical learning changes could
  // be reverted even though the button says singular "last learning change".
  const undoSingleFlightCard = new Card();
  undoSingleFlightCard._hass = { language: "de" };
  undoSingleFlightCard._render = () => {};
  undoSingleFlightCard._config = { entry_id: "entry" };
  undoSingleFlightCard._selectedProfile = "A";
  undoSingleFlightCard._requestGeneration = 1;
  undoSingleFlightCard._refresh = async () => {};
  undoSingleFlightCard._t = (key) => key;
  const undoDone = deferred();
  let undoCalls = 0;
  undoSingleFlightCard._send = async (type) => {
    if (type === "jackenberater/profile_maintenance") {
      undoCalls += 1;
      return undoDone.promise;
    }
    throw new Error(`unexpected ${type}`);
  };
  const undoFirst = undoSingleFlightCard._maintainProfile("undo");
  const undoSecond = undoSingleFlightCard._maintainProfile("undo");
  await Promise.resolve();
  assert.equal(undoCalls, 1, "double-click Undo must send exactly one mutating request");
  undoDone.resolve({ ok: true });
  await Promise.all([undoFirst, undoSecond]);

  // Feedback uses the same single-flight rule per session. The backend already
  // rejects a duplicate, but the card should not emit the redundant request or
  // replace a successful notice with "already submitted".
  const feedbackSingleFlightCard = new Card();
  feedbackSingleFlightCard._hass = { language: "de" };
  feedbackSingleFlightCard._render = () => {};
  feedbackSingleFlightCard._config = { entry_id: "entry" };
  feedbackSingleFlightCard._selectedProfile = "A";
  feedbackSingleFlightCard._requestGeneration = 1;
  feedbackSingleFlightCard._refresh = async () => {};
  feedbackSingleFlightCard._t = (key) => key;
  const feedbackSession = {
    id: "single-flight-session",
    recommendation: { jacket_now: "light", jacket_later: "light" },
  };
  feedbackSingleFlightCard._session = feedbackSession;
  const feedbackFlightDone = deferred();
  let feedbackFlightCalls = 0;
  feedbackSingleFlightCard._send = async (type) => {
    if (type === "jackenberater/feedback") {
      feedbackFlightCalls += 1;
      return feedbackFlightDone.promise;
    }
    throw new Error(`unexpected ${type}`);
  };
  const feedbackFirst = feedbackSingleFlightCard._feedback(feedbackSession, "perfect", true);
  const feedbackSecond = feedbackSingleFlightCard._feedback(feedbackSession, "perfect", true);
  await Promise.resolve();
  assert.equal(feedbackFlightCalls, 1, "double-click feedback must send exactly one request per session");
  feedbackFlightDone.resolve({ ok: true });
  await Promise.all([feedbackFirst, feedbackSecond]);
  assert.equal(feedbackSingleFlightCard._notice, "submitted");

  console.log("frontend session contract OK");
})().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
