# JackenBerater – Projektkontext

Dieses lokale Projekt wurde ursprünglich am 2. September 2026 aus dem ChatGPT-Projekt „Jackenberater“ übernommen und seitdem als Home-Assistant-Custom-Integration weiterentwickelt.

- Quellprojekt: https://chatgpt.com/g/g-p-6a983d3dc0288191b241cbfcd430cacf-jackenberater/project
- Übernommener Chat: „Kältegefühl Tracken“
- Aktueller Entwicklungsstand: **JackenBerater v0.3.2**
- CI prüft den deklarierten Mindeststand Home Assistant 2026.6.0, einen reproduzierbar gepinnten aktuellen Stand und zusätzlich den jeweils neuesten verfügbaren HA-Teststack unter Python 3.14.

## Zweck

JackenBerater erzeugt aus aktuellem Wetter, stündlichem Forecast, persönlichem Wärmeempfinden und optionalem Arbeits-/Kalenderkontext eine nachvollziehbare Jacken- und Regenschutzempfehlung. Das persönliche Modell bleibt kompakt und lernt inkrementell, ohne eine jahrelange Wetter- oder Feedbackhistorie zu speichern.

## Aktuelle Produktregeln

- Normale Betrachtung: 9 reale Stunden, bei relevanten Änderungen bis etwa 12 Stunden; Kalender-/Arbeitskontext kann bis maximal 16 Stunden erweitern.
- Aktuelle Wetterquelle ist zuhause, außer innerhalb einer tatsächlichen konfigurierten Arbeitszeit; dann ist das Arbeitswetter maßgeblich. Ein ausgefallenes Zuhause-Wetter darf eine gesunde Arbeitsquelle nicht blockieren.
- Arbeitsforecast ersetzt Zuhause-Forecast nur innerhalb der geplanten Arbeitsfenster. Fehlende Arbeitsdaten werden nicht still mit Zuhause-Wetter gefüllt und müssen sichtbar gewarnt werden.
- Eine sichtbare Karte erzeugt keine Session. Erst bewusstes Aufklappen erzeugt eine Nutzungssession; das Infofeld allein nicht.
- Nahezu identische bewusste Öffnungen desselben Profils innerhalb von zehn Minuten zählen profilweit als eine reale Jackenentscheidung, unabhängig vom Gerät/Login.
- Fälliges Feedback gehört zum Profil und kann deshalb auf einem freigegebenen Wandtablet beantwortet werden, auch wenn die Session am persönlichen Gerät entstand.
- Nicht-freiwilliges Feedback ist serverseitig an `request_feedback` und `ready_at` gebunden; freiwilliges Feedback darf bewusst sofort erfolgen.
- Shared-/Wandtablet-Rechte stammen ausschließlich aus `shared_user_ids` der Integration. Lovelace-`shared: true` ist keine Berechtigung und wird nicht als Shared-Modus ausgewertet.
- `general_offset_c` ist der ganzjährige persönliche Grundwert. Winter, Frühling, Sommer und Herbst sind eigenständige Offsets dazu; normales thermisches Feedback verschiebt Main nicht direkt, sondern nur die aktive Saison beziehungsweise während der 30-Tage-Überblendung die beiden direkten Nachbarsaisons.
- Saisonale Lernraten hängen ausschließlich von der eigenen echten Saison-Evidenz ab und frieren auch bei hoher alter Evidenz nicht vollständig ein. `Perfekt` bestätigt die beteiligte Saison ohne thermische Offsetkorrektur; `Nicht genutzt`, reine Timing-/Grenzenkorrekturen und thermische No-ops erzeugen keine Saison-Evidenz.
- Eine erstmals auftretende Saison übernimmt beim ersten Übergang einmalig nur den Offset ihrer direkten Vorgängersaison. Wird die komplette Übergangszone verpasst, wird dieses Seeding beim ersten späteren Zugriff in der neuen Saison nachgeholt. RunningStats, Evidenz und Lernhistorie werden nicht kopiert; in späteren Jahren wird niemals erneut geseedet. Sind mehrere ganze Saisons übersprungen und ist die direkte Vorgängersaison unbekannt, wird keine rückwirkende Seed-Kette erfunden: nur die aktuell erreichte Saison startet neutral.
- Nur vier mit mindestens 3,0 realem Gewicht bestätigte Saisonoffsets dürfen einen gemeinsamen gleichgerichteten Sockel bis auf ±0,2 °C Rest in Main poolen. Der Transfer ist reversibel und erhält `main + saison` für jede Jahreszeit exakt. Einzelne oder widersprechende Saisons dürfen Main nicht fernsteuern.
- Die vier Saisonanker werden um jeden meteorologischen Saisonwechsel über 30 Tage per Smoothstep weich gemischt. In Übergangsphasen summiert sich die gewichtete Saison-Evidenz einer realen Bewertung auf genau eine Bewertung; der Offset-Schritt wird normalisiert, sodass auch 50/50 den vorgesehenen effektiven Lernschritt nicht halbiert.
- Saisonoffsets sind auf ±4,0 °C begrenzt. Sättigung einer einzelnen Saison wird nicht in Main umgeleitet und ist in der Profildiagnostik erkennbar.
- Beim Laden migriert Saisonmodell v4 alte v0.3-Zustände anhand der jeweiligen Saison-`RunningStat.weight_sum`: untrainierte Rezentrierungsartefakte werden nicht als echte Saisonerfahrung übernommen, während tatsächlich trainierte saisonale Wirkung möglichst erhalten bleibt.
- Bei einem späteren Jackenwechsel wird konkretes Timing-Feedback nur der betroffenen Jackengrenze zugeordnet; Grundprofil und Saison bleiben dabei unverändert.
- Der sichtbare „Lernstand“ ist ein eigener Fortschrittswert, der im normalen fortlaufenden Lernen nicht durch schwankende Entscheidungs-Confidence zurückfällt; Reset und Undo dürfen ihn bewusst senken. Allgemeine Erfahrung und Jackengrenzen zählen stärker als einzelne Spezialkanäle.
- Feedback-Undo betrifft ausschließlich die Lernparameter und zugehörigen RunningStats der rückgängig gemachten Bewertung. Spätere unabhängige Zustände wie `learning_enabled`, `feedback_opportunities`, Setup-Antworten und Setup-Status bleiben unverändert; `total_feedback` wird vom aktuellen Stand um genau eine rückgängig gemachte lernwirksame Bewertung reduziert.
- Ein vollständiges erneutes Profil-Setup ersetzt das Modell vollständig und leert deshalb auch alle alten Feedbacksessions; deren Wetter-, Empfehlungs-, Lern- und Undo-Kontext gehört fachlich zum vorherigen Modell.
- Beim Laden werden alte v0.2.x-Vollmodell-Snapshots in `learning_before` durch die aktuelle Modellmigration geschickt und ins kompakte v0.3-Undo-Format umgewandelt, bevor sie später für Undo verwendet werden können.
- Die Arbeitszone dient nur als Anzeigename. Präsenz, Koordinaten oder Zonenstatus werden nicht zur Standortentscheidung verwendet.

