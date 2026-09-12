# Changelog

## v0.3.2

### Release-Hardening

- Session-Deduplizierung gegen Policy-Wechsel gehärtet: Ändert sich bei derselben realen Entscheidung innerhalb des 10-Minuten-Fensters die Feedback-Policy, wird die alte unbeantwortete Session explizit superseded und dauerhaft untrainierbar, bevor die neue Policy-Session entsteht. Zwei trainierbare Versionen derselben Entscheidung können damit nicht gleichzeitig fällig werden.
- Während pausiertem Lernen erzeugte Sessions sind explizit `trainable=false` und bleiben auch nach Resume dauerhaft untrainierbar. Das temporäre Session-Schema wurde dafür auf v5 erhöht; offene Sessions älterer Semantik werden wie bisher beim Upgrade verworfen.
- Mutierende Frontendaktionen sind Single-Flight: Undo/Reset/Lernstatus senden während eines laufenden Maintenance-Requests keinen zweiten Mutationsrequest; Feedbackbuttons sind pro Session ebenfalls gesperrt. Schneller Doppelklick kann dadurch weder zwei Lernänderungen zurücknehmen noch eine erfolgreiche Bewertung mit einer zweiten "bereits abgegeben"-Antwort überdecken.
- Frontend-Cache-Revision für diese Session-/Mutation-Hardening-Runde auf `ui=13` erhöht.

