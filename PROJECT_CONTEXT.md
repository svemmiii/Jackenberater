# JackenBerater – Projektkontext

Dieses lokale Projekt wurde ursprünglich am 2. September 2026 aus dem ChatGPT-Projekt „Jackenberater“ übernommen und seitdem als Home-Assistant-Custom-Integration weiterentwickelt.

- Quellprojekt: https://chatgpt.com/g/g-p-6a983d3dc0288191b241cbfcd430cacf-jackenberater/project
- Übernommener Chat: „Kältegefühl Tracken“
- Aktueller Entwicklungsstand: **JackenBerater v0.1.5**
- Zielumgebung der CI: Home Assistant 2026.9, Runtime-Smoke-Test unter Python 3.14

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
- Persönliche Kurzzeit-/Trend- und Saisonanpassungen bleiben begrenzt und ergänzen das allgemeine Wärmeprofil, statt es zu ersetzen.
- Der sichtbare „Lernstand“ ist ein eigener Fortschrittswert, der im normalen fortlaufenden Lernen nicht durch schwankende Entscheidungs-Confidence zurückfällt; Reset und Undo dürfen ihn bewusst senken. Allgemeine Erfahrung und Jackengrenzen zählen stärker als einzelne Spezialkanäle.
- Die Arbeitszone dient nur als Anzeigename. Präsenz, Koordinaten oder Zonenstatus werden nicht zur Standortentscheidung verwendet.

## Wartungs- und Datenschutzregeln

- Profile sind an Home-Assistant-User-IDs gebunden. Gelöschte HA-Nutzer werden aus dem JackenBerater-Store entfernt; umbenannte Nutzer werden beim Profilabruf synchronisiert.
- Profil-Export/-Import ist im Code vorhanden, aber in v0.1.5 weiterhin deaktiviert.
- Diagnose-Sensoren sind standardmäßig deaktiviert und ihre Modellattribute von der Recorder-Historie ausgeschlossen.
- Der Test-/Simulationsmodus darf weder Sessions noch Feedback-Gelegenheiten, Lernen oder Undo-Zustand verändern.

## Letzter lokal verifizierter Prüfstand

- **172 / 172 Python-Tests bestanden** (`pytest -q tests --ignore=tests/ha_runtime`)
- funktionaler JavaScript-/Frontend-Vertragstest bestanden
- Python-Dateien kompilierbar
- JavaScript-Syntaxprüfung bestanden
- JSON-Dateien syntaktisch gültig

Der separate Home-Assistant-Runtime-Smoke-Test liegt unter `tests/ha_runtime` und wird in CI mit installiertem Home-Assistant-Testframework ausgeführt.

## Wichtige Produktentscheidung

Eine Jackenstufe soll nicht wegen eines winzigen Zeitfensters zur Hauptempfehlung werden. Kurzzeitphasen werden anhand von Dauer, persönlicher Grenzabweichung und weiterem thermischem Verlauf bewertet. Kleidung unter der Jacke wird nicht abgefragt.

- Laufzeitdaten eines geladenen Config Entries liegen in `entry.runtime_data`; `hass.data[DOMAIN]` bleibt nur für integrationsglobale Frontend-/API-Marker.
- Der Forecast-Coordinator erhält den `ConfigEntry` explizit und die automatisch verwaltete Lovelace-Ressource wird beim endgültigen Entfernen des Eintrags aufgeräumt.