## Wartungs- und Datenschutzregeln

- Profile sind an Home-Assistant-User-IDs gebunden. Gelöschte HA-Nutzer werden aus dem JackenBerater-Store entfernt; umbenannte Nutzer werden beim Profilabruf synchronisiert.
- Profil-Export/-Import ist im Code vorhanden, aber in v0.3.2 weiterhin deaktiviert. Der alte undokumentierte Lovelace-`profile_id`-Shortcut wurde aus der Karte entfernt; Profilwahl erfolgt ausschließlich über den authentifizierten Eigenprofil- bzw. Shared-/Admin-Flow.
- Diagnose-Sensoren sind standardmäßig deaktiviert und ihre Modellattribute von der Recorder-Historie ausgeschlossen.
- Der Test-/Simulationsmodus darf weder Sessions noch Feedback-Gelegenheiten, Lernen oder Undo-Zustand verändern.

## Letzter lokal verifizierter Prüfstand

- **306 / 306 Python-Tests bestanden** (`pytest -q tests --ignore=tests/ha_runtime`)
- Neue Regressionen decken parallele stale `prepared_model`-Snapshots (Deduplizierung + Cadence), Simulation-Aktivierung während `open_session` und Directory-Revision-Wechsel während Advice ab.

- Shared-Recovery/Lifecycle-Runde: `profiles` kann eine nach Rechteentzug stale Fremdprofil-Auswahl sicher auf den eigenen Scope zurückführen; Content-Endpunkte bleiben strikt geschützt.
- WebSocket-Runtime-Ownership: Requests werden während `unloading`/nicht geladenem Config Entry abgelehnt und nach langen `await`s gegen Runtime- und `ProfileManager`-Identität geprüft, damit alte Manager nach Reload keine Sessions/Saves mehr erzeugen.
- Alle asynchronen Kartenaktionen (Feedback, Setup, Maintenance sowie Backup-UI) sind profil-/entry-/generationgebunden; alte Antworten dürfen den UI-State eines neu ausgewählten Profils nicht verändern.
- Revision-Poll-Lock ist generationsgebunden; Diagnose-Simulationen bumpen eine volatile Profilrevision und werden dadurch auf bereits geöffneten Hauptkarten zeitnah sichtbar.
- Advice-Snapshot-Konsistenz: Recommendation und Revision-Token stammen garantiert aus demselben Profilmodellstand. Ändert ein anderes Gerät das Profil während Forecast-/Kalender-Awaits, wird die alte Berechnung verworfen und höchstens einmal neu auf dem aktuellen Modell erstellt; `open_session` übernimmt exakt dieses stabilisierte Modell.
- Shared-Directory-Snapshot: Profilverzeichnis und Preview tragen eigene Directory-Revisionen. Erkennt das Frontend zwischen Listen- und Advice-Request einen Directory-Wechsel, wird die gemischte Generation verworfen und vollständig neu geladen.
- Gleichzeitige UI-Aktionen desselben Profils besitzen zusätzlich zur Request-Generation eine Action-Generation; eine alte Session-Antwort darf eine neuere Sessionoberfläche desselben Profils nicht schließen oder überschreiben.
- Profil-Löschung während eines laufenden Advice-Requests wird nach dem Await erkannt und als `profile_not_found` behandelt; interne `KeyError`-Pfade werden nicht an WebSocket-Clients durchgereicht.
- funktionaler JavaScript-/Frontend-Vertragstest bestanden
- Python-Dateien kompilierbar
- JavaScript-Syntaxprüfung bestanden
- JSON-Dateien syntaktisch gültig