- Zehn-Minuten-Deduplizierung auf reale Entscheidungen vervollständigt: Auch eine bereits beantwortete identische Session verhindert innerhalb des Reuse-Fensters eine zweite Opportunity bzw. ein zweites Lernen derselben Wettersituation. `total_feedback` ist – wie bereits `feedback_opportunities` – nur Cadence-Zustand und kein Bestandteil der Entscheidungsidentität. Das temporäre Session-Schema wurde deshalb auf v4 erhöht; unbeantwortete v3-Sessions werden beim Update verworfen.
- Vollständige Card-Revision berücksichtigt nun neben Modell-/Directory-Revision auch den dynamischen Sessionzustand. Neue Sessions und das Erreichen von `ready_at` werden dadurch auf anderen geöffneten Geräten über den 30-Sekunden-Revision-Poll sichtbar, ohne künstlich die persistierte Lernmodellrevision zu erhöhen.
- `open_session` und manuelles Feedback markieren eine neuere Action-Revision nicht mehr als vollständig angewendeten Profil-/Directory-Snapshot. Sie dürfen Recommendation/Session sofort aktualisieren und den Token als „gesehen“ merken, erzwingen bei Abweichung aber einen vollständigen `profiles + preview`-Refresh; erst dieser setzt die applied revision.
- Frontend-Cache-Revision für diese Session-/Snapshot-Hardening-Runde auf `ui=12` erhöht.
- Zehn-Minuten-Deduplizierung korrigiert: `feedback_opportunities` bleibt für die Cadence einer neu erzeugten Session aktuell, ist aber nicht mehr Teil der Session-Identität. A → B → A innerhalb von zehn Minuten zählt damit nur A und B; der zweite A-Aufruf verwendet die ursprüngliche A-Session. Das interne Session-Schema wurde auf v3 erhöht, damit offene Sessions aus dem vorherigen Identitätsvertrag beim Update nicht weiterverwendet werden.
- Frontend-Reihenfolge vereinheitlicht: Background-Preview, Detail-`open_session` und manuelles Feedback teilen einen monotonen View-Request-Token. Später gestartete Requests superseden ältere unabhängig von Antwortreihenfolge; eine alte Sessionantwort kann keine bereits neuere Preview zurückrollen und ein alter Refresh keine neuere Sessionansicht überschreiben.
- Shared-Control-Profile werden konsequent aus Personenprofilen entfernt: Alle aktuell in `shared_user_ids` konfigurierten Konten sind reine Steuerflächen, werden in Shared/Admin-Selektoren ausgeblendet und von Preview/Session/Feedback als Advice-Ziel serverseitig abgelehnt. Historische Lerndaten bleiben unverändert gespeichert und werden nach Entfernen des Shared-Status wieder nutzbar.
- Frontend-Cache-Revision wegen der View-Ordering-Härtung auf `ui=11` erhöht.
- Parallele `open_session`-Snapshots verlieren keine Feedback-Gelegenheiten mehr: Das stabilisierte Advice-Modell übernimmt unmittelbar vor Session-Policy/Deduplizierung ausschließlich den aktuell persistierten `feedback_opportunities`-Zähler. Identische parallele Opens werden wieder sauber dedupliziert; unterschiedliche Sessions zählen und takten jeweils genau einmal.
- Diagnose-Simulation ist über die gesamte `open_session`-Operation gesperrt: Wird sie während Forecast-/Kalender-Awaits aktiviert, bricht auch ein Snapshot-Retry mit `simulation_active` ab und kann keine echte persistente Feedbacksession erzeugen.
- Shared-Directory-Snapshot vervollständigt: Nach Advice-Awaits werden Directory- und kombinierter Card-Revision-Token frisch gelesen. Ändert sich nur das Profilverzeichnis, bleibt die persönliche Recommendation gültig, aber das Frontend erkennt `profiles D1` vs. `preview D2` sofort und lädt die Transaktion neu.
- Advice-Snapshot-Konsistenz zentral abgesichert: Preview und `open_session` merken nach Season-Bootstrap die Profilrevision, verwerfen eine Recommendation bei parallelem Feedback/Simulation und berechnen sie genau einmal auf dem neuen Modell neu; Revision-Token und Recommendation stammen damit garantiert aus demselben persönlichen Modellstand.
- `open_session` verwendet für die Session exakt das bereits stabilisierte Advice-Modell weiter. Eine Session kann dadurch keinen älteren Recommendation-Zustand mehr konservieren, nachdem ein anderes Gerät das Profil während Forecast-/Kalender-Awaits verändert hat.
- Shared-Directory-Snapshot gehärtet: `profiles` und `preview` liefern eine eigene Directory-Revision. Ändert sich die Profilliste zwischen beiden Requests, verwirft das Frontend die gemischte Generation und lädt die komplette Transaktion sofort neu, statt eine alte Liste als aktuell zu markieren.
- Gleichzeitige UI-Aktionen desselben Profils besitzen nun eine eigene Action-Generation. Eine verspätete Antwort von Session S1 darf eine neuere manuelle Session S2 weder schließen noch mit einer alten Erfolgsmeldung überschreiben.
- Profil-Lösch-Races während laufender Advice-Requests werden nach dem Await erneut geprüft und als `profile_not_found` beantwortet; ein interner `KeyError` kann nicht mehr ungefangen aus `open_session` entkommen.
- Frontend-Cache-Revision für diese Snapshot-/Action-Race-Hardening-Runde auf `ui=11` erhöht.
- Shared-Recovery gehärtet: `jackenberater/profiles` bleibt als sicherer Metadaten-/Recovery-Endpunkt nutzbar, wenn einem Wandtablet live die Shared-Berechtigung entzogen wurde und noch eine fremde Profil-ID ausgewählt ist. Preview/Session/Feedback bleiben weiterhin strikt zugriffsgeschützt.
- WebSocket-Lifecycle gehärtet: Requests werden während Config-Entry-Unload/Reload abgewiesen und nach asynchronen Wartephasen gegen Runtime-/`ProfileManager`-Ownership validiert; ein ersetzter alter Manager kann dadurch keine Sessions, Feedback-Opportunities oder delayed Saves mehr nach dem Reload erzeugen.
- Frontend-Generation-Guard auf Feedback, Setup, Maintenance sowie Backup-Aktionen erweitert; verspätete Antworten eines alten Profils/Entries dürfen Notice, Fehler, Session oder Panelzustand der neuen Auswahl nicht verändern.
- Revision-Poll-Lock besitzt einen Generation-Owner, sodass ein alter Poll nach `setConfig()` die Sperre eines neueren Polls nicht freigeben kann. Diagnose-Simulationen erhöhen eine volatile Profilrevision und werden dadurch auf bereits offenen Karten kurzfristig sichtbar.
- Frontend-Cache-Revision für diese Lifecycle-/Shared-Hardening-Runde auf `ui=9` erhöht.
- Alle asynchronen `open_session`-UI-Pfade sind jetzt an Request-Generation, Profil und Config-Entry gebunden. Verspätete Detail-/Manual-Feedback-Antworten oder Fehler eines alten Profils/Entries dürfen keinen neu ausgewählten Kartenstand mehr überschreiben.
- Kalenderkontext wird recommendationweit aus einer gemeinsamen `context_cache_generation` gelesen: Context-Horizon und Work/Vacation-Fenster werden bei einem Generationwechsel gemeinsam neu geholt; ein zweites Race fällt konservativ auf `unavailable` zurück.
- Cross-Device-Revisionen sind profilbezogen: normale Karten reagieren nur noch auf Änderungen ihres eigenen Lernprofils; Shared/Admin-Auswahl kombiniert Directory-Revision und Revision des ausgewählten Profils. Änderungen fremder Modelle lösen damit keine unnötigen Full-Refreshes anderer Nutzer mehr aus.
- `ws_preview`/`open_session` liefern den nach Advice/Season-Bootstrap aktuellen Profil-Revision-Token. Ein korrektes Saison-Seeding verursacht dadurch 30 Sekunden später keinen redundanten Zweit-Refresh.
- Revision-Polls sind selbst generation-/profil-/entrygebunden und können nach Profil- oder Configwechsel keinen unnötigen Refresh der neuen Karte mehr anstoßen.
- Fehlgeschlagener Platform-Unload (oder Flush/Unload-Exception) setzt `runtime["unloading"]` wieder zurück, solange derselbe Runtime-State geladen bleibt.
- Frontend-Cache-Revision für diese Async-/Revision-Hardening-Runde auf `ui=8` erhöht.
- Read-side Saisonmutation entfernt: Profilübersicht, Diagnostik und Export lesen Modelle jetzt garantiert ohne `prepare_seasons_for()`. Saisoninitialisierung/-Seeding wird ausschließlich beim echten Advice/Open-Session des ausgewählten Profils persistiert; fremde Admin-/Wandtablet-Lesezugriffe können keine künstliche Herbst→Winter→Frühling→Sommer-Kette mehr erzeugen.
- Frontend-Async-Generationen eingeführt: Profilwechsel und `setConfig()` invalidieren laufende Requests; verspätete Antworten dürfen weder das falsche Profil rendern noch neue Kartenkonfiguration mit alten Entry-/Revision-/Entity-Daten überschreiben.
- `setConfig()` lädt eine vorhandene neue Konfiguration sofort vollständig nach, statt Preview/Metadaten bis zum nächsten zufälligen State-Change oder Fallback leer zu lassen.
- Cross-Device-Revision ist nun reload-sicher: der Token kombiniert eine neue Runtime-Generation pro `ProfileManager` mit der lokalen Revision. Ein Config-Entry-Reload wird damit auch bei identischem Integer-Zähler erkannt.
- Ein erstmals gesehener Revision-Token bei noch leerem Kartenstand wird nur als gesehen, nicht als angewendet markiert; erst ein erfolgreicher Full-Refresh setzt die applied revision.
- Teil-Abwesenheits-Wiedereinstieg gehärtet: echte Arbeitszeit hat bei überlappenden Split-Window-Puffern Vorrang, sodass exakt am Wiederbeginn nicht fälschlich „Rund um deine Arbeit“ erscheint.
- Beschädigte/unlesbare `expires_at`-Werte machen unbeantwortete Feedbacksessions nicht mehr unbefristet: Cleanup verwirft sie und `async_feedback()` lehnt verbliebene/injizierte Reste defensiv ab.
- Vorherige Frontend-Hardening-Runde erhöhte die Cache-Revision auf `ui=7`; aktueller Stand ist `ui=13`.
- Frontend-Cachevertrag korrigiert: In der vorherigen Hardening-Runde verwendeten Runtime und Dokumentation beide `ui=6`; die damalige Runde stand auf `ui=7`; aktueller Stand ist `ui=13`; der Package-Test liest die Runtime-Konstante aus und vergleicht sie direkt mit der README statt widersprüchliche Zahlen separat festzuschreiben.
- Frontend-Lifecycle gehärtet: wiederholtes `setConfig()` räumt Revision-Intervalle und Pending-Refresh-Timeouts vor dem Reset auf und startet bei verbundener Karte genau einen neuen Revision-Poll; beim Entfernen bleiben keine Timer verwaist.
- WebSocket-User-Sync besitzt denselben Unload/Reload-Schutz wie der periodische Sync und verwirft sein Ergebnis, wenn während `async_get_users()` der Runtime-Manager ersetzt wurde.
- Kalender- und Session-Zeitparser fangen unmögliche Datumswerte (`ValueError`/`TypeError`) ab, statt Provider-/Storage-Randfälle bis zum gesamten Request bzw. Manager-Load durchschlagen zu lassen.
- Forecast-Fehler-Retry ist quellenspezifisch: ein defekter, aktuell irrelevanter Arbeitsforecast zieht gesunde Home-Beratung nicht mehr in den 1-Minuten-Fehlerretry; relevante Arbeitsfenster behalten den kurzen Retry.
- Automatisches Saison-Seeding/-Initialisieren erhöht jetzt ebenfalls `profile_revision`, damit bereits geöffnete Zweitgeräte diese echte Modelländerung kurzzyklisch erkennen.
- Frontend unterscheidet erkannte von erfolgreich angewendeter `profile_revision`: ein fehlgeschlagener Full-Refresh markiert die neue Revision nicht voreilig als verarbeitet und wird beim nächsten Poll erneut angestoßen.
- Session-Schema/Policy-Generation gehärtet: Pause invalidiert unbeantwortete Sessions vollständig, Resume kann sie nicht wiederverwenden; unbeantwortete Legacy-Sessions ohne aktuelle Signatur werden beim Laden verworfen und serverseitig nicht mehr als Training akzeptiert.
- Multi-Work-Window-Coverage ist reihenfolgeunabhängig: ist mindestens ein Arbeitsfenster abgedeckt und ein anderes nicht, lautet das Ergebnis immer `partial`; nur komplett unversorgte Fenster werden `missing`.
- Zweitgeräte-Synchronisierung verbessert: Profiländerungen wie Feedback, Pause/Resume, Undo oder Reset erhöhen einen leichten Runtime-Revision-Token. Bereits geöffnete Karten prüfen nur diesen Token kurzzyklisch und laden die vollständige Vorschau erst bei echter Änderung neu.
- Forecast-Provider-Härtung: unmögliche Datumswerte werden verworfen statt `ValueError` auszulösen; ein nichtleerer Forecast, dessen sämtliche Zeilen ungültig sind, gilt als fehlgeschlagener Fetch und nutzt den kurzen Retry-Pfad.
- Periodischer User-Verzeichnis-Sync ist gegen Unload/Reload-Races abgesichert: ein bereits wartender alter Callback darf nach Austausch des Runtime-Managers keine Profiländerung oder delayed save mehr auslösen.
- Frühere Frontend-Hardening-Runde erhöhte die Cache-Revision auf `ui=6`; aktuelle Revision ist `ui=13`.
- Session-Reuse besitzt jetzt eine Lern-/Feedback-Policy-Signatur. Innerhalb der 10-Minuten-Deduplizierung werden Sessions nur wiederverwendet, wenn Lernstatus, Recommendation-Confidence, Threshold-/Unusual-Policy und der saisonal relevante Beobachtungstag identisch geblieben sind; reine Cadence-Zähler sind keine Entscheidungsidentität.
- Freiwilliges Sofort-Feedback kann einen noch zukünftigen Jackenwechsel nicht mehr lernen: vor `later_at` werden `Perfekt`, `later` und `all` serverseitig auf den tatsächlich erlebten Startzustand begrenzt.
- Forecast-Abrufe unterscheiden jetzt technisch fehlgeschlagene `weather.get_forecasts`-Calls von erfolgreich leeren Forecasts. Fehlgeschlagene Quellen werden nicht als frischer leerer Forecast konsumiert und nach kurzem Backoff erneut versucht.
- Kalender-Invalidierung schützt nun auch die aktuell wartende Empfehlung: eine während des Requests geänderte Generation verwirft die alte Antwort, versucht einmal frisch und fällt bei einem zweiten Race konservativ auf `unavailable` zurück.
- „Lernen pausieren“ deaktiviert offene Feedbackaufforderungen; Feedback wird während der Pause serverseitig mit `learning_paused` abgewiesen und nicht als erfolgreich übernommene Bewertung markiert.
- Der exakte Engine-Beobachtungszeitpunkt wird als `Recommendation.observed_at` bis in den Start-Lernkontext übernommen; ein zweites `now()` kann Feedback nicht mehr über Mitternacht in einen anderen Saisonmix verschieben.
- Diagnose-Simulationen werden beim Entfernen/Deaktivieren der Diagnose-Entity explizit aus dem Runtime-State entfernt.
- Lovelace reagiert nur noch auf tatsächlich relevante Wetter-/Kalender-/Temperatur-Stateänderungen statt auf beliebige HA-Stateupdates; damalige Frontend-Cache-Revision `ui=6`; aktueller Stand `ui=13`.
- Saisonbewusste Empfehlungs-Confidence wird für die Feedback-Entscheidung unverändert wiederverwendet; eine neue Saison kann dadurch nicht mehr auf der Karte als unsicher erscheinen, während das Session-System sie intern fälschlich als nahezu vollständig gelernt behandelt.
- Während der Saisonüberblendung verhindert jeder saisonale Anker mit mindestens 10 % Einfluss und weniger als 1,0 eigener Real-Evidenz vollständiges `hidden`; reife Nachbarsaisons können eine neue Saison dadurch nicht mehr unsichtbar überstimmen.
- Persistierte alte Threshold-Rohwerte werden beim Laden auf ihre tatsächlich wirksamen Grenzen canonicalisiert. Verdeckte v0.3.1-Überhänge bleiben damit wirkungsgleich, können aber keine neue Scheinevidenz mehr erzeugen. Threshold-Lernen zählt zusätzlich nur noch Bewegungen, die die effektiv verwendete Grenze wirklich verändern.
- Frontend-Follow-up nach einer State-Änderung während eines laufenden Refreshs läuft wieder durch Throttle/Backoff statt unmittelbar rekursiv einen neuen WebSocket-Refresh zu starten.
- Tatsächliche Arbeitszeit ist jetzt ein halboffenes Intervall (`Start <= t < Ende`): exakt am Schichtende beginnt der Pufferkontext und nicht mehr die Formulierung „Für deine Arbeitszeit“.
- Kalendercache besitzt einen Generation-Counter; ein bereits laufender älterer Kalenderrequest darf einen zwischenzeitlich invalidierten Cache nicht wieder mit veralteten Daten befüllen. State-Events invalidieren weiterhin sofort; der JackenBerater-eigene TTL wurde zusätzlich von 15 Minuten auf 1 Minute verkürzt, damit fehlende CRUD-State-Signale keine lange eigene Stale-Phase verursachen.
- Session-Ablaufbereinigung wird auch im Early-Return-Reuse-Pfad von `async_open_session()` persistent vorgemerkt.
- Widersprüchliche Forecast-Dubletten werden pro UTC-Instant deterministisch auf den vollständigsten Datenpunkt reduziert; bei gleicher Vollständigkeit gewinnt der spätere Providereintrag.
- Browser-Dokumentation weist auf vollständiges Neuladen nach Frontend-Updates hin; die Frontend-Cache-Revision wurde zunächst auf `ui=4` erhöht; die vorherige Hardening-Runde verwendete `ui=6`, die aktuelle `ui=13`.
- Kommentar/Dokumentation der Saisonüberblendung präzisiert: 30 aktive Kalendertage entsprechen dem halboffenen Bereich von 15 Tagen vor bis 14 Tagen nach dem meteorologischen Wechsel.
- Arbeitsforecast-Coverage am Schicht-/Pufferende korrigiert: kurze Restfenster dürfen von einem ausreichend frischen Forecastanker abgedeckt werden; vollständig vergangene Fenster sind `not_applicable` statt `missing`.
- Echte Schichtgrenzen bleiben während des ±30-Minuten-Planungspuffers erhalten; das Frontend unterscheidet explizit zwischen tatsächlicher Arbeitszeit und Puffer.
- Kontext-/Termin- und Abwesenheitskalender invalidieren den Kontextcache bei State-Änderungen sofort; ohne entsprechendes Provider-State-Signal begrenzt ein 1-Minuten-TTL die JackenBerater-eigene Cache-Staleness.
- Frisch geseedete Saisonanker mit 0 eigener Evidenz können eine reife Empfehlung auch während der Saisonüberblendung nicht mehr vollständig verstecken, sobald ihr Anteil mindestens 10 % beträgt.
- Windinterpolation im Low-Wind-Übergang monotonisiert: stärkerer Wind kann bei identischen Bedingungen keine leichtere Jacke mehr erzeugen.
- Threshold-Lernen sammelt keine zusätzliche Evidenz mehr, wenn die reale Grenze durch den Mindestabstand zum Nachbar-Threshold blockiert ist.
- Feedback-API normalisiert `later`/`all` ohne tatsächlichen Klassenwechsel auf den Startkontext.
- Forecastpunkte mit identischem realen Zeitstempel werden vor Trend-/Transient-Auswertung dedupliziert.
- Ablaufende unbeantwortete Sessions werden nach RAM-Cleanup auch zur Persistierung vorgemerkt.
- Diagnose-Registry-Cleanup beim Profil-Löschen ist an den Config-Entry-Lifecycle gebunden.
- Frontend merkt State-Änderungen während eines laufenden Refreshs und plant den Nachlauf über den normalen 60-Sekunden-Throttle/Backoff, statt direkte Refreshketten zu erzeugen.
- Custom-Element-Registrierung und `customCards`-Metadaten sind gegen doppeltes Ressourcenladen geschützt.
- Diagnose-Datenschutz dokumentiert; der optional aktivierte Diagnose-Sensor enthält das vollständige persönliche Lernmodell.
- Saisonüberblendung verwendet auf Tagesebene ein echtes 30-Tage-Halboffenintervall.
- Undo-Beschriftung präzisiert auf „Letzte Lernänderung zurücknehmen“.
- Einzelner unbestätigter letzter Forecastpunkt wird sprachlich vorsichtiger als einzelner Hinweis statt als gesicherter „ab dann“-Trend formuliert.
- Lokaler HA-unabhängiger Prüfstand: **306 / 306 Python-Tests**. Der separate HA-Runtime-Smoke-Test bleibt CI-abhängig, wenn das Home-Assistant-Testframework lokal nicht installiert ist.
- Versionsstand projektweit auf **0.3.2** aktualisiert.

