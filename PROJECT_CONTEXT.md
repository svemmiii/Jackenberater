# JackenBerater – Projektkontext

Dieses lokale Projekt wurde ursprünglich am 2. September 2026 aus dem ChatGPT-Projekt „Jackenberater“ übernommen und seitdem als Home-Assistant-Custom-Integration weiterentwickelt.

- Quellprojekt: https://chatgpt.com/g/g-p-6a983d3dc0288191b241cbfcd430cacf-jackenberater/project
- Übernommener Chat: „Kältegefühl Tracken“
- Aktueller Entwicklungsstand: **JackenBerater v0.5.0**
- CI prüft den deklarierten Mindeststand Home Assistant 2026.6.0, einen reproduzierbar gepinnten aktuellen Stand und zusätzlich den jeweils neuesten verfügbaren HA-Teststack unter Python 3.14.

## Zweck

JackenBerater erzeugt aus aktuellem Wetter, stündlichem Forecast, persönlichem Wärmeempfinden und optionalem Arbeits-/Kalenderkontext eine nachvollziehbare Jacken- und Regenschutzempfehlung. Das persönliche Modell bleibt kompakt und lernt inkrementell, ohne eine jahrelange Wetter- oder Feedbackhistorie zu speichern.

## Aktuelle Produktregeln

- Normale Betrachtung: 9 reale Stunden, bei relevanten Änderungen bis etwa 12 Stunden; Kalender-/Arbeitskontext kann bis maximal 16 Stunden erweitern.
- Wetterquelle, Arbeits-/Schichtkontext und persönliche Kalender gehören ab v0.5.0 zum jeweiligen Personenprofil. Innerhalb einer tatsächlichen dort konfigurierten Arbeitszeit ist dessen Arbeitswetter maßgeblich; außerhalb davon dessen primäre Profil-Wetterquelle. Ein ausgefallenes primäres Wetter darf eine gesunde Arbeitsquelle nicht blockieren.
- Arbeitsforecast ersetzt den primären Profil-Forecast nur innerhalb der geplanten Arbeitsfenster. Fehlende Arbeitsdaten werden nicht still mit der primären Wetterquelle gefüllt und müssen sichtbar gewarnt werden.
- Profilbezogene Forecasts cachen erfolgreiche Abrufe 15 Minuten, echte Abruffehler dagegen nur 1 Minute. Erfolgreich leere Forecasts gelten weiterhin als Erfolg. Arbeitsforecast wird nur bei einem tatsächlich relevanten Planungsfenster abgefragt.
- Eine sichtbare Karte erzeugt keine Session. Erst bewusstes Aufklappen erzeugt eine Nutzungssession; das Infofeld allein nicht.
- Nahezu identische bewusste Öffnungen desselben Profils innerhalb von 30 Minuten zählen profilweit als eine reale Jackenentscheidung, unabhängig vom Gerät/Login.
- Fälliges Feedback gehört zum Profil und kann deshalb auf einem freigegebenen Wandtablet beantwortet werden, auch wenn die Session am persönlichen Gerät entstand.
- Nicht-freiwilliges Feedback ist serverseitig an `request_feedback` und `ready_at` gebunden; freiwilliges Feedback darf bewusst sofort erfolgen.
- Shared-/Wandtablet-Rechte stammen ausschließlich aus `shared_user_ids` der Integration. Lovelace-`shared: true` ist keine Berechtigung und wird nicht als Shared-Modus ausgewertet.
- `general_offset_c` ist der ganzjährige persönliche Grundwert. Winter, Frühling, Sommer und Herbst sind eigenständige Offsets dazu; normales thermisches Feedback verschiebt Main nicht direkt, sondern nur die aktive Saison beziehungsweise während der 30-Tage-Überblendung die beiden direkten Nachbarsaisons.
- Saisonale Lernraten hängen ausschließlich von der eigenen echten Saison-Evidenz ab und frieren auch bei hoher alter Evidenz nicht vollständig ein. `Perfekt` bestätigt die beteiligte Saison ohne thermische Offsetkorrektur; `Nicht genutzt`, reine Timing-/Grenzenkorrekturen und thermische No-ops erzeugen keine Saison-Evidenz.
- Eine erstmals auftretende Saison übernimmt beim ersten Übergang einmalig nur den Offset ihrer direkten Vorgängersaison. Wird die komplette Übergangszone verpasst, wird dieses Seeding beim ersten späteren Zugriff in der neuen Saison nachgeholt. RunningStats, Evidenz und Lernhistorie werden nie kopiert. Neu in v0.4.2: War die allererste genutzte Saison wegen eines späten Einstiegs mit weniger als 2,0 eigener Evidenz nur schwach gelernt, darf sie beim ersten Wiederkommen in einem späteren Jahreszyklus einmalig zum inzwischen ausreichend gelernten direkten Vorgänger gezogen werden; danach ist dieser Rescue dauerhaft erledigt. Sind mehrere ganze Saisons übersprungen und ist die direkte Vorgängersaison unbekannt, wird keine rückwirkende Seed-Kette erfunden.
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
- Profil-Export/-Import ist im Code vorhanden, aber in v0.4.0 weiterhin deaktiviert. Der alte undokumentierte Lovelace-`profile_id`-Shortcut wurde aus der Karte entfernt; Profilwahl erfolgt ausschließlich über den authentifizierten Eigenprofil- bzw. Shared-/Admin-Flow.
- Diagnose-Sensoren sind standardmäßig deaktiviert und ihre Modellattribute von der Recorder-Historie ausgeschlossen.
- Der Test-/Simulationsmodus darf weder Sessions noch Feedback-Gelegenheiten, Lernen oder Undo-Zustand verändern.