Der separate Home-Assistant-Runtime-Smoke-Test liegt unter `tests/ha_runtime`. CI führt ihn gegen den deklarierten Mindeststand Home Assistant 2026.6.0, einen reproduzierbar gepinnten aktuellen Teststack sowie zusätzlich gegen den jeweils neuesten verfügbaren `pytest-homeassistant-custom-component`-Stand aus.

## Wichtige Produktentscheidung

Eine Jackenstufe soll nicht wegen eines winzigen Zeitfensters zur Hauptempfehlung werden. Kurzzeitphasen werden anhand von Dauer, persönlicher Grenzabweichung und weiterem thermischem Verlauf bewertet. Kleidung unter der Jacke wird nicht abgefragt.

- Laufzeitdaten eines geladenen Config Entries liegen in `entry.runtime_data`; `hass.data[DOMAIN]` bleibt nur für integrationsglobale Frontend-/API-Marker.
- Der Forecast-Coordinator erhält den `ConfigEntry` explizit und die automatisch verwaltete Lovelace-Ressource wird beim endgültigen Entfernen des Eintrags aufgeräumt.


## v0.3.2 Release-Hardening

- 10-Minuten-Session-Deduplizierung ist jetzt unabhängig vom laufenden `feedback_opportunities`-Zähler: A → B → A innerhalb des Reuse-Fensters verwendet A wieder, statt dieselbe reale Entscheidung als dritte Opportunity zu zählen. Das temporäre Session-Schema steht jetzt auf v4: `feedback_opportunities` und `total_feedback` gehören nicht zur Entscheidungsidentität, und beantwortete identische Entscheidungen blockieren innerhalb von zehn Minuten eine zweite Opportunity. Offene Sessions mit älterer Semantik werden beim Update verworfen.
- Frontend verwendet einen gemeinsamen monotonen View-Request-Token für Background-Preview und `open_session`/manuelles Feedback. Ein später gestarteter Request gewinnt unabhängig von Antwortreihenfolge; ältere Recommendation-/Session-Antworten können neueren sichtbaren Zustand nicht zurückrollen.
- Alle aktuell als Shared-/Steuerkonto konfigurierten HA-User werden aus der beratbaren Profilauswahl entfernt. Historische persönliche Profile bleiben gespeichert, sind während der Shared-Rolle aber auch serverseitig kein Advice-/Session-/Feedback-Ziel.
- `open_session`/Manual-Feedback und Revision-Polls besitzen dieselbe Request-Generation-Härtung wie normale Preview-Refreshes; alte Profil-/Entry-Antworten dürfen keinen neuen Kartenstand überschreiben.
- Kalender-Horizon und Work/Vacation-Fenster werden innerhalb einer Recommendation generation-atomar beschafft und bei erkanntem Race gemeinsam neu gelesen.
- Preview/Open-Session liefern den nach Season-Bootstrap aktuellen Profil-Revision-Token, wodurch kein redundanter Folge-Refresh entsteht.
- Ein fehlgeschlagener Config-Entry-Unload setzt das `unloading`-Flag defensiv zurück.
- Profil-Lesewege sind strikt read-only: `get_model()`, Profilübersichten, Diagnose und Export führen kein Saison-Seeding mehr aus. Nur echte Preview/Open-Session-Nutzung des konkret gewählten Profils darf `prepare_model_for_advice()` persistieren. Fremde Admin-/Wandtablet-Profilabrufe können damit keine Saison-Seed-Ketten mehr erzeugen.
- Frontend-Requests besitzen eine Generation: Profilwechsel und `setConfig()` invalidieren laufende Antworten. Veraltete Profil-/Config-Antworten werden verworfen und können weder Preview noch `watched_entities` oder Revision überschreiben. `setConfig()` startet bei vorhandenem `hass` sofort einen Full-Refresh.
- Cross-Device-Revision ist reload-sicher und profilbezogen: normale Karten verwenden `runtime_generation + profile_revision`, Shared-Auswahl zusätzlich `directory_revision`. Ein erster nur gesehener Token gilt bei leerem Kartenstand nicht als angewendet.
- Bei aufgeteilten Arbeitsfenstern hat echte `[start,end)`-Arbeitszeit Vorrang vor überlappenden Puffern benachbarter Fenster; der Wiedereinstieg nach Teil-Abwesenheit wird damit wieder als tatsächliche Arbeit bezeichnet.
- Unbeantwortete Sessions mit fehlender/ungültiger Expiry werden verworfen; direkte Feedbackabgabe auf solchen Storage-Resten wird serverseitig als inkompatibel abgelehnt.
- Frontend-Cache für diese JS-Hardening-Runde auf `ui=13` erhöht.

