# JackenBerater – Projektkontext

Dieses lokale Projekt wurde ursprünglich am 2. September 2026 aus dem ChatGPT-Projekt „Jackenberater“ übernommen und seitdem als Home-Assistant-Custom-Integration weiterentwickelt.

- Quellprojekt: https://chatgpt.com/g/g-p-6a983d3dc0288191b241cbfcd430cacf-jackenberater/project
- Übernommener Chat: „Kältegefühl Tracken“
- Aktueller Entwicklungsstand: **JackenBerater v0.3.1**
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
- Profil-Export/-Import ist im Code vorhanden, aber in v0.3.1 weiterhin deaktiviert. Der alte undokumentierte Lovelace-`profile_id`-Shortcut wurde aus der Karte entfernt; Profilwahl erfolgt ausschließlich über den authentifizierten Eigenprofil- bzw. Shared-/Admin-Flow.
- Diagnose-Sensoren sind standardmäßig deaktiviert und ihre Modellattribute von der Recorder-Historie ausgeschlossen.
- Der Test-/Simulationsmodus darf weder Sessions noch Feedback-Gelegenheiten, Lernen oder Undo-Zustand verändern.

## Letzter lokal verifizierter Prüfstand

- **230 / 230 Python-Tests bestanden** (`pytest -q tests --ignore=tests/ha_runtime`)
- funktionaler JavaScript-/Frontend-Vertragstest bestanden
- Python-Dateien kompilierbar
- JavaScript-Syntaxprüfung bestanden
- JSON-Dateien syntaktisch gültig

Der separate Home-Assistant-Runtime-Smoke-Test liegt unter `tests/ha_runtime`. CI führt ihn gegen den deklarierten Mindeststand Home Assistant 2026.6.0, einen reproduzierbar gepinnten aktuellen Teststack sowie zusätzlich gegen den jeweils neuesten verfügbaren `pytest-homeassistant-custom-component`-Stand aus.

## Wichtige Produktentscheidung

Eine Jackenstufe soll nicht wegen eines winzigen Zeitfensters zur Hauptempfehlung werden. Kurzzeitphasen werden anhand von Dauer, persönlicher Grenzabweichung und weiterem thermischem Verlauf bewertet. Kleidung unter der Jacke wird nicht abgefragt.

- Laufzeitdaten eines geladenen Config Entries liegen in `entry.runtime_data`; `hass.data[DOMAIN]` bleibt nur für integrationsglobale Frontend-/API-Marker.
- Der Forecast-Coordinator erhält den `ConfigEntry` explizit und die automatisch verwaltete Lovelace-Ressource wird beim endgültigen Entfernen des Eintrags aufgeräumt.