## Letzter lokal verifizierter Prüfstand

- **448 / 448 HA-unabhängige Python-Tests bestanden** (`pytest -q tests --ignore=tests/ha_runtime`), zusätzlich JS-Syntaxcheck, Python-Compilecheck und JSON-/YAML-Validierung. Der echte HA-Runtime-Smoke benötigt eine Umgebung mit installiertem `homeassistant` und konnte im lokalen Prüfcontainer nicht gesammelt werden.
- Neue v0.4.0-Regressionen decken die Pullover-Schicht zusätzlich gegen kurzfristige Indoor→Outdoor-Übergangskälte, Forecast-Lücken vor dem ersten Zukunftspunkt, falsche Jackengrenzen-Evidenz bei `Pullover + Jacke`, verschobene Pullover-Transientgrenzen in beide Richtungen, korrekte Lernattribution bei `Pullover + keine Jacke + transient` sowie reine `pullover_reason`-Änderungen ohne neue Lernsession, das vollständige Abtrainieren von Warming-/Cooling-Transient-Overrides einschließlich des 0-Grad-Minuten-Grenzfalls, reine `weather.condition`-Labelwechsel und reine `rain_status`-Hinweiswechsel ohne neue Lernsession, reine Work-/Kontextmetadatenwechsel, den realistischen Fall eines nachträglich verfügbaren Work-Forecasts bei unverändertem Outfit sowie Lernsemantik-Grenzen bei `14,8 → 15,2 °C`, Wind-Malus `0,4 → 0,6` und Transition-Malus `0,7 → 0,9` ab; zusätzlich sind Transient-/Bootstrap-Fälle gegen semantisch wirkungslose Grenzrefreshes sowie Confidence-Änderungen innerhalb bzw. über die `< 0,55`-Policygrenze abgesichert. Setup-Speichern ist außerdem Single-Flight gegen Doppelklick. Der v13-Learning-Contract friert die Lernbedeutung einer Session unveränderlich ein: Bootstrap/Mature, `Perfekt`-Grenzziel, Wind-/Transition-Aktivierung und Saisongewichte werden beim Öffnen gespeichert und beim späteren Feedback tatsächlich durchgesetzt. `PHASE_ALL` kann dadurch innerhalb einer Bewertung nicht die Lernphase wechseln. Die Active-Learning-Policy dedupliziert nach dem tatsächlichen Ergebnis `informative_feedback` statt nach einzelnen OR-Ursachen; identische Saisongewichte über Mitternacht bleiben dieselbe Lernsemantik. Frontend-Mutation-Flights sind zusätzlich an Config-/Profil-/Generation gebunden, sodass alte Setup-/Maintenance-Requests einen neuen Kontext weder blockieren noch entsperren können. Der v14-Stand bindete zusätzlich jede Active-Learning-Opportunity an die reale Entscheidung: beantwortete identische Entscheidungen blieben im damaligen v14-Stand 10 Minuten Dedupe-Anker (seit v0.4.2: 30 Minuten), während semantische Snapshot-Replacements ihre ursprüngliche `opportunity_count` erben. Pausierte Display-Sessions werden innerhalb derselben Pause wiederverwendet, bleiben nach Resume aber dauerhaft untrainierbar. Active-Work setzt im Fallback konsistent `stay_context=work`; beschädigte `inf`-/`seeded_from`-Storagewerte werden defensiv normalisiert.
- Neue v0.4.1-Regressionen prüfen Taupunkt-/Schwüleberechnung, trockene Gegenfälle, getrennte Warm-/Kaltfeuchte-Persistenz, langsames Solarlernen, neutrales `partlycloudy` ohne sichere Tageslicht-/Expositionsinformation, Priorisierung des Feuchtekanals bei `Pullover + keine Jacke + zu warm`, unverändertes Pulloverlernen unter trockenen Bedingungen, geteilte Lernstärke bei gleichzeitig aktiver Schwüle + Sonne, eingefrorene/quantisierte Specialist-Relevanz mit Opportunity-erhaltendem Snapshot-Replacement, Kaltfeuchte `zu kalt`/`zu warm`/`perfekt`, `PHASE_LATER`/`boundary_only` ohne Feuchte-/Solar-Doppellernen, Sichtbarkeit materiell aktiver Spezialisten mit <3 eigener Evidenz sowie defensive Bereinigung nicht-dictförmiger Session-Storageeinträge und beschädigter Specialist-Contract-Werte.


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