## v0.3.1

- First-Season-Seeding gehärtet: Wird eine komplette 30-Tage-Übergangszone nicht benutzt, übernimmt die noch nie initialisierte aktuelle Saison beim ersten späteren Zugriff einmalig den Offset ihrer **direkten** bereits bekannten Vorgängersaison. Evidenz und RunningStats bleiben dabei exakt leer; der Seed liegt bereits vor Empfehlung, Feedback-Snapshot und Undo vor.
- Mehrere vollständig übersprungene Saisons sind jetzt bewusst definiert: Ist die direkte Vorgängersaison unbekannt, wird **keine** rückwirkende Seed-Kette erfunden. Die aktuell erreichte Saison startet neutral und lernt ab dort selbst.
- Der alte undokumentierte Lovelace-`profile_id`-Shortcut wurde aus der Karte entfernt. Profilwahl erfolgt ausschließlich über den serverseitig authentifizierten Eigenprofil-/Shared-/Admin-Pfad.
- README dokumentiert die aktuelle HACS-Installation ausdrücklich als Custom Repository und beschreibt Shared-Rechte präzise für nicht-administrative Shared-Konten.
- CI-Härtung: Runtime-Smoke zusätzlich gegen die deklarierte Mindestversion Home Assistant 2026.6.0 (`pytest-homeassistant-custom-component==0.13.336`) und gegen den jeweils neuesten verfügbaren HA-Teststack; der reproduzierbare aktuelle Job ist auf `0.13.364` aktualisiert.
- Saisonmodell auf Version 4 umgestellt: Winter, Frühling, Sommer und Herbst sind echte eigenständige Offsets zum ganzjährigen `general_offset_c`; normales saisonales Feedback verschiebt Main nicht mehr direkt und rezentriert keine unbeteiligten Jahreszeiten.
- Saisonlernen verwendet die jeweils eigene reale Saison-Evidenz für die Lernrate. Hohe Evidenz verfeinert die Schritte, friert das Modell aber nie vollständig ein; Saisonoffsets besitzen jetzt einen Bereich von **-4,0 bis +4,0 °C**.
- Die bestehende 30-Tage-Smoothstep-Überblendung bleibt erhalten. Feedback in Übergängen trainiert ausschließlich die beiden Nachbarsaisons, verteilt reale Evidenz mit Summe 1,0 und normalisiert den Parameter-Schritt so, dass ein 50/50-Übergang den effektiven Lernschritt nicht halbiert.
- Neue Jahreszeiten werden beim allerersten Übergang einmalig mit dem Offset der Vorgängersaison initialisiert; wurde die komplette Übergangszone verpasst, wird genau dieses Seeding beim ersten späteren Zugriff nachgeholt. Statistik, Evidenz, Confidence und Historie werden nicht kopiert; einmal initialisierte Saisons werden in späteren Jahren nie erneut überschrieben.
- Neuer Vier-Saison-Konsens: Erst ab mindestens 3,0 realem Evidenzgewicht in allen vier Jahreszeiten und nur bei identischem Vorzeichen wird ein gemeinsamer Sockel bis auf ±0,2 °C Rest verlustfrei aus allen Saisonoffsets in Main verschoben. Der Transfer ist vollständig reversibel und erhält `main + saison` exakt.
- Migration von v0.3.0 auf Saisonmodell v4 unterscheidet echte Saisonerfahrung anhand der jeweiligen `RunningStat.weight_sum` von alten Rezentrierungsartefakten. Untrainierte künstliche Saisonwerte werden neutralisiert; tatsächlich trainierte saisonale Wirkung bleibt erhalten. Legacy-Undo-Snapshots werden über dieselbe aktuelle Migration normalisiert.
- Profildiagnostik zeigt pro Jahreszeit den echten `real_weight`, die aktuelle Konsensberechtigung/-richtung und Saisons am ±4-°C-Limit.
- Transient-, Boundary-/Timing-, No-op-, Undo-, Forecast-, Arbeits- und Shared-Tablet-Verhalten bleiben unverändert; neue Regressionstests decken Saison-Isolation, Übergangsnormalisierung, Seeding, Konsens/Umkehrbarkeit, Sättigung und Migration ab.
- Lokaler HA-unabhängiger Prüfstand: **230 / 230 Python-Tests**.
- Versionsstand projektweit auf **0.3.1** aktualisiert; historische Changelog-Versionen bleiben unverändert.

