# JackenBerater v0.1.0 – zweite Review-Runde

Grundlage war die zweite unabhängige Prüfliste für den noch **unveröffentlichten** Entwicklungsstand v0.1.0. Versionssprung und Migration zwischen den internen Zwischen-ZIPs sind deshalb bewusst **kein Release-Thema**; funktionale Funde wurden dagegen erneut gegen den tatsächlichen Code geprüft.

## Ergebnis

| Fund aus Review | Status | Umsetzung |
|---|---|---|
| Neue Session wird nach Cleanup nicht persistent gespeichert | ✅ behoben | Liste wird erst **nach** Cleanup neu geholt; Regressionstest deckt `open_session → latest_session → feedback` ab. |
| Migration alter v0.1.0-Daten | ⏭️ nicht erforderlich | Noch keine Version veröffentlicht/installiert; erste echte Veröffentlichung bleibt v0.1.0. |
| Beide Builds heißen v0.1.0 | ⏭️ bewusst | Entwicklungsstände vor dem ersten Release. |
| Feedbackpolicy kann bei bestimmten `total_feedback`-Werten einfrieren | ✅ behoben | Periodisches Sampling nutzt jetzt einen separaten `feedback_opportunities`-Zähler für bewusste Beratungen. |
| Pausiertes Lernen erhöht `total_feedback` | ✅ behoben | Bei pausiertem Lernen verändern Feedbacks weder Lernwerte noch Lernzähler/Cadence. |
| Aktiver Arbeitsort ohne Work-Hourly mischt später Home-Wetter hinein | ✅ behoben | Home-Forecastpunkte im Arbeitsfenster werden auch ohne Ersatz-Work-Forecast entfernt; eine Lücke ist besser als falscher Ort. |
| Ein Activity-/Abendwert gilt für alle Forecaststunden | ✅ behoben | Aktivitätskorrektur wird pro `WeatherPoint.dt` berechnet. |
| Wärmerwerden speichert keinen echten späteren Lernkontext | ✅ behoben | `later_point`/`later_result` werden auch bei sinkender Jackenklasse gesetzt. |
| `PHASE_ALL` lernt nur aus später | ✅ behoben | Globales Signal einmal, Start-Kontext und Later-Kontext getrennt; kein doppeltes `total_feedback`. |
| Nicht angeforderte Sessions zählen/verdängen Feedback-Kandidaten | ✅ behoben | Max. 3 gilt nur für angeforderte offene Kandidaten; diese werden zusätzlich im 20er-Ring vor manuellen Sessions geschützt. |
| Jeder HA-Nutzer kann fremde Shared-Profile manipulieren | ✅ behoben | Cross-Profile-Zugriff nur für HA-Admins oder explizit in der Integration freigegebene Konten. |
| Teilweise Abwesenheit löscht komplette Schicht | ✅ behoben | Zeitfenster werden subtrahiert und bei Bedarf aufgeteilt. |
| Arbeitskalender fällt bei leerem Tag auf Schichtzyklus zurück | ✅ behoben | Wenn ein Arbeitskalender konfiguriert ist, ist er autoritativ: leer = frei. |
| 9 Stunden sind nur 9 Forecast-Punkte | ✅ behoben | Auswahl basiert auf tatsächlicher Zeitdifferenz zum aktuellen Punkt. |
| Winterjacke-zu-kalt erhöht Wintergrenzen-Confidence | ✅ behoben | In diesem Fall lernt nur die globale Kälteempfindlichkeit, nicht eine nicht vorhandene wärmere Grenze. |
| „Ungewöhnlicher Tag“ ist im Frontend nicht erreichbar | ✅ behoben | Checkbox in normalem und phasenbezogenem Feedback; reduziertes Gewicht wird ans Backend gesendet. |
| Shared-Setupwerte bleiben beim Profilwechsel erhalten | ✅ behoben | Setup-Skalen werden beim Wechsel auf neutrale Defaults zurückgesetzt. |
| Beschädigte `RunningStat`-Daten können vor Fallback crashen | ✅ behoben | Konstruktion liegt vollständig im geschützten Parse-Pfad; Regressionstest mit ungültigen Typen. |
| Vergangene Forecastpunkte zählen gegen den Horizont | ✅ behoben | Nur Punkte mit `dt > current.dt` werden verwendet. |
| Work-Punkte werden unnötig doppelt bewertet | ✅ behoben | Einmal berechnete Work-Assessment-Paare werden wiederverwendet. |
| Neue Entities sind hart deutsch benannt | ✅ behoben | Übersetzungs-Keys + Platzhalter für DE/EN. |
| Versionsnummer an mehreren Laufzeitstellen hartcodiert | ✅ weitgehend behoben | Entities und Frontend-Resource verwenden `INTEGRATION_VERSION`; Manifest bleibt HA-bedingt deklarativ. Ein Test prüft Manifest ↔ Runtime-Konstante. |
| HACS Workflow `ignore: brands` | 🟡 Release-Vorbereitung | Für die jetzige unveröffentlichte Entwicklungs-/Custom-Repo-Phase kein Funktionsblocker. Vor einem HACS-Default-PR muss das separat sauber gemacht werden. |

## Zusätzlich abgesichert

- Feedback-Sessions bleiben pro Profil begrenzt und der Speicher wächst nicht mit der Gesamtzahl historischer Bewertungen.
- Unangeforderte/manuelle Sessions können eine noch offene systemseitige Feedback-Anfrage nicht mehr allein durch den 20er-Ring verdrängen.
- Ein leerer, explizit ausgewählter Arbeitskalender wurde mit einem Regressionstest gegen einen gleichzeitig vorhandenen rotierenden Schichtzyklus abgesichert.
- Kaputte Lernstatistik-Daten fallen auf ein frisches, funktionsfähiges Modell zurück statt das Laden des Profils zu blockieren.

## Lokale Prüfungen

- `pytest`: **35/35 bestanden**
- Python `compileall`: bestanden
- JavaScript `node --check`: bestanden
- alle JSON-Dateien: valide

Ein vollständiger Start in einer realen Home-Assistant-Instanz ist in dieser Arbeitsumgebung nicht möglich. HACS/hassfest bleiben deshalb zusätzlich Teil des GitHub-CI-Workflows.