Eine Jackenstufe soll nicht wegen eines winzigen Zeitfensters zur Hauptempfehlung werden. Kurzzeitphasen werden anhand von Dauer, persönlicher Grenzabweichung und weiterem thermischem Verlauf bewertet. Ab v0.4.0 modelliert JackenBerater zusätzlich genau eine feste Oberkörper-Grundschicht (`Shirt` oder `Pullover`); Hosen/Shorts bleiben bewusst außerhalb des Modells.

- Laufzeitdaten eines geladenen Config Entries liegen in `entry.runtime_data`; `hass.data[DOMAIN]` bleibt nur für integrationsglobale Frontend-/API-Marker.
- Der Forecast-Coordinator erhält den `ConfigEntry` explizit und die automatisch verwaltete Lovelace-Ressource wird beim endgültigen Entfernen des Eintrags aufgeräumt.



## v0.5.0 Personenprofile / Server-Lifecycle

- Kein allgemeines Beratungsprofil mehr: neue Personen starten neutral mit eigener Wetterquelle und eigenem Arbeits-/Schicht-/Kalenderkontext. Bestehende Profile migrieren die früher globalen persönlichen Werte einmalig.
- Empfehlung, Wetterauswertung, Sessions und Lernen sind serverseitiger Profilzustand; Handy und Shared-Tablet sind Darstellungs-/Bedienclients derselben Auswertung. Die sichtbare Hauptkarte bleibt gegenüber v0.4.2 unverändert.
- Preview liefert einen Profil-Shell auch ohne berechenbare Empfehlung, damit Erst-Setup und Weather-Recovery nie von `weather_unavailable` verdeckt werden.
- `ProfileManager.async_open_session()` ist die einzige Session-Dedupe-Instanz. Die WebSocket-API besitzt keinen vereinfachten Vorab-Shortcut mehr.
- Profilbezogene `watched_entities` werden mit dem angezeigten Preview geliefert, sodass ein restauriertes Shared-Profil sofort seine tatsächlichen Wetter-/Kalenderquellen beobachtet.
- Startantworten können aus dem bestehenden Info-Bereich bewusst neu gesetzt werden; vollständiges Re-Setup ersetzt Modell und Sessions wie bisher.
- Frontend-Recovery bei HA-Core-Neustarts: Die Karte nutzt `disconnected`/`ready` der HA-WebSocket-Verbindung und besitzt zusätzlich einen schnellen Restart-Retry für den Zeitraum, in dem der Socket schon wieder bereit ist, der JackenBerater-ConfigEntry aber noch `integration_reloading`/nicht geladen meldet. Die normale Karte benötigt dadurch keinen manuellen Browser-Refresh. Frontend-Cache: `ui=23`.