- Frontend-Ressource und Package-Vertrag sind auf `ui=13` synchron; `setConfig()` räumt eigene Timer sauber auf und Revisionen gelten erst nach erfolgreichem Full-Refresh als angewendet.
- WebSocket- und periodischer HA-User-Sync prüfen nach ihrem `await`, dass noch derselbe Runtime-Manager aktiv ist.
- Datetime-Parser für Forecast, Kalender und persistierte Sessions sind gegen unmögliche Zeitstempel gehärtet.
- Forecast-Fehlerretry berücksichtigt die aktuell benötigten Quellen; ein irrelevanter defekter Arbeitsprovider erzwingt keinen 1-Minuten-Retry der Home-Beratung.
- Automatische Saisoninitialisierung/-seeding erhöht den Runtime-Revision-Token für Zweitgeräte-Synchronisierung.
- Feedback-Session-Schema gehärtet: unbeantwortete Legacy-Sessions ohne aktuelle Policy-/Schema-Signatur werden beim Laden verworfen; pausierte Sessions werden invalidiert und können nach Resume nicht im 10-Minuten-Reuse-Fenster wieder auftauchen.
- Arbeitsforecast-Coverage aggregiert mehrere relevante Arbeitsfenster vollständig und ist nicht mehr von deren Reihenfolge abhängig; Teilabdeckung bleibt in beiden Richtungen `partial`.
- Bereits geöffnete Karten auf anderen Geräten erkennen reine Profil-/Lernänderungen über einen kleinen Runtime-Revision-Token spätestens beim kurzen Revision-Poll, ohne wieder vollständige Preview-Refreshes bei jedem HA-Stateupdate auszulösen.
- Forecast-Normalisierung fängt unmögliche Provider-Datumswerte ab; ein nichtleerer Payload, aus dem kein einziger gültiger Punkt entsteht, gilt als Fetch-Fehler und nutzt den kurzen Retry-Pfad.
- Periodischer HA-User-Sync prüft nach seinem `await`, ob derselbe Runtime-Manager noch aktiv ist; Unload markiert den Runtime-State vorher als `unloading`, sodass ein bereits laufender alter Callback keinen Save auf einem ersetzten Manager vormerken kann.