## v0.3.0

- Lernmodell trennt das schnelle persönliche Grundprofil sauber von saisonalen Abweichungen. Ein Feedback erhält nur noch ein gemeinsames Korrekturbudget; Saisonlernen verstärkt denselben Fehler nicht zusätzlich.
- Saisonale Abweichungen werden um den persönlichen Jahresdurchschnitt zentriert. Vorhandene v0.2.x-Profile werden beim Laden so umgerechnet, dass `general + saison` für jede Jahreszeit erhalten bleibt.
- Saisonale Evidenz wird ab dem ersten Feedback gesammelt. Mit mehr Erfahrung in der aktuellen und anderen Jahreszeiten darf ein größerer Teil künftiger Korrekturen saisonspezifisch werden, ohne die schnelle Anfangsanpassung zu bremsen.
- Die vier Saisonwerte bleiben die einzigen gelernten Saisonanker. Rund um März, Juni, September und Dezember werden sie über jeweils einen Monat weich miteinander überblendet, statt am Monatsanfang hart umzuschalten.
- Feedback in einer Übergangsphase wird anteilig auf beide benachbarten Saisonstatistiken verteilt. Der saisonale Lernschritt wird dabei normiert, sodass die wirksame Korrektur weder halbiert noch doppelt gezählt wird; stößt ein Anker an sein Limit, wird der verbleibende Anteil weiterverteilt.
- Feedback zu Empfehlungen mit späterem Jackenwechsel zeigt die ursprüngliche Empfehlung samt Wechselzeit und verwendet konkrete Rückfragen statt abstrakter Phasenbezeichnungen.
- Feedback, dass ein vorhergesagter Wechsel früher oder später hätte erfolgen sollen, trainiert gezielt die betroffene Jackengrenze und verändert nicht zusätzlich Grundprofil oder Saison.
- Ein normales `Keine Jacke` + `zu warm` verändert das persönliche Wärmeprofil nicht, weil keine leichtere Jackenentscheidung existiert. Die Lern-/Undo-Entscheidung stammt jetzt direkt aus dem tatsächlichen Lernpfad: transiente Empfehlungen können weiterhin gezielt `transient_tolerance` lernen und erhalten dafür einen eigenen Undo-Punkt; echte No-op-Bewertungen verbrauchen keinen alten sinnvollen Undo-Punkt.
- Feedback-Undo restauriert nur noch die von der rückgängig gemachten Bewertung trainierbaren Lernfelder. Späteres Pausieren des Lernens, Feedback-Gelegenheiten und spätere No-op-Bewertungen bleiben erhalten; `total_feedback` wird vom aktuellen Stand genau um die rückgängig gemachte Bewertung reduziert.
- Ein erneutes vollständiges Profil-Setup verwirft jetzt alle alten Feedbacksessions samt Undo-, Wetter- und Learning-Context. Dadurch kann weder eine alte Bewertung das neu initialisierte Profil trainieren noch ein alter Undo-Punkt dessen Startparameter zurückdrehen.
- Legacy-v0.2.x-Undo-Snapshots werden beim Laden über die aktuelle `PersonalModel`-Migration normalisiert und anschließend ins kompakte v0.3-Undo-Format überführt. Ein Undo nach einem Upgrade kann damit keine unzentrierten alten Saisonanker mehr in ein v0.3-Modell zurückbringen.
- Aktive Transient-Kompromisse werden nicht mehr vollständig ausgeblendet. Auch bei einem reifen Profil bleibt die Karte mindestens kompakt sichtbar, damit die bewusst geglättete Entscheidung nachvollziehbar und lernbar bleibt.
- Frontend-Cache-Revision auf `ui=2`; Versionsstand projektweit auf **0.3.0**.

## v0.2.0

- Versionsstand projektweit auf **0.2.0** vereinheitlicht: Manifest, Integrationskonstante, README, Bugreport-Vorbelegung, Tests und Lovelace-Ressourcenpfad.
- Enthält den vollständigen v0.1.5-Hardening-Stand einschließlich Forecast-/Lern-/Arbeitskontext-Fixes, Storage-/Lifecycle-Härtung und Shared-Tablet-Logik.
- Responsive Tablet-Karte reagiert auf die tatsächliche Kartenbreite, damit Empfehlungstext in schmalen Dashboard-Spalten nicht mehr zusammengedrückt wird.
- Die letzten CI-Korrekturen für hassfest-Manifestreihenfolge und HA-Runtime-Smoke-Test sind enthalten.
- Lokaler Prüfstand für v0.2.0: **175 Python-Tests** plus Frontend-Vertragstest.

## v0.1.5

### Audit- und Konsistenzrelease