## v0.4.3 Profilwetter / Shared-UI

- Primäres Wetter ist profilbezogen (`weather_entity` im Profilstore); bestehende Profile migrieren einmalig vom bisherigen globalen `CONF_WEATHER`.
- Shared-/Wandtablet bleibt reine Bedien-/Anzeigeoberfläche: ausgewähltes Profil bestimmt Wetter, Empfehlung, Session und Feedback. Das Tablet benötigt keine eigene Wetterentität und berechnet keine separate Beratung.
- Persönliche Profile können die Wetterentität im Setup und später im Info-Bereich wechseln. Ein Wechsel leert offene Sessions des alten Wetterkontexts.
- Nicht-globale Profil-Forecasts werden serverseitig 15 Minuten gecacht.
- Eine frische Session wird 30 Minuten profilweit als aktive Interaktion wiederverwendet, damit Tablet und Handy nicht parallel zwei Sessions desselben Profils erzeugen.
- Die bestehende Shared-Profilwahl per localStorage, Warn-/Profilanzeige und profilbezogenes Feedback bleiben erhalten.

## v0.4.2 Arbeitsgate / Nässe / Sessions / Season Rescue

- Arbeit ist erst ab **3 h vor echtem Start** oder während einer laufenden Schicht beratungsrelevant. Arbeits-Puffer ziehen den Start nicht vor; Nachtarbeit bleibt über den Kalendertag hinweg aktiv.
- Provider-`dew_point` wird nach Normalisierung bevorzugt; die lokale Magnus-Berechnung bleibt vollständiger Fallback.
- Neuer Nässe-Spezialist mit neutraler Migration (`wet_bias_c=0`, `wet_stat=0`). Wind×Nässe erhält nur eine feste, auf den personalisierten Einzeleffekten aufbauende harmonische Synergie; kein eigener Synergie-Lernkanal.
- Numerische Nässe aus Forecastmenge/-wahrscheinlichkeit wird kontinuierlich eingeblendet; die bisherigen 0,2 mm / 65 % bleiben Sättigungspunkte statt binärer Schalter. Provider-Taupunkt wird bei gleichzeitig vorhandener rF weich plausibilisiert (voller Provider bis 4 K Abweichung, Blend 4..8 K, danach Magnus), sodass keine künstlichen Outfit-Sprünge an einem einzelnen Grenzwert entstehen.
- Thermische Nässe darf unterhalb der Specialist-Materialität weiterhin weich wirken, wird aber erst ab **0,50 K neutralem Nässe-Basiseffekt** als `wet`-Unusual-/Active-Learning-Signal markiert. Damit fordert JackenBerater kein Nässefeedback an, das der Nässe-Spezialist selbst anschließend gar nicht lernen dürfte.
- Provider-Taupunkte oberhalb der Lufttemperatur werden ohne zusätzliche harte T+2-K-Grenze kontinuierlich auf die Lufttemperatur geklemmt; bei vorhandener rF entscheidet danach ausschließlich das 4..8-K-Plausibilitätsblending über das Providergewicht.
- `wet` ist Bestandteil des eingefrorenen Specialist-Learning-Contracts, beteiligt sich an Share/Relevance, wird auf `boundary_only` vollständig gesperrt und kann bei <3 Evidenzpunkten frühes Feedback sichtbar halten.
- Season Rescue: Eine erste schwach gelernte Saison darf beim ersten späteren Jahreszyklus einmalig aus dem direkten, ausreichend gelernten Vorgänger nachgebessert werden. Schwelle: <2 eigene Evidenz; Evidenz wird nie kopiert; bestehende v0.4.1-Saisonwerte werden bei Migration nicht unmittelbar verändert. Die Rescue-Entscheidung wird pro Rückkehrzyklus eingefroren: War der Vorgänger beim ersten relevanten Zugriff noch nicht ausreichend gelernt, kann späteres Feedback denselben 30-Tage-Blend nicht nachträglich umschalten; erst ein späterer Jahreszyklus darf erneut prüfen.
- Session-Dedupe **30 min**, Schema **v17**. Detailansicht erzeugt passive Session erst nach **1,3 s**; Info/Details Auto-Collapse nach **5 min Inaktivität** mit Interaction-Refresh.
- Frontend-Cache `ui=19`.