- Session-Reuse berücksichtigt jetzt eine explizite Lern-/Feedback-Policy-Signatur (Lernstatus, Confidence, Schwellen-/Unusual-Flags sowie beobachteten Saison-Tag; reine Cadence-Zähler wie `total_feedback`/`feedback_opportunities` sind bewusst ausgeschlossen). Zehn-Minuten-Deduplizierung darf dadurch keinen alten Saison- oder Feedbackkontext in eine neue Entscheidung tragen.
- Freiwilliges Sofort-Feedback bewertet ausschließlich bereits erlebte Zustände: liegt ein vorhergesagter Jackenwechsel noch in der Zukunft, wird serverseitig immer nur der Startzustand gelernt; `Perfekt`, `later` oder `all` können die Zukunft nicht vorab bestätigen.
- Forecast-Abruf trennt einen technisch fehlgeschlagenen `weather.get_forecasts`-Call von einem erfolgreich leeren Forecast. Fehlerhafte Quellen werden nicht als frischer leerer Forecast verwendet und nach kurzem Backoff erneut versucht.
- Kalender-Generation schützt nicht nur den Cache: wird ein laufender Request während des `await` invalidiert, wird seine Antwort für die aktuelle Empfehlung verworfen und einmal frisch angefragt; ein zweites Race fällt konservativ auf „unavailable“ zurück.
- „Lernen pausieren“ deaktiviert offene Feedbackaufforderungen und lehnt neue Lernbewertungen serverseitig ab, statt eine scheinbar erfolgreiche No-op-Bewertung anzuzeigen.
- `Recommendation.observed_at` wird vom tatsächlichen Engine-Zeitpunkt bis in den gespeicherten Start-Lernkontext durchgereicht; Mitternachts-/Saisonrennen durch ein zweites `now()` entfallen.
- Diagnose-Simulation wird beim Entfernen/Deaktivieren der Diagnose-Entity explizit aus dem Runtime-State entfernt.
- Frontend reagiert auf HA-Stateupdates nur noch für die vom Backend gemeldeten relevanten Wetter-/Kalender-/Temperatur-Entities; der 5-Minuten-Timer bleibt Fallback statt durch beliebige HA-Sensoren effektiv auf ~1 Minute verkürzt zu werden.