1. **Arbeitswetter ohne Zuhause-Abhängigkeit:** Innerhalb einer tatsächlichen Arbeitszeit kann eine gesunde Arbeits-Wetterquelle die Empfehlung liefern, auch wenn die Zuhause-Entity ausgefallen ist. Der Forecast-Coordinator scheitert ebenfalls erst, wenn keine konfigurierte Wetterquelle mehr nutzbar ist.
2. **Arbeitsforecast-Warnungen bleiben sichtbar:** `missing`/`partial` beim Arbeitsforecast verhindert nun das vollständige Ausblenden der Karte, damit genau diese Datenlücke nicht unsichtbar wird.
3. **Profilweite Session-Deduplizierung:** Nahezu identische bewusste Öffnungen desselben Profils innerhalb von zehn Minuten werden geräte-/loginübergreifend wiederverwendet und zählen nur einmal als Feedback-Gelegenheit.
4. **Wandtablet-Dokumentation korrigiert:** Fälliges Feedback gehört zum ausgewählten Profil und darf auch eine Session beantworten, die zuvor am persönlichen Gerät entstanden ist.
5. **Release-Dokumentation auf v0.1.5 gezogen:** README, Ressourcen-Cache-Buster, Teststand und Versionshinweise sind konsistent; aktuell 172 lokale Python-Tests plus Frontend-Vertragstest.
6. **„Jetzt mitnehmen“ umgesetzt:** Wird später eine wärmere Jacke nötig, formuliert die Karte ausdrücklich, dass diese jetzt mitgenommen werden sollte, falls man dann noch unterwegs ist.
7. **30-Minuten-Regel serverseitig:** Nicht-freiwilliges Feedback wird auch für persönliche Nutzer und Administratoren vor `ready_at` beziehungsweise ohne angefordertes Feedback abgelehnt.
8. **Frontend-Retry-Backoff:** Fehlgeschlagene WebSocket-Aktualisierungen werden zeitlich gedrosselt und bei wiederholten Fehlern bis auf fünf Minuten zurückgenommen, statt auf viele HA-Stateupdates erneut zu feuern.
9. **Stabiler sichtbarer Lernstand:** Der UI-Lernstand ist jetzt ein eigener Fortschrittswert, der im normalen fortlaufenden Lernen nicht wegen schwankender Entscheidungs-Confidence zurückfällt. Reset und Undo dürfen ihn bewusst wieder senken. Die konservative Entscheidungs-Confidence bleibt intern separat.
10. **Abendfrage präzisiert:** Die Startfrage beschreibt nun die tatsächlich verwendete typische Abendaktivität, statt einen nur „länger draußen“-spezifischen Kontext vorzutäuschen.
11. **Arbeitszone präzisiert:** Setup/Reconfigure erklären ausdrücklich, dass die Zone nur einen Anzeigenamen liefert; Präsenz, Koordinaten und Zonenstatus fließen nicht in die Entscheidung ein.
12. **`shared: true` entkoppelt:** Shared-Rechte und Shared-Modus stammen ausschließlich aus `shared_user_ids`; ein Lovelace-Flag kann weder Rechte noch Shared-Verhalten erzeugen.
13. **Mehrere Arbeitsfenster korrekt angezeigt:** Bei mehreren relevanten Fenstern wird das Fenster angezeigt, das den späteren Arbeits-Jackenwechsel tatsächlich ausgelöst hat.
14. **DST-Schichtgrenzen definiert:** Nicht existente lokale Schichtzeiten im Frühlingssprung werden auf die erste gültige Minute vorgezogen; bei der Herbst-Doppelstunde nutzt Start die erste und Ende die zweite Vorkommnis.
15. **Frontend-Registrierungsfehler nicht mehr verschluckt:** Ein unerwarteter `RuntimeError` beim statischen Pfad schlägt sichtbar fehl; erfolgreiche Pfadregistrierung wird separat gemerkt, damit partielle Setup-Retries nicht doppelt registrieren.
16. **Gelöschte HA-Nutzer werden bereinigt:** Nicht mehr vorhandene User-IDs werden aus dem persistenten Profilstore entfernt.
17. **Umbenannte HA-Nutzer werden synchronisiert:** Profilnamen werden beim Profilabruf aus dem aktuellen HA-Benutzerverzeichnis aktualisiert.
18. **`PROJECT_CONTEXT.md` aktualisiert:** Entwicklungsstand, Produktregeln und Teststatus beschreiben nun v0.1.5 statt den alten Importstand.
19. **Reconfigure-Arbeitskontext erklärt:** Auch beim späteren Neu-Konfigurieren ist klar, dass das Arbeitsmodell erst zusammen mit einer Arbeits-Wetterquelle aktiv wird.
20. **Home-Assistant-Single-Entry-Standard:** Das Manifest verwendet `"single_config_entry": true`; der alte eigene Unique-ID-Abbruch im Config Flow wurde entsprechend entfernt.


### v0.1.5 – Release-Hardening nach erneuter Gesamtprüfung

- Karten-UX: „Info“ und die normale Detail-Erweiterung sind jetzt gegenseitig exklusiv; beim Öffnen der einen wird die andere automatisch geschlossen.
- Frontend-only Cache-Revision `ui=3`, damit diese Kartenänderung trotz unveränderter Integrationsversion `0.1.5` sicher neu geladen wird.
- Ein einzelner letzter/unbestätigter Forecast-Punkt darf die aktuelle Jackenklasse nicht mehr über die Kurzzeitglättung überschreiben. Eine spätere Klasse braucht mindestens einen weiteren bestätigenden Forecast-Punkt.
- Bestätigungen für Kurzzeitglättung und „später leichter“ müssen zeitlich zusammenhängen. Zwischen relevanten Forecast-Punkten sind höchstens 90 Minuten Lücke erlaubt; weiter entfernte Punkte gelten nicht als Beweis für einen stabilen Verlauf.
- Nach einem fehlgeschlagenen erzwungenen Forecast-Refresh werden alte Cache-Daten nicht mehr als frischer Forecast weiterverwendet.
- Reconfigure bereinigt nicht mehr aktive Schichtfelder; ein altes `shift_pattern` blockiert eine spätere normale 5-Tage-Konfiguration nicht mehr.
- Offene Shared-Karten verkraften gelöschte Profile sowie Laufzeitwechsel normal ↔ Shared ohne Browserreload und setzen ungültige Profilauswahlen zurück.
- Gelöschte HA-Nutzer räumen zusätzlich Diagnose-Entity-/Registry- und Simulationszustand auf; der Nutzerbestand wird während des Betriebs periodisch synchronisiert.
- Shared-Konten legen/verwenden während des Shared-Betriebs kein eigenes Profil, vorhandene persönliche Lerndaten werden bei einer Rollenänderung aber nicht destruktiv gelöscht.
- Fehlender Arbeits-**Forecast** wird auch genau so bezeichnet und die Warnung nur einmal angezeigt.
- Der englische sichtbare Fortschrittswert heißt jetzt „Learning progress“ statt „Confidence“.
- Der Lernstand gewichtet allgemeines Lernen und Jackengrenzen deutlich stärker als einzelne Spezialkanäle; Reset/Undo dürfen ihn erwartungsgemäß reduzieren.
- README beschreibt die Wind-Chill-Nutzung korrekt als interne Komfortheuristik außerhalb des offiziellen ≤0-°C-Indexbereichs.
- Arbeits-„jetzt mitnehmen“-Text ist konditional: nur wenn man vor dem relevanten Arbeitszeitraum nicht noch einmal nach Hause kommt.
- Ein alter Frontend-State-Refresh-Timer wird bei jedem echten Refresh verworfen.
- Arbeitsforecast wird bei deaktiviertem Arbeitsmodus nicht mehr unnötig gepollt.
- Bugreport-Vorbelegung, interne Aktivitätsbeschreibung und weitere Release-Reste wurden auf v0.1.5 bereinigt.
- Coordinator erhält den `ConfigEntry` explizit und Laufzeitdaten liegen primär in `entry.runtime_data`.
- Beim Entfernen des Config Entries wird die automatisch verwaltete Lovelace-Ressource in Storage-Lovelace mit entfernt.
- Der numerische interne **„thermisch“-Wert** wurde aus der normalen Nutzerkarte entfernt. Er bleibt vollständig in Engine, Lernen und Diagnose erhalten und wird nicht irreführend als „Gefühlt“ umbenannt.

## v0.1.4

### Forecast bleibt frisch

- Der stündliche Wetter-Forecast wird nun wirklich dauerhaft im vorgesehenen 15-Minuten-Intervall aktualisiert. Zuvor hatte der `DataUpdateCoordinator` keinen Listener; dadurch lief nach dem Start nur der erste Forecast und alterte anschließend weg, bis beispielsweise nur noch eine zukünftige Stunde übrig war.
- Vor einer Empfehlung wird ein veralteter oder zeitlich unplausibler Forecast zusätzlich defensiv aktualisiert. Damit kann eine bewusst geöffnete Beratung nicht auf einem alten Cache trainieren.
- Die Forecast-Abdeckung wird gegen den beabsichtigten Horizont geprüft. Ein einzelner verbleibender +1-h-Punkt gilt daher nicht mehr fälschlich als vollständige Abdeckung des normalen 9-h-Zeitraums.
- Providerpunkte werden erst normalisiert und sortiert und danach auf 24 Punkte begrenzt, damit ungewöhnliche Reihenfolgen keine späteren Stunden abschneiden.

### Wandtablet-Feedback pro Profil