## v0.4.1 Feuchte / Taupunkt / Strahlung

- Warm-feuchte Luft verwendet intern Taupunkt statt bloßer relativer Feuchte als primäres Schwülesignal; die Wirkung blendet temperaturabhängig ein und ist keine offizielle Heat-Index-/UTCI-Ausgabe.
- Persönliches Lernen ist in `humidity_warm_*` und `humidity_cold_*` getrennt, damit Sommer-Schwüle und der kleine Kaltfeuchte-Effekt nicht dieselbe Lerndimension teilen.
- Solar wird als meteorologisches Strahlungspotenzial verstanden. `sunny` + Bewölkung liefert einen konservativen thermischen Beitrag; `partlycloudy` bleibt ohne zusätzliche sichere Tageslicht-/Expositionsinformation thermisch neutral.
- `solar_bias_c` / `solar_stat` lernen absichtlich langsam und nur bei starkem `sunny`-Signal, weil Weather-Daten keine tatsächliche persönliche Sonnen-/Schattenexposition kennen.
- Klare Feuchte-/Solarursachen können auch bei `keine Jacke + zu warm` lernen. Bei `Pullover + keine Jacke + zu warm` hat ein klar aktiver Wetter-Spezialkanal Vorrang vor einer globalen Pulloververschiebung; trockene/schattige Fälle trainieren weiterhin die Pullovergrenze.
- Mehrere gleichzeitig aktive Umwelt-Spezialkanäle teilen die Lernstärke. Transient-Feedback bleibt separat und trainiert Feuchte/Solar nicht zusätzlich.
- Session-Schema v16 friert die neuen Umwelt-Lerngates **und deren quantisierte tatsächliche Lernrelevanz/Share** pro Feedbacksession ein. Relevante Änderungen ersetzen nur den Snapshot und übernehmen dieselbe Opportunity-Nummer.
- Reines `PHASE_LATER`-Boundary-Feedback ist ausschließlich Jackengrenzen-Feedback; selbst bei schwül/sonnigem späterem Wetter bleiben `humidity_*`- und `solar_*`-Spezialisten dabei eingefroren.
- Ist ein materieller Feuchte-/Solar-Spezialist noch unter 3 Evidenzpunkten, verhindert dieser konkrete Early-Learning-Bedarf vollständiges `hidden`; die Karte bleibt mindestens kompakt erreichbar.
- Die Lernfortschrittsanzeige umfasst ab v0.4.1 drei zusätzliche Spezialkanäle. Deshalb kann ein migriertes v0.4.0-Profil prozentual leicht zurückgehen, ohne dass alte Evidenz verloren geht.

## v0.4.0 Pullover / Midlayer