- Saison-/Feedback-Confidence: Sessions verwenden exakt die bereits saisonbewusst berechnete Recommendation-Confidence. Ein relevanter Saisonanker mit <1,0 eigener Real-Evidenz verhindert ab 10 % Einfluss vollständiges `hidden`, auch innerhalb der Überblendung.
- Threshold-Upgrades: alte versteckte Raw-Überhänge werden beim Laden auf die effektiv verwendeten Grenzen canonicalisiert; Evidenz wächst nur bei echter effektiver Grenzbewegung.
- Frontend: Pending-State-Refresh läuft durch normalen Throttle/Backoff; `ui=13`. Nach einem Update ist ein vollständiger Seitenreload vorgesehen, weil registrierte Custom-Element-Klassen in derselben JS-Session nicht ersetzt werden können.
- Arbeitszeit: tatsächliche Schichten sind am Ende exklusiv (`start <= t < end`); exakt zum Feierabend gilt bereits der Pufferkontext.
- Kalendercache: Generation-Counter verhindert Re-Population durch bereits laufende Requests nach einer Invalidierung. Entity-State-Änderungen leeren sofort; der interne TTL beträgt nur noch 1 Minute, weil nicht jede Kalender-CRUD-Änderung zwingend einen State-Change erzeugt.
- Session-/Forecast-Hygiene: Session-Expiry wird auch beim Reuse-Early-Return gespeichert; Forecast-Dubletten wählen deterministisch den vollständigsten Datensatz pro Instant.
- Arbeitsforecast: Restfenster am Schichtende nutzen frische Forecastanker; vergangene Fenster sind `not_applicable`; echte Arbeitsgrenzen bleiben im Nachlaufpuffer erhalten.
- Neue Saison: 0 echte Evidenz verhindert vollständiges `hidden`, bis die aktive Saison selbst bestätigt wurde.
- Wind: Low-Wind-Übergang ist monoton. Thresholds sammeln bei durch Mindestabstände blockierter Bewegung keine Scheinevidenz.
- API/Forecast: kein `later/all` ohne Klassenwechsel; doppelte Forecast-Instant-Zeitstempel werden dedupliziert.
- Lifecycle/Frontend: Session-Cleanup wird gespeichert, Registry-Cleanup ist Config-Entry-gebunden, State-Updates während Refresh werden nachgezogen, Custom Elements sind doppelladesicher, Kalenderänderungen leeren den Kontextcache.
- Datenschutz: Diagnose-Sensor bleibt opt-in und recorder-excluded; bei Aktivierung sind vollständige persönliche Lernparameter für Entity-Berechtigte sichtbar.

- Session-Deduplizierung verwendet nur semantische Entscheidungs-/Policy-Felder; Cadence-Zähler wie `total_feedback`/`feedback_opportunities` gehören nicht zur Identität. Bereits beantwortete identische Entscheidungen blockieren innerhalb von zehn Minuten eine zweite Opportunity. Offene Sessions mit älterer Semantik werden beim Update verworfen.
- Policy-Wechsel innerhalb derselben realen Entscheidung superseden die alte unbeantwortete Session; supersedete Sessions sind weder Feedbackkandidaten noch per direkter API trainierbar. Während pausiertem Lernen erzeugte Sessions tragen `trainable=false` und bleiben nach Resume untrainierbar. Aktuelles internes Session-Schema: v5.
- Mutierende Kartenaktionen sind Single-Flight: Maintenance/Undo wird global pro Karte serialisiert, Feedback pro Session. Doppelklicks erzeugen dadurch keine doppelten Undo-/Feedback-Requests.