- Das bewusste Aufklappen bleibt unverändert der Moment, in dem auf einem Shared-/Wandtablet eine neue Session für das ausgewählte Profil entsteht. Eine bloß sichtbare Karte erzeugt weiterhin keine Session.
- Reifes, angefordertes Feedback ist nun an das ausgewählte Profil gebunden statt an das HA-Login, auf dem die ursprüngliche Session geöffnet wurde. Damit kann z. B. eine am Handy entstandene Sven-Session später am Wandtablet beantwortet werden, sobald dort Sven ausgewählt ist.
- Freiwilliges Sofort-Feedback und Profilwartung bleiben auf nicht-administrativen Shared-Konten weiterhin gesperrt.

## v0.1.3

### Wandtablet-Sessions und Feedback

- Der normale Aufklapp-Pfeil startet auf einem Wandtablet eine Empfehlungssession ausschließlich für das aktuell ausgewählte Profil.
- Eine bloß sichtbare Karte, das eingekreiste Infofeld und ein Tablet ohne gewähltes Profil erzeugen weiterhin keine Session.
- Fälliges Feedback kann auf dem Wandtablet beantwortet werden und nennt das betroffene Profil ausdrücklich. Zugelassen sind nur reife Feedback-Sessions, die dasselbe Shared-Konto zuvor für dasselbe Profil geöffnet hat.
- Profilwechsel löschen den lokalen Session-/Feedbackkontext. Manuelles Sofort-Feedback, Setup, Lernpause, Reset, Undo und andere Wartungsaktionen bleiben auf Shared-Konten gesperrt.

### Sichtbares Lernprofil und sicherer Testmodus

- Die persönliche Karte bündelt die Werte im aufklappbaren Bereich **„Was hat dieses Profil gelernt?“**. Shared-/Wandtablet-Konten erhalten keine detaillierten fremden Lernwerte.
- Pro Profil wird ein kompakter Diagnose-Sensor vorbereitet, aber aus Datenschutzgründen standardmäßig deaktiviert. Ein Administrator kann ihn gezielt zum Troubleshooting aktivieren; sein Zustand zeigt die Zahl der verarbeiteten Bewertungen, seine Modellattribute sind von der Recorder-Historie ausgeschlossen.
- Manuell unter **Entwicklerwerkzeuge → Zustände** gesetzte Sensorwerte werden als flüchtige, begrenzte Simulation ausgewertet und sichtbar als Testmodus markiert.
- Simulationen arbeiten ausschließlich auf einer Modellkopie im Arbeitsspeicher. Dabei entstehen weder Sessions noch Nutzungs-/Feedbackzähler, Lernen, Feedbackkandidaten oder Undo-Änderungen; gespeichertes Modell und gespeicherte Sessions bleiben unverändert.
- Ein echter Profilvorgang oder Neustart verwirft die Simulation und stellt den gespeicherten Stand wieder her.

### Aufräumen und Absicherung

- Profil-Export und -Import bleiben im Code erhalten, sind aber vorerst deaktiviert: keine Karten-Schaltflächen, keine registrierten WebSocket-Befehle und defensive Ablehnung bei direktem Handler-Aufruf.
- Der Vorschau-Crash durch das fehlplatzierte `simulation_active`-Feld ist behoben und wird nun über den echten `ws_preview`-Handler getestet.
- Forecast-, Arbeits-, Kalender-, Cache-, Session- und Feedback-Zeiten werden für Dauer, Vergleich, Sortierung und Schlüssel konsequent als UTC-Zeitpunkte behandelt. Eigene Regressionstests decken Sommerzeitlücke, Winterzeitwiederholung und beide `fold`-Stunden ab.
- Fehlende oder nur teilweise Arbeitsforecast-Abdeckung wird direkt in der normalen aufgeklappten Beratung sichtbar gewarnt, nicht erst im zusätzlichen Infofeld.
- Erfolgreich leere Kalender und nicht erreichbare Kalender werden getrennt behandelt. Bei einem Ausfall bleibt der Kontext sichtbar `unavailable`; ein ausgefallener Abwesenheitskalender deaktiviert vorsichtshalber die Arbeitsortplanung, statt „keine Abwesenheit“ anzunehmen. Die Karte bleibt dafür auch dann sichtbar, wenn sie thermisch sonst ausgeblendet wäre.
- Der Home-Assistant-Runtime-Test nimmt das Repository jetzt ausdrücklich in den Python-Importpfad auf und wird über `python -m pytest` gestartet; dadurch lässt sich `custom_components.jackenberater` auch im isolierten CI-Job zuverlässig importieren.
- Der Testmodus erkennt manuelle Zustandsänderungen über deren Benutzerkontext und besitzt keinen hängenbleibenden „ignoriere nächstes Ereignis“-Schalter mehr.
- Die neue Diagnose-Entität ersetzt nicht die alten v0.1.1-Schalter und Buttons; deren Registry-Einträge und verwaiste Gerätekarte werden beim Start weiterhin bereinigt.
- Teststand v0.1.3: **142 lokale Python-Tests** plus funktionaler Frontend-Vertragstest. CI enthält zusätzlich einen echten Home-Assistant-2026.9-Runtime-Smoke-Test unter Python 3.14 für Setup, Sensorplattform, WebSockets, Reload und Unload.

## v0.1.2

### Audit-Korrekturen vor der Erstveröffentlichung

- Beim Start entfernt die Integration automatisch verwaiste Schalter, Buttons, Diagnosesensoren und die alte Gerätekarte aus der Home-Assistant-Registry. Damit verschwinden nach einem Update die ausgegrauten v0.1.1-Einträge aus der Geräteansicht.
- Shared-/Wandtablet-Konten sind reine Anzeige- und Auswahlkonten. Sie dürfen fremde Profile für Empfehlungen auswählen, aber weder Sessions/Feedback erzeugen noch Setup, Wartung, Undo, Reset oder Export ausführen; Administratoren behalten diese Rechte.
- Shared-Vorschauen enthalten keine offenen Feedbacks, letzte Session oder detaillierte Lernstatistik des ausgewählten Profils.
- Arbeits- und Kalender-Caches akzeptieren nur ein Alter zwischen null und 15 Minuten; zukünftige Zeitstempel nach Uhrkorrekturen erzwingen eine Aktualisierung.
- Ruff-F/E9 läuft in CI, unbenutzte Importe wurden entfernt, Hassfest ist auf einen Commit und die HACS-Action auf Release 22.5.0 gepinnt.
- Profilverändernde Wartungsaktionen und Lerndiagnosen werden nicht mehr als globale Home-Assistant-Entitäten veröffentlicht. Die früheren Plattformdateien sind nur noch inerte Kompatibilitätsplatzhalter, damit ein Überschreiben bestehender GitHub-Repositories keine alte ausführbare Entity-Implementierung zurücklässt. Pausieren, Reset und Undo laufen direkt in der Karte über den authentifizierten WebSocket-Pfad und sind nur für das eigene Profil oder Administratoren erlaubt.
- „Später leichter“ prüft nach einem kurzzeitig extrem milden Ausreißer auch stabil ausreichende, etwas wärmere Jackenstufen. Ein kurzer „keine Jacke“-Punkt verschluckt damit keine später dauerhaft ausreichende leichte Jacke mehr.
- Fehlende Arbeits-Forecastdaten vor einer geplanten Schicht werden in der Karte ausdrücklich als unvollständige Arbeitsempfehlung ausgewiesen; Zuhause-Wetter wird weiterhin nicht als Ersatz für den Arbeitsort verwendet.
- `snowy` und `hail` lösen neben dem thermischen Nässeeffekt nun auch die separate Niederschlagsschutz-Empfehlung aus.
- Kalender- und Arbeitshorizonte werden auch über Sommer-/Winterzeitwechsel in echten verstrichenen Stunden begrenzt.
- Nicht endliche oder unplausible Providerwerte werden verworfen: Temperatur, Wind, Feuchte, Bewölkung, Niederschlagswahrscheinlichkeit und Niederschlagsmenge besitzen großzügige fachliche Grenzen.
- Pakettests lesen UTF-8-Dateien unter Windows ausdrücklich mit `encoding="utf-8"`.
- Regressionsteststand auf 115 Python-Fälle erweitert; der Frontend-Zeittest berücksichtigt die lokale Browser-Zeitzone.

### Persönlicher Verlauf statt minutengenauer Jackenwechsel