- Hosen-/Shorts-Idee bewusst verworfen; v0.4.0 erweitert ausschließlich den Oberkörper um `Shirt` vs. `Pullover`.
- Pullover ist eine feste Midlayer-Entscheidung für den relevanten Planungszeitraum; er wird nie als später mitzunehmender Kleidungswechsel geplant.
- Außenschichten bleiben flexibel: bei deutlicher Erwärmung gewinnt Shirt + abnehmbare Jacke gegenüber einem morgens thermisch ähnlichen Pullover.
- Normaler Pullover-Einsatz benötigt mindestens zwei kontinuierliche Zukunftspunkte über mindestens zwei Stunden und ausreichend stabile/kühle Bedingungen.
- Bei anhaltender tiefer Kälte kann Pullover + Winterjacke die bisherige Kälteskala nach unten erweitern; wird es im selben Zeitraum warm, bleibt Shirt + abnehmbare Jacke bevorzugt.
- Neue Nutzer erhalten eine fünfte Setup-Frage zur Pullover-Neigung. Bestehende Profile migrieren mit neutralem Pullover-Prior und behalten alle bisherigen Jacken-/Saison-/Wind-/Threshold-Werte.
- Pullover hat eigene Evidenz/Confidence und einen lernbaren Schwellen-Offset. „Zu warm“ mit Pullover verschiebt gezielt dessen Einsatz zu kühleren Bedingungen.
- Transient-/Kurzzeitlogik bewertet bei Pullover dieselbe um `PULLOVER_WARMTH_C` verschobene Jackengrenze wie die normale Outfitentscheidung; die Umgebungs-Effektivtemperatur selbst bleibt unverändert.
- `pullover_reason` und `weather.condition` sind reine Erklärungs-/Historienmetadaten und kein Bestandteil der Session-Deduplizierungsidentität. Auch `rain_status` ist allein kein Wärme-Lerninput; ein reiner Regenschutz-Hinweiswechsel bleibt bei unverändertem Outfit/thermischem Lernkontext innerhalb des aktuellen 30-Minuten-Fensters dieselbe reale Entscheidung. Dasselbe gilt für organisatorische Work-/Kontextmetadaten (`source`, `work_jacket`, `work_context`, `later_work_period`, `later_change_confirmed`): Sie dürfen dieselbe thermische Outfitentscheidung nicht in mehrere Lerngelegenheiten aufspalten.
- Historisch ab v11/v13 besaß die damals 10-minütige Deduplizierung bereits eine diskrete Lernsemantik-Signatur; seit v0.4.2 gilt dasselbe Prinzip mit 30 Minuten. Praktisch gleiche Wetterwerte dürfen nur dann denselben Snapshot wiederverwenden, wenn `Perfekt` dieselbe Jackengrenze bestätigen würde und die Wind-/Transition-Lerngates sowie die Pullover-/Transient-Attribution gleich bleiben. Bei geänderter Lernsemantik wird eine alte unbeantwortete Session superseded, bevor der aktuelle Snapshot trainierbar wird; dadurch kann Feedback nie auf einen nur numerisch nahen, fachlich aber anders lernenden Altzustand fallen.
- Die Lernsemantik-Signatur spiegelt die Early-Return-Reihenfolge von `apply_feedback()`: Ein aktiver Transient blendet für die Session-Identität normale Boundary-/Wind-/Transition-Lernpfade aus; während Bootstrap bleiben Wind/Transition ebenfalls semantisch inaktiv. Die Feedback-Policy verwendet keine rohe Confidence mehr, sondern die tatsächliche `< 0,55`-Schwelle und den Bootstrap-Zustand. Semantisch wirkungslose Refreshes verändern dadurch weder Session noch Feedback-Cadence.
- Die persönliche `transient_tolerance` kann von 1,0 bis auf 0,0 sinken. `0,0` ist ein explizites Veto in der Engine, sodass konsistentes Gegenfeedback die Kurzzeitglättung auch bei exakt 0 Grad-Minuten Belastung vollständig abschalten kann.
- Temporäres Feedback-Session-Schema v0.4.1: v16.
- Frontend zeigt Kombinationen wie `Pullover + Winterjacke`; spätere Forecast-Hinweise nennen nur die zusätzlich mitzunehmende Jacke.
- Frontend-Cache v0.4.1: `ui=18`.

## v0.3.2 Release-Hardening

- Historisch wurde die damals 10-minütige Session-Deduplizierung unabhängig vom laufenden `feedback_opportunities`-Zähler gemacht (seit v0.4.2: 30 Minuten): A → B → A innerhalb des Reuse-Fensters verwendet A wieder, statt dieselbe reale Entscheidung als dritte Opportunity zu zählen. Das temporäre Session-Schema steht jetzt auf v4: `feedback_opportunities` und `total_feedback` gehören nicht zur Entscheidungsidentität, und beantwortete identische Entscheidungen blockierten im damaligen v4-Stand innerhalb von zehn Minuten eine zweite Opportunity (seit v0.4.2: 30 Minuten). Offene Sessions mit älterer Semantik werden beim Update verworfen.
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
- Frontend-Cache dieses damaligen Hardening-Stands: `ui=18`.

