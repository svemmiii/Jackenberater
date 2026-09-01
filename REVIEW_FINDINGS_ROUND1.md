# Review der gemeldeten Einschätzungen – JackenBerater v0.1.0

Die Prüfliste wurde gegen den **tatsächlich vorliegenden aktuellen Quellstand** geprüft. Mehrere Punkte bezogen sich erkennbar auf einen älteren Zwischenstand (Zeilennummern und beschriebenes Verhalten existierten im aktuellen Stand bereits nicht mehr). Echte oder teilweise noch vorhandene Probleme wurden behoben.

| Fund aus der Prüfliste | Ergebnis im geprüften Stand | Maßnahme |
|---|---|---|
| Frontend aktualisiert nur einmal | **Teilweise berechtigt** – es gab bereits einen 5-Minuten-Timer, aber aktuelle HA-Zustandsänderungen konnten bis dahin sichtbar veraltet bleiben | HA-Updates lösen jetzt ressourcenschonend höchstens einmal pro Minute einen Refresh aus; 5-Minuten-Fallback bleibt |
| `_error` bleibt dauerhaft gesetzt | **Teilweise berechtigt** – erfolgreicher Preview-Refresh löschte den Fehler bereits, andere erfolgreiche Aktionen nicht immer | Fehlerzustand wird nach erfolgreichen Aktionen konsistent zurückgesetzt |
| „Perfekt“ erhöht keine Threshold-Samples | **Berechtigt in der Lernlogik** – das Verhalten war inkonsistent und bestätigte nicht alle relevanten Grenzen | „Perfekt“ bestätigt jetzt die zur Jackenklasse gehörenden Grenzwerte ohne sie zu verschieben |
| Threshold-Confidence bleibt dadurch 0 / Feedback nervt dauerhaft | **Ursprüngliche Begründung war im aktuellen Stand nicht exakt**, weil die Feedbackpolicy nur die globale Confidence nutzte | Feedbackpolicy nutzt jetzt zusätzlich eine konservative, empfehlungsspezifische Jackengrenzen-Confidence |
| Test prüft Threshold-Samples nicht | **Berechtigt** | Expliziter Regressionstest ergänzt |
| Home- und Work-Wetter konkurrieren gleichzeitig | **Berechtigt** | Während eines Arbeitsfensters ersetzt Work-Wetter die Home-Punkte derselben Zeit statt zusätzlich daneben zu stehen |
| „Jetzt“ bleibt Zuhause obwohl Schicht schon läuft | **Im aktuellen Stand bereits behoben** | Aktiver Arbeitszeitraum verwendet bereits Work-Current; Verhalten beibehalten und Timeline danach verbessert |
| Shared-Profilname kann vom Tablet überschrieben werden | **Im aktuellen Stand bereits behoben** | Fremdprofil wird nicht erneut mit dem Namen des Tablet-Users „sichergestellt“ |
| Shared Tablet behält letztes Profil gefährlich bei | **Berechtigt** | Shared-Modus verlangt explizite Profilauswahl und setzt sie beim Schließen der Beratung zurück |
| Frontend ignoriert `ok:false` bei Feedback | **So im aktuellen Stand nicht mehr vorhanden** – WebSocket-Fehler werden als Promise-Fehler behandelt | Zusätzlich wird doppelt eingereichtes/abgelaufenes Feedback backendseitig klar abgelehnt |
| beantwortete Session wird erneut verwendet | **Im aktuellen Stand bereits behoben** (`feedback is None` war Bedingung) | Regression beibehalten |
| 20 Sessions gelten global statt pro User | **Im aktuellen Stand bereits behoben** | Ringpuffer liegt pro Profil |
| Jackengrenzen können unbeschränkt wegdriften | **Im aktuellen Stand bereits behoben** | Deltas bleiben hart begrenzt; zusätzlicher Stresstest ergänzt |
| Event-/Abendzeit nutzt UTC statt Ortszeit | **Im aktuellen Stand bereits behoben** | `dt_util.as_local()` bleibt explizit erhalten |
| Event-Kontext wird immer als `True` gesetzt | **Im aktuellen Stand bereits behoben** | Kalender- und Aktivitätskontext sind getrennt und nur bei echtem Kontext aktiv |
| Transition-Lernen mischt effektive Temperatur zurück | **Beschreibung passt nicht mehr zum aktuellen Algorithmus** | Transition-Lernen nutzt den separaten Transition-Penalty als Kontextsignal |
| Windlernen ignoriert Böen | **Berechtigt** | Feedback-Kontext verwendet nun den stärkeren Wert aus Wind und Böen |
| Feedback für „später“ lernt aus dem aktuellen Wetter/Jacke | **Berechtigt und wichtig** | Session speichert getrennte Start-/Später-Lernkontexte; Phase „Später“ trainiert den damaligen Forecastpunkt und `jacket_later` |
| Niederschlag ohne Einheitenumrechnung | **Im aktuellen Stand bereits behoben** | `DistanceConverter` rechnet auf mm; Test für Inch→mm ergänzt |
| Wind kennt Beaufort/ft/s nicht | **Berechtigt** | ft/s und Beaufort ergänzt; unbekannte Einheiten werden nicht mehr als km/h interpretiert |
| `snowy-rainy` fehlt | **Im aktuellen Stand bereits behoben** | Condition ist enthalten |
| ungültige Temperatureinheit wird als Rohzahl benutzt | **Im aktuellen Stand bereits behoben** | ungültige Einheit verwirft den Wert / nutzt Indoor-Fallback |
| Weather-Entity ohne Hourly-Forecast auswählbar | **Bewusster Fallback, kein Defekt** | Aktuelle Empfehlung funktioniert weiterhin; spätere Empfehlung ist eingeschränkt. Hourly bleibt empfohlen, nicht Pflicht |
| `display_mode=compact` wird nicht benutzt | **Im aktuellen Stand bereits behoben** | Frontend rendert Compact-Modus |
| „Später“-Ternary immer identisch | **Im aktuellen Stand bereits behoben** | `_laterText()` unterscheidet wärmer/kühler und blendet unveränderte Lage aus |
| Icon nutzt Overall statt Jetzt | **Im aktuellen Stand bereits behoben** | Icon und Haupttext verwenden `jacket_now` |
| `getCardSize()` ignoriert offene Feedbacks | **Im aktuellen Stand bereits behoben** | Pending/Latest werden berücksichtigt |
| Danke-Hinweis bleibt ewig | **Teilweise berechtigt** | Hinweis wird beim nächsten bewussten Öffnen/Profilwechsel zurückgesetzt |
| `manual`/`voluntary` ist toter Backendpfad | **Im aktuellen Stand bereits behoben** | Manuelles Feedback sendet `voluntary=true` |
| „Ungewöhnlicher Tag“ zählt Samples voll | **Berechtigt** | Weighted RunningStat: Roh-Sample bleibt sichtbar, effektives Lern-/Confidence-Gewicht beträgt nur 30 % |
| `work_zone` hat keinen Berechnungseffekt | **Im Kern zutreffend, aber absichtlich** | Zone dient in v0.1.0 nur Zuordnung/Anzeige; Wetter muss weiterhin aus einer Weather-Entity kommen. Konfiguration beschreibt das ausdrücklich |
| Work-Weather ohne Arbeitszeitquelle hat keinen Effekt | **Berechtigt** | Config-Flow lehnt jetzt stille No-op-Konfiguration ab: Work-Weather benötigt Arbeitskalender oder Schichtzyklus |
| englische Übersetzung überwiegend Deutsch | **Im aktuellen Stand nicht zutreffend** | EN ist bereits übersetzt; Beschreibungen wurden zusätzlich vervollständigt |
| sehr viele `except Exception` | **Im aktuellen Stand nicht zutreffend** | Es werden überwiegend konkrete Fehlerklassen gefangen und Debug-Meldungen geschrieben |
| viele Semikolons / `from .const import *` | **Im aktuellen Stand nicht zutreffend** | Python-Code ist bereits strukturiert und verwendet explizite Imports |
| kaputte `SHA256SUMS.txt` | **Im aktuellen Paket nicht vorhanden** | Kein Handlungsbedarf |
| CI prüft nur Compile + wenige Engine-Tests | **Prüfliste passt nicht zum aktuellen Workflow, aber Tests fehlten dort tatsächlich** | CI hat jetzt Unit-Test-Job + Compile sowie weiterhin HACS- und hassfest-Prüfung |

## Zusätzlich beim Review gefunden

- **Urlaubskalender:** Ein Urlaubstermin irgendwo innerhalb des 16-h-Horizonts unterdrückte bisher pauschal alle Arbeitsfenster. Jetzt werden nur Arbeitsfenster unterdrückt, die zeitlich wirklich mit Urlaub/Abwesenheit überlappen.
- **Shared-Setup:** Ein noch nicht eingerichtetes persönliches Profil kann auf einem Shared-Tablet nun korrekt eingerichtet werden; nach Abschluss wird die Profilauswahl wieder zurückgesetzt.
- **Aktiver Arbeitskontext ohne Hourly-Forecast:** Wenn am Arbeitsort nur aktuelle Wetterdaten verfügbar sind, wird der aktuelle Work-Kontext trotzdem korrekt als solcher markiert.

## Lokale Prüfungen nach den Änderungen

- Python Unit-Tests: **22/22 bestanden**
- Python-Syntax/Compile: bestanden
- JavaScript-Syntax (`node --check`): bestanden
- JSON-Dateien: validiert

HACS/hassfest sind im GitHub-Workflow enthalten; sie können vollständig erst in der entsprechenden CI/Home-Assistant-Umgebung ausgeführt werden.