- Neue **Trend-/Kurzzeitlogik**: Ein sehr kurzer Übergang entscheidet nicht mehr automatisch allein über die Hauptjacke.
- Unter ungefähr 15 Minuten wird eine einzelne Zwischenstufe als möglicher Übergang behandelt; darüber entscheidet keine starre Zeitregel, sondern die kumulierte Abweichung zur **persönlich gelernten Jackengrenze**, die Dauer und der weitere thermische Verlauf.
- Kurze Übergänge werden nur geglättet, wenn der restliche relevante Zeitraum die Richtung bestätigt; `Warm → Leicht → Warm` bleibt damit weiterhin geschützt.
- Die praktische Empfehlung kann einen kurzen aktuellen Restzustand bewusst übergehen, ohne die rohe thermische Sofortbewertung zu verlieren (`instant_jacket`).
- Ein eigener, eng begrenzter `transient_tolerance`-Wert lernt aus genau solchen Situationen. Feedback auf eine geglättete Übergangsentscheidung verschiebt nicht pauschal die normalen Jackengrenzen.
- Spätere Kälte wird transparent formuliert, z. B. **„Leichte Jacke reicht aktuell. Wenn du länger unterwegs bist, wird ab etwa 18:00 eine warme Jacke sinnvoll.“**
- Arbeitskontext kann einen späteren Zeitraum als wahrscheinlich relevant kennzeichnen; unbekannte Aufenthaltsdauer wird nicht als Wissen ausgegeben.

### Saisonale Feinanpassung

- Vier kleine, fest begrenzte saisonale Korrekturwerte ergänzen das persönliche Langzeitprofil.
- Saisonales Lernen beginnt erst nach etwas allgemeiner Erfahrung und lernt deutlich langsamer als das Hauptprofil.
- Keine saisonale Feedbackhistorie: Es bleiben nur kompakte Running-Stats und Bias-Werte gespeichert.

### Wandtablet & Transparenz

- Shared-/Wandtablet-Konten merken das ausgewählte Nutzerprofil **lokal im Browser**. Die Auswahl überlebt Dashboardwechsel, Browser-/HA-/Tablet-Neustarts und bleibt bestehen, bis sie bewusst gewechselt wird.
- Die lokale Auswahl ist zusätzlich an Integration und angemeldetes Shared-Konto gebunden und wird nicht serverweit synchronisiert.
- Neues **ⓘ-Infofeld** mit Forecast-Horizont, Aufenthaltsannahme, thermischem Trend, Forecast-Abdeckung, persönlicher Confidence sowie Hinweisen auf aktive Kurzzeit-/Saisonanpassung.

### Lernprofil sichern

- Kompaktes persönliches Lernprofil kann als versionierte JSON-Datei exportiert werden.
- Import/Restore stellt die Lernparameter wieder her und verwirft bewusst alte Sessions.
- Backup enthält keine Wetterhistorie und keine wachsende Sessionhistorie.
- Eigene Profile dürfen selbst wiederhergestellt werden; das Überschreiben fremder Profile bleibt Administratoren vorbehalten.

### Tests

- Regressionstests für kurze Erwärmung/Abkühlung, starke Kurzzeitabweichungen, spätere statt sofortige Jackenwechsel, isoliertes Kurzzeitlernen, saisonales Lernen, Profil-Export/Import und lokale Wandtablet-Persistenz.
- Teststand v0.1.2: **108 Python-Tests** plus funktionaler Frontend-Vertragstest.


Alle veröffentlichten Änderungen werden in dieser Datei gesammelt.

## v0.1.1

### Release-Kandidaten-Cleanup

- Wenn Arbeitskontext den Betrachtungszeitraum über 12 Stunden hinaus erweitert, wird die normale Home-/Forecast-Timeline jetzt bis zur gleichen tatsächlichen Endreichweite ausgewertet. Ein vorhandener Home-Kälteeinbruch zwischen 12 und 16 Stunden kann dadurch nicht mehr von einem späteren Work-Punkt übersprungen werden.
- Vollständiges Ausblenden der Karte verlangt Forecast-Abdeckung bis zum tatsächlich behaupteten Empfehlungshorizont, nicht nur bis zum normalen 9-Stunden-Basisfenster.
- „Feedback manuell abgeben“ holt beim Anklicken immer eine aktuelle Backend-Session. Ein lange geöffnetes Detailpanel kann damit keine alte Wetter-/Empfehlungssession mehr trainieren.
- Lokales HACS/Home-Assistant-Branding unter `custom_components/jackenberater/brand/icon.png` ergänzt und den `brands`-Ignore aus der HACS-Action entfernt.
- Custom-Integration-Übersetzungen liegen vollständig unter `translations/`; die nicht mehr verwendete `strings.json` wurde entfernt und DE/EN-Reconfigure-Texte wurden strukturell angeglichen.
- Zusätzliche Regressionstests für Work-erweiterten Home-Horizont und frische manuelle Feedback-Sessions.

### Adversarial-/Regression-Härtung

- Die bereits behobene „später leichter“-Logik ist wieder dauerhaft abgesichert: Eine leichtere Jackenstufe wird erst genannt, wenn die leichteste erreichte Stufe für den restlichen relevanten Zeitraum ausreicht. Der dazugehörige Regressionstest bleibt bestehen.
- Reine zukünftige Regenhinweise lösen kein thermisches Active-Learning-Feedback mehr aus. Regenberatung bleibt vollständig erhalten, trainiert aber nicht versehentlich den aktuellen Wärme-Kontext.
- „Perfekt“ bei leichter/warmer Jacke bestätigt nicht mehr pauschal beide angrenzenden Jackengrenzen. Wenn der effektive Temperaturpunkt bekannt ist, wird nur die tatsächlich nächstliegende Grenze sicherer.
- Der 30-Minuten-Planungspuffer nach Arbeitsende bleibt auch bei einer frischen Context-Berechnung erhalten und hängt nicht mehr vom Cache-Zeitpunkt ab.
- `partlycloudy` erzeugt ohne explizite Tageslichtinformation keinen garantierten Sonnenbonus mehr; `sunny` bleibt weiterhin ein positiver Sonnenhinweis.
- Die schnelle Start-Lernphase richtet sich jetzt nach der gewichteten Erfahrung. Ein als „ungewöhnlich“ markierter Tag mit Gewicht 0,30 zählt nicht mehr wie eine volle normale Bewertung für die Modellreife.
- Der Work-Horizont verwendet echtes `math.ceil()` statt einer Näherungsformel.
- „Nicht genutzt“ bzw. nicht lernendes Feedback verbraucht nicht mehr die Undo-Möglichkeit der vorherigen echten Modelländerung.
- Beim Laden werden beschädigte numerische Storage-Werte typisiert, auf sichere Bereiche begrenzt bzw. auf Defaultwerte zurückgesetzt, statt später die Engine zum Absturz bringen zu können.
- Der englische Text für „später leichter“ nennt jetzt wie der deutsche Text die tatsächlich ausreichende Ziel-Jackenstufe.
- Basis-Jackengrenzen liegen nun zentral in `const.py`, damit Engine und Lernmodell dieselben Grenzwerte verwenden.
- Zusätzliche Regressionstests für Stable-Lighter, Regen/Active-Learning, Perfect-Grenzconfidence, gewichtete Lernreife, Post-Work-Puffer, Nacht-`partlycloudy`, Undo und Storage-Sanitisierung.

### Finale Zeit-/Kontext-Härtung

- Arbeits-Forecastpunkte und Arbeitsfenster sind defensiv auf den globalen Maximalhorizont von 16 Stunden begrenzt. Wetter oder Regen jenseits dieses Fensters kann keine angebliche 16-Stunden-Empfehlung mehr bestimmen.
- Wenn ein Arbeitskontext einen vorher erkannten späteren Jackenwechsel wieder auf die aktuelle Jackenstufe zurücksetzt, werden die `later_*`-Felder konsequent geleert. Dadurch kann kein zukünftiger Zustand mehr zu frühes oder falsch zugeordnetes Feedback auslösen.
- Automatisches Feedback wird nur noch von Start-/Später-Kontexten ausgelöst, die tatsächlich in der Session gespeichert und später gelernt werden können.
- „Neu konfigurieren“ ersetzt jetzt bewusst den vollständigen Config-Entry-Datensatz. Sichtbar geleerte optionale Felder wie Innenraumsensor, Kalender, Arbeitswetter oder Arbeitszone bleiben dadurch nicht heimlich mit alten Werten gespeichert.
- Vollständiges Ausblenden der Karte erfordert jetzt eine echte, annähernd stündliche Forecast-Abdeckung bis zum normalen Horizont; ein einzelner Punkt bei +9 h reicht nicht mehr.
- Regenfolgen werden bei Forecast-Lücken über 90 Minuten getrennt bewertet.
- Der Grund „persönliches Profil“ erkennt auch gelernte Wind-/Übergangsempfindlichkeit, wenn diese die Jackenklasse tatsächlich verändert.
- „Später leichter“ wird präziser als „ab dann reicht voraussichtlich …“ formuliert.
- Zusätzliche Regressionstests für 16-h-Work-Grenze, Work-Override/Lernziel, Reconfigure-Clearing, Forecast-Abdeckung und Regenlücken.