- Frontend-Ressource und Package-Vertrag waren in diesem damaligen Hardening-Stand auf `ui=18` synchron; `setConfig()` räumt eigene Timer sauber auf und Revisionen gelten erst nach erfolgreichem Full-Refresh als angewendet.
- WebSocket- und periodischer HA-User-Sync prüfen nach ihrem `await`, dass noch derselbe Runtime-Manager aktiv ist.
- Datetime-Parser für Forecast, Kalender und persistierte Sessions sind gegen unmögliche Zeitstempel gehärtet.
- Forecast-Fehlerretry berücksichtigt die aktuell benötigten Quellen; ein irrelevanter defekter Arbeitsprovider erzwingt keinen 1-Minuten-Retry der Home-Beratung.
- Automatische Saisoninitialisierung/-seeding erhöht den Runtime-Revision-Token für Zweitgeräte-Synchronisierung.
- Feedback-Session-Schema gehärtet: unbeantwortete Legacy-Sessions ohne aktuelle Policy-/Schema-Signatur werden beim Laden verworfen; pausierte Sessions werden invalidiert und können nach Resume nicht im damals 10-minütigen Reuse-Fenster wieder auftauchen (aktuell 30 Minuten).
- Arbeitsforecast-Coverage aggregiert mehrere relevante Arbeitsfenster vollständig und ist nicht mehr von deren Reihenfolge abhängig; Teilabdeckung bleibt in beiden Richtungen `partial`.
- Bereits geöffnete Karten auf anderen Geräten erkennen reine Profil-/Lernänderungen über einen kleinen Runtime-Revision-Token spätestens beim kurzen Revision-Poll, ohne wieder vollständige Preview-Refreshes bei jedem HA-Stateupdate auszulösen.
- Forecast-Normalisierung fängt unmögliche Provider-Datumswerte ab; ein nichtleerer Payload, aus dem kein einziger gültiger Punkt entsteht, gilt als Fetch-Fehler und nutzt den kurzen Retry-Pfad.
- Periodischer HA-User-Sync prüft nach seinem `await`, ob derselbe Runtime-Manager noch aktiv ist; Unload markiert den Runtime-State vorher als `unloading`, sodass ein bereits laufender alter Callback keinen Save auf einem ersetzten Manager vormerken kann.

- Session-Reuse erhielt in diesem damaligen Hardening-Stand eine explizite Lern-/Feedback-Policy-Signatur (Lernstatus, Confidence, Schwellen-/Unusual-Flags sowie beobachteten Saison-Tag; reine Cadence-Zähler wie `total_feedback`/`feedback_opportunities` sind bewusst ausgeschlossen). Die damalige Zehn-Minuten-Deduplizierung durfte dadurch keinen alten Saison- oder Feedbackkontext in eine neue Entscheidung tragen.
- Freiwilliges Sofort-Feedback bewertet ausschließlich bereits erlebte Zustände: liegt ein vorhergesagter Jackenwechsel noch in der Zukunft, wird serverseitig immer nur der Startzustand gelernt; `Perfekt`, `later` oder `all` können die Zukunft nicht vorab bestätigen.
- Forecast-Abruf trennt einen technisch fehlgeschlagenen `weather.get_forecasts`-Call von einem erfolgreich leeren Forecast. Fehlerhafte Quellen werden nicht als frischer leerer Forecast verwendet und nach kurzem Backoff erneut versucht.
- Kalender-Generation schützt nicht nur den Cache: wird ein laufender Request während des `await` invalidiert, wird seine Antwort für die aktuelle Empfehlung verworfen und einmal frisch angefragt; ein zweites Race fällt konservativ auf „unavailable“ zurück.
- „Lernen pausieren“ deaktiviert offene Feedbackaufforderungen und lehnt neue Lernbewertungen serverseitig ab, statt eine scheinbar erfolgreiche No-op-Bewertung anzuzeigen.
- `Recommendation.observed_at` wird vom tatsächlichen Engine-Zeitpunkt bis in den gespeicherten Start-Lernkontext durchgereicht; Mitternachts-/Saisonrennen durch ein zweites `now()` entfallen.
- Diagnose-Simulation wird beim Entfernen/Deaktivieren der Diagnose-Entity explizit aus dem Runtime-State entfernt.
- Frontend reagiert auf HA-Stateupdates nur noch für die vom Backend gemeldeten relevanten Wetter-/Kalender-/Temperatur-Entities; der 5-Minuten-Timer bleibt Fallback statt durch beliebige HA-Sensoren effektiv auf ~1 Minute verkürzt zu werden.