### Engine-Finalisierung

- Die adaptive 9→12-Stunden-Erweiterung prüft jetzt **alle** zusätzlichen Forecastpunkte. Kurze Kälte-, Wind- oder Regenereignisse zwischen Stunde 9 und 12 können nicht mehr verschwinden, nur weil Stunde 12 wieder mild ist.
- Windwirkung verläuft an niedrigen Windgeschwindigkeiten und rund um den Übergang aus dem klassischen Wind-Chill-Bereich nun weich statt sprunghaft.
- Die Feuchtekorrektur wird um ihre Temperaturgrenzen weich ein- und ausgeblendet.
- Bei einer späteren Jackenänderung übernimmt die Empfehlung auch die tatsächlichen Gründe des entscheidenden späteren Punkts, z. B. Wind oder Sonne.
- Der Grund „persönliches Profil“ wird auch dann gesetzt, wenn gelernte Jackengrenzen die konkrete Jackenklasse gegenüber den Basisgrenzen verändern.
- „Nahe an der Grenze“ berücksichtigt jetzt den gesamten relevanten Forecast-/Arbeitskontext und nicht nur den aktuellen Zeitpunkt.
- Ohne Hourly-Forecast wird kein künstlicher 1-Stunden-Horizont mehr behauptet; die Karte kennzeichnet die Bewertung als „nur jetzt“.
- Der Arbeitsbereich erklärt nun ausdrücklich, dass Arbeitsmodell und -zeiten erst mit einer gewählten Arbeits-Wetterquelle aktiv werden.
- Zusätzliche Regressionstests für kurze Kälte-/Windpeaks, Wind-/Feuchte-Kontinuität, spätere Gründe, personalisierte Grenzentscheidungen und Forecast-Horizont.

### Letzte Logik-/HA-Korrekturen vor Veröffentlichung

- Reconfigure nutzt bei aktivem Config-Entry-Update-Listener den nicht-reloadenden Home-Assistant-Helper und vermeidet damit den seit Core 2026.6 deprecated doppelten Reload.
- Urlaub/Abwesenheit wird zuerst von der tatsächlichen Arbeitszeit abgezogen; Planungsfenster entstehen erst aus den verbleibenden Arbeitsabschnitten. Eine komplett ausfallende Schicht hinterlässt damit keine künstlichen ±30-Minuten-Puffer.
- Regen am Arbeitsort wird als Zukunftsprognose bewertet. Der erste zukünftige Work-Punkt wird nicht mehr so behandelt, als würde es bereits jetzt regnen.
- Während einer tatsächlichen Arbeitszeit wird bei fehlenden aktuellen Arbeitswetterdaten nicht still auf Zuhause-Wetter zurückgefallen.
- Die neutrale Aktivitätsantwort „Gemischt“ ist jetzt thermisch exakt neutral.
- Profilumbenennungen senden ein Update-Signal an bereits vorhandene HA-Entities.
- Identische Start-/Endzeiten für Arbeit oder Schichten werden im Config Flow abgelehnt und zusätzlich in der Zeitlogik abgesichert.
- Böen werden in den Kartendetails sichtbar, wenn sie über dem Grundwind liegen.
- Bei einer später nötigen wärmeren Jacke sagt die Karte ausdrücklich, dass sie **jetzt mitgenommen** werden sollte, wenn man dann noch unterwegs ist.
- Zusätzliche Regression-/Glue-Tests für Reconfigure, Abwesenheitspuffer, Work-Regen und Arbeitswetter-Fallback.

### Weitere Korrekturen vor Veröffentlichung

- Vergangene Arbeits-Forecastpunkte können keine spätere Empfehlung mehr beeinflussen.
- „Perfekt“ bestätigt bei einem Jackenwechsel automatisch Anfang und spätere Jackenstufe.
- Windlernen wird an den tatsächlich angewandten Windeffekt gekoppelt, nicht an rohe Böenspitzen.
- Eine Session wird nur wiederverwendet, wenn der relevante Lernkontext weiterhin praktisch identisch ist.
- Junge/unsichere Profile bleiben auch bei eindeutig „keine Jacke“ kompakt erreichbar statt vollständig zu verschwinden.
- Der ±30-Minuten-Arbeitspuffer dient nur der Planung; die aktuelle Wetterquelle wechselt erst während der tatsächlichen Arbeitszeit.
- Die vierte Startfrage misst jetzt direkt typische Aktivität bei längeren Abendaufenthalten statt Ausgeh-Häufigkeit.
- Recommendation-Confidence beschreibt die konkrete Jackenentscheidung.
- Freiwilliges Feedback erhält normales Gewicht; „ungewöhnlicher Tag“ bleibt bewusst reduziert.
- Kleine Frontend-/String-Korrekturen und zusätzliche Regressionstests.


### Geändert

- **Gemeinsame Wandtablets werden automatisch erkannt:** Ein in der Integration freigegebener Shared-/Tablet-HA-Benutzer bekommt kein eigenes Wärmeprofil mehr. Die Karte fragt direkt, für welches vorhandene Nutzerprofil die Beratung gedacht ist.
- **Feedback wird nicht mehr sofort nach dem Öffnen angeboten:** Eine normale Feedback-Anfrage wird frühestens 30 Minuten nach der aktuellen Empfehlung bereit. Wenn die Empfehlung ausdrücklich auf einen späteren Jackenwechsel abzielt, wird sie erst 30 Minuten nach diesem Zeitpunkt automatisch zur Bewertung angeboten.
- **Freiwilliges Feedback bleibt jederzeit möglich:** In den Details gibt es einen kleinen, bewussten „Feedback manuell abgeben“-Weg, ohne dass frisch erzeugte Empfehlungen sofort mit Bewertungsbuttons überladen werden.
- **Arbeitskalender ist nicht mehr erforderlich:** Für normale Arbeitszeiten wird standardmäßig Montag bis Freitag von 08:00 bis 17:00 Uhr angenommen, jeweils mit 30 Minuten Puffer davor und danach.
- **Arbeitsmodell auswählbar:** Arbeit nicht berücksichtigen / normale 5-Tage-Woche / rotierendes Schichtsystem.
- **Rotierende Schichten bleiben unterstützt:** z. B. `F,F,S,S,N,N,N,X,X` mit Ankerdatum und eigenen Früh-/Spät-/Nachtzeiten.
- Ein optionaler Urlaubs-/Abwesenheitskalender kann weiterhin wahrscheinliche Arbeitszeiträume unterdrücken, ohne Arbeit selbst zu erzeugen.
- Bestehende v0.1.0-Konfigurationen werden auf das neue Arbeitsmodell migriert; ein vorhandener Schichtzyklus bleibt erhalten, sonst wird auf die normale 5-Tage-Woche umgestellt.

### Technisch

- Integration/Frontend-Cache-Version auf **0.1.1** erhöht.
- Config-Entry-Schema auf Minor-Version **1.1** migriert.
- Zusätzliche Regressionstests für Feedback-Reife, Standard-Arbeitswoche, Wochenende, Schichtmodus und Frontend-Feedbackdarstellung.

## v0.1.0

- Erste Testversion des JackenBeraters.
- Persönliche Jackenstufen, Wetterverlauf und separater Regenschutz.
- Lernprofile pro Home-Assistant-Benutzer mit kompaktem, inkrementellem Lernen.
- Innen→Außen-Effekt, Wind/Böen, optionale Kalender-/Arbeitskontexte und rotierende Schichtzyklen.
- Eigene Lovelace-Karte und Shared-Profile-Unterstützung.