- Saison-/Feedback-Confidence: Sessions verwenden exakt die bereits saisonbewusst berechnete Recommendation-Confidence. Ein relevanter Saisonanker mit <1,0 eigener Real-Evidenz verhindert ab 10 % Einfluss vollständiges `hidden`, auch innerhalb der Überblendung.
- Threshold-Upgrades: alte versteckte Raw-Überhänge werden beim Laden auf die effektiv verwendeten Grenzen canonicalisiert; Evidenz wächst nur bei echter effektiver Grenzbewegung.
- Frontend: Pending-State-Refresh läuft durch normalen Throttle/Backoff; der Frontend-Cache dieses damaligen Stands war `ui=18`. Nach einem Update ist ein vollständiger Seitenreload vorgesehen, weil registrierte Custom-Element-Klassen in derselben JS-Session nicht ersetzt werden können.
- Arbeitszeit: tatsächliche Schichten sind am Ende exklusiv (`start <= t < end`); exakt zum Feierabend gilt bereits der Pufferkontext.
- Kalendercache: Generation-Counter verhindert Re-Population durch bereits laufende Requests nach einer Invalidierung. Entity-State-Änderungen leeren sofort; der interne TTL beträgt nur noch 1 Minute, weil nicht jede Kalender-CRUD-Änderung zwingend einen State-Change erzeugt.
- Session-/Forecast-Hygiene: Session-Expiry wird auch beim Reuse-Early-Return gespeichert; Forecast-Dubletten wählen deterministisch den vollständigsten Datensatz pro Instant.
- Arbeitsforecast: Restfenster am Schichtende nutzen frische Forecastanker; vergangene Fenster sind `not_applicable`; echte Arbeitsgrenzen bleiben im Nachlaufpuffer erhalten.
- Neue Saison: 0 echte Evidenz verhindert vollständiges `hidden`, bis die aktive Saison selbst bestätigt wurde.
- Wind: Low-Wind-Übergang ist monoton. Thresholds sammeln bei durch Mindestabstände blockierter Bewegung keine Scheinevidenz.
- API/Forecast: kein `later/all` ohne Klassenwechsel; doppelte Forecast-Instant-Zeitstempel werden dedupliziert.
- Lifecycle/Frontend: Session-Cleanup wird gespeichert, Registry-Cleanup ist Config-Entry-gebunden, State-Updates während Refresh werden nachgezogen, Custom Elements sind doppelladesicher, Kalenderänderungen leeren den Kontextcache.
- Datenschutz: Diagnose-Sensor bleibt opt-in und recorder-excluded; bei Aktivierung sind vollständige persönliche Lernparameter für Entity-Berechtigte sichtbar.

- Session-Deduplizierung verwendet nur semantische Entscheidungs-/Policy-Felder; Cadence-Zähler wie `total_feedback`/`feedback_opportunities` gehören nicht zur Identität. Bereits beantwortete identische Entscheidungen blockieren im aktuellen Stand innerhalb von 30 Minuten eine zweite Opportunity. Offene Sessions mit älterer Semantik werden beim Update verworfen.
- Policy-Wechsel innerhalb derselben realen Entscheidung superseden die alte unbeantwortete Session; supersedete Sessions sind weder Feedbackkandidaten noch per direkter API trainierbar. Während pausiertem Lernen erzeugte Sessions tragen `trainable=false` und bleiben nach Resume untrainierbar. Internes Session-Schema dieses damaligen Hardening-Stands: v5.
- v14-Dedupe-Vertrag: Eine beantwortete current-schema Session blieb ab v14 innerhalb des damaligen 10-Minuten-Fensters Dedupe-Anchor, unabhängig von späteren Modell-/Learning-Contract-Änderungen; v0.4.2 verlängert dieses Fenster auf 30 Minuten, ohne die Semantik zu ändern. Unbeantwortete semantische Snapshot-Replacements übernehmen die `opportunity_count` der realen Entscheidung und erhöhen `feedback_opportunities` nicht erneut. Pausierte `trainable=false`-Display-Snapshots dürfen während derselben Pause dedupliziert werden, ohne nach Resume rückwirkend trainierbar zu werden.
- Mutierende Kartenaktionen sind Single-Flight: Maintenance/Undo wird global pro Karte serialisiert, Feedback pro Session. Doppelklicks erzeugen dadurch keine doppelten Undo-/Feedback-Requests.
