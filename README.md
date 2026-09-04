# 🧥 JackenBerater v0.1.3

Eine schlanke Home-Assistant-Integration, die nicht nur auf die Außentemperatur schaut, sondern eine **persönliche Jackenempfehlung** aus Wetter, Wetterverlauf, Innen→Außen-Wechsel und freiwilligem Nutzerfeedback ableitet.

> **Status:** erste Testversion. Der Name „JackenBerater“ ist noch nicht als endgültiger Projektname gedacht.

## Was v0.1.3 kann

- Empfehlung in vier Wärmestufen:
  - Keine Jacke
  - Leichte Jacke
  - Warme Jacke
  - Winterjacke
- getrennte Regenschutz-Empfehlung
- aktuelle Entscheidung **„wenn ich jetzt rausgehe“**
- normalerweise **9 echte Zeitstunden Vorschau**, bei relevanter Änderung bis ca. **12 Stunden** (nicht bloß 9/12 Forecast-Punkte)
- optionaler Kalender-Zeitkontext bis max. ca. 16 Stunden
- Innen→Außen-Effekt über einen optionalen Wohnraum-Temperatursensor
- Fallback für die Innentemperatur: standardmäßig 21,5 °C
- Wind, Böen, Feuchte, Bewölkung/Sonne und Niederschlag werden genutzt, wenn die Wetterquelle sie liefert
- persönliche Profile über die authentifizierte Home-Assistant-User-ID
- schneller Lernstart, danach zunehmend vorsichtige Anpassungen
- freiwilliges Feedback jederzeit möglich
- alte Feedbacks zeigen klar Datum/Uhrzeit und die damalige Empfehlung
- kompakter Speicher: keine unbegrenzt wachsende Trainingshistorie
- optionale Arbeits-Wetterquelle mit **normaler 5-Tage-Woche als Standard**
- optionaler Urlaubs-/Abwesenheitskalender zum Aussetzen wahrscheinlicher Arbeitszeiten
- optionaler rotierender Schichtzyklus für Schichtarbeiter, unabhängig vom Wochentag
- eigene Lovelace-Karte mit visueller Einrichtung und Feedback
- **persönliche Trend-/Kurzzeitlogik:** sehr kurze Übergänge dürfen geglättet werden, wenn die weitere thermische Entwicklung klar in die andere Richtung läuft und die persönliche Belastung klein genug ist
- transparente Langzeit-Hinweise wie **„Leichte Jacke reicht aktuell. Wenn du länger unterwegs bist, wird ab etwa 18:00 eine warme Jacke sinnvoll.“**
- kleine saisonale Feinanpassung des persönlichen Profils, ohne wachsende Historie
- ⓘ-Infofeld mit betrachtetem Zeitraum, Aufenthaltsannahme, thermischem Trend, Forecast-Abdeckung und persönlicher Confidence
- ein kompakter Diagnose-Sensor je Profil zeigt die tatsächlich gelernten Werte ohne wachsende Historie
- auf Shared-/Wandtablets bleibt das ausgewählte Personenprofil lokal auf diesem Browser gespeichert, bis es bewusst gewechselt wird
- Geschützte Verwaltung direkt in der Karte: Lernen pausieren, Lernprofil zurücksetzen, letzte Bewertung zurücknehmen

## Ressourcenverbrauch

JackenBerater hat **keine zusätzlichen Python-Abhängigkeiten** und keine eigene große Datenbank.

- Wetter-Forecast wird standardmäßig nur alle 15 Minuten aktualisiert.
- Aktuelle Wetterwerte werden aus den vorhandenen HA-Entities gelesen.
- Kalenderkontext wird höchstens alle 15 Minuten neu abgefragt und nur, wenn ein entsprechender Kalender eingerichtet wurde.
- Pro Nutzer werden nur wenige Lernparameter, Zähler und maximal 20 kompakte Sessions gespeichert.
- Höchstens 3 **angeforderte** unbeantwortete Feedback-Sessions bleiben gleichzeitig erhalten; freiwillige/manuelle Sessions verdrängen diese nicht.
- Unbeantwortete Sessions laufen nach etwa 36 Stunden ab.

Damit wächst das Lernprofil auch nach mehreren Jahren nicht proportional zur Zahl der Bewertungen.

## Installation

### HACS Custom Repository

Die Integration bringt ihr lokales Brand-Icon direkt unter `custom_components/jackenberater/brand/icon.png` mit.

1. Repository in HACS als **Integration** hinzufügen.
2. JackenBerater installieren.
3. Home Assistant neu starten.
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → JackenBerater**.

### Manuell

Den Ordner

`custom_components/jackenberater`

nach

`/config/custom_components/jackenberater`

kopieren und Home Assistant neu starten.

## Einrichtung

### Grundlage

**Wetterquelle** ist die einzige Pflichtangabe.

Optional:

- Wohnraumtemperatur, z. B. Wohnzimmer
- Fallback-Innentemperatur
- Regenschutz berücksichtigen

Es ist absichtlich kein bestimmter Wetteranbieter vorgeschrieben. JackenBerater verwendet die verfügbaren Felder und fällt bei fehlenden Zusatzdaten sauber zurück. Für die volle „später mitnehmen“-Funktion ist ein stündlicher Forecast am hilfreichsten.

### Zeitkontext – optional

Ein ausgewählter Kalender wird **nicht inhaltlich analysiert**. JackenBerater liest nur Start und Ende zeitlich begrenzter Termine.

Ein Kalendereintrag bedeutet ausdrücklich **nicht**, dass der Nutzer draußen ist. Er kann lediglich den Zeitraum erweitern, den der Berater vorsichtshalber betrachtet.

Ein erfolgreich gelesener Kalender ohne passende Termine wird normal als leer behandelt. Ist der konfigurierte Kalender dagegen vorübergehend nicht lesbar, bleibt dieser Zustand als **nicht verfügbar** erhalten und die Karte weist sichtbar darauf hin, dass längere Termine in der Planung fehlen können.

### Arbeitskontext – optional

Falls Arbeit klimatisch deutlich anders ist als zuhause:

- vorhandene HA-Zone „Arbeit“ auswählen
- eine Wetter-Entity für den Arbeitsort auswählen
- Arbeitsmodell wählen
- optional Urlaubs-/Abwesenheitskalender

Für normale Nutzer gilt standardmäßig **Montag bis Freitag, 08:00–17:00 Uhr**. Start und Ende können geändert werden. Für die Planung wird automatisch ein kleiner Puffer von etwa ±30 Minuten verwendet – eine Fahrzeit muss deshalb nicht abgefragt werden. Dieser Puffer macht den Arbeitsort aber **nicht** zum aktuellen Standort: Für „jetzt“ wechselt die Wetterquelle erst innerhalb der tatsächlichen Arbeitszeit.

Das Arbeitsmodell wird nur angewendet, wenn auch eine **Wetterquelle am Arbeitsort** gewählt ist. Ohne diese bleibt der Arbeitskontext bewusst inaktiv; die übrige Jackenberatung funktioniert normal weiter.

Verfügbare Arbeitsmodelle:

- **Arbeit nicht berücksichtigen**
- **Normale 5-Tage-Woche**
- **Rotierendes Schichtsystem**

Ein optionaler Urlaubs-/Abwesenheitskalender erzeugt niemals selbst Arbeit. Er kann nur Zeiträume aussetzen, in denen der Berater sonst Arbeit vermuten würde. Wird eine komplette Schicht als abwesend markiert, verschwinden auch die zugehörigen Planungs-Puffer; bei teilweiser Abwesenheit bleibt genau dieser Zeitraum ausgespart. Kalenderinhalte wie Titel oder Beschreibung werden weiterhin nicht analysiert.

Ist ein eingerichteter Abwesenheitskalender nicht erreichbar, wird das nicht mit „keine Abwesenheit“ gleichgesetzt. JackenBerater verwendet die Arbeitsortplanung dann vorsichtshalber nicht und zeigt die Datenlücke direkt auf der Karte an. Sobald der Kalender wieder erfolgreich gelesen wurde, arbeitet die normale Planung weiter.

Während der tatsächlichen Arbeitszeit verwendet JackenBerater die aktuelle Wetterquelle des Arbeitsorts. Ist diese vorübergehend nicht verfügbar, wird bewusst **nicht** still auf das Zuhause-Wetter zurückgefallen – die Karte meldet die fehlenden Arbeitswetterdaten stattdessen transparent.

### Rotierender Schichtzyklus – optional

Für Systeme, die nicht an Montag–Sonntag gebunden sind, z. B.:

`F,F,S,S,N,N,N,X,X`

- `F` = Frühschicht
- `S` = Spätschicht
- `N` = Nachtschicht
- `X` = frei

Dazu wird einmal ein **Ankerdatum** angegeben, an dem der erste Eintrag des Zyklus gilt. Danach läuft die Folge unabhängig vom Wochentag weiter.

## Persönliches Profil

Beim ersten bewussten Öffnen der Karte fragt der Berater vier fünfstufige Startwerte:

1. Wie schnell frierst du?
2. Wie schnell wird dir zu warm?
3. Wie empfindlich bist du bei Wind?
4. Wenn du abends länger draußen bist: eher ruhig/stehend oder aktiv in Bewegung?

Diese Antworten sind nur Startwerte. Echtes Feedback darf das Profil sofort verändern.

### Lernen

Am Anfang lernt das Modell absichtlich kräftiger. Mit zunehmender Erfahrung wird jede einzelne Bewertung vorsichtiger gewichtet.

Dabei werden getrennte Erfahrungszähler geführt, z. B. für:

- allgemeines Wärmeempfinden
- Wind
- Innen→Außen-Übergang
- Grenze keine ↔ leichte Jacke
- Grenze leichte ↔ warme Jacke
- Grenze warme ↔ Winterjacke

Dadurch kann eine selten erlebte Wintergrenze noch deutlich lernen, obwohl das allgemeine Profil bereits viele Bewertungen kennt.

Die Lernrate fällt nie auf null, sodass sich ein Profil auch nach Jahren langsam an echte Veränderungen anpassen kann.

### Kurzzeit-/Trendlernen

JackenBerater behandelt einen sehr kurzen Temperatur- oder Komfortübergang nicht automatisch wie eine eigene vollständige Jackensituation. Als Anti-Flattern gilt ein Mindestbereich von ungefähr **15 Minuten**; darüber entscheidet aber keine starre Zeitgrenze. Stattdessen bewertet die Engine die kumulierte Abweichung zur **persönlich gelernten Jackengrenze**, die Dauer und den weiteren thermischen Trend.

Beispiel: Ist jetzt kurz eine warme Jacke optimal, wenige Minuten später reicht dauerhaft eine leichte Jacke und der restliche Zeitraum wird weiter milder, kann die praktische Empfehlung direkt auf „leichte Jacke“ geglättet werden. Ist die kurze Kältephase dagegen deutlich stärker oder hält zu lange an, bleibt die wärmere Jacke die Empfehlung. Diese Kurzzeit-Toleranz lernt separat aus passendem Feedback und verschiebt nicht einfach das normale Langzeit-Wärmeprofil.

Zusätzlich besitzt jedes Profil vier kleine saisonale Korrekturwerte. Sie lernen bewusst sehr langsam und ergänzen das langfristige Profil, ohne alte Bewertungen als Historie dauerhaft zu speichern.

## Feedback

Eine sichtbare Dashboard-Karte gilt **nicht** als Nutzung. Erst ein bewusster Tap auf den normalen Aufklapp-Pfeil erzeugt eine Empfehlungssession. Das Öffnen des eingekreisten **ⓘ** erzeugt keine Session.

Eine neue Empfehlung wird **nicht sofort** zur Bewertung angeboten. Normalerweise wird Feedback frühestens nach etwa 30 Minuten freigegeben. Wenn die Empfehlung ausdrücklich auf einen späteren Jackenwechsel zielt, wartet der Berater bis etwa 30 Minuten nach diesem späteren Zeitpunkt. Freiwilliges Feedback kann über einen kleinen manuellen Weg trotzdem jederzeit bewusst abgegeben werden.

Feedback:

- 🥶 Zu kalt
- ✅ Perfekt
- 🥵 Zu warm
- Nicht genutzt

Alte Bewertungen werden immer mit ihrem damaligen Zeitpunkt und einer kleinen Wetter-Erinnerung angezeigt. Eine offene Bewertung blockiert niemals eine neue Empfehlung.

Der Nutzer kann außerdem freiwillig eine Empfehlung bewerten, selbst wenn der Lernalgorithmus gerade kein Feedback benötigt. Bei jeder Bewertung kann optional **„Heute war ungewöhnlich – schwächer gewichten“** markiert werden; diese Rückmeldung zählt dann nur reduziert in das Lernprofil hinein.

## Gemeinsames Wandtablet

In der Integration können bestimmte Home-Assistant-Konten als **gemeinsame Tablet-/Wandtablet-Konten** freigegeben werden. Die Karte erkennt diese Konten automatisch.

Ein solches Tablet bekommt **kein eigenes Wärmeprofil**. Stattdessen fragt die Karte vor der Beratung direkt, für welches vorhandene Komfortprofil sie rechnen soll. Die Auswahl wird lokal im Browser des jeweiligen Wandtablets gespeichert und bleibt auch nach Dashboardwechsel, Browser-Refresh, Home-Assistant-Neustart oder Tablet-Neustart erhalten, bis sie über die Profilauswahl bewusst gewechselt wird. Sie wird **nicht serverweit** für das HA-Konto gesetzt.

Auf persönlichen Geräten verwendet JackenBerater weiterhin automatisch die eigene Home-Assistant-User-ID. Auf dem Wandtablet erzeugt der normale Aufklapp-Pfeil eine Session **nur für das ausgewählte Profil**. Ohne Profilauswahl, bei der bloßen Vorschau und über das eingekreiste **ⓘ** wird keine Session angelegt. Ein später fälliges Feedback darf auf demselben Shared-Konto beantwortet werden und wird deutlich als **„Feedback für &lt;Profilname&gt;“** beschriftet. Ein Profilwechsel verwirft den lokalen Kartenkontext; Sessions und Feedback verschiedener Profile oder Shared-Konten werden nicht vermischt.

Shared-Konten dürfen weder manuelles Sofort-Feedback noch Setup, Lernpause, Wartung, Reset, Undo, Import oder Export ausführen. Das Backend akzeptiert vom Tablet ausschließlich fälliges Feedback zu einer Session, die genau dieses Shared-Konto zuvor für genau dieses Profil geöffnet hat. Es wird keine Anwesenheit oder Geräteposition geraten.

## Karte hinzufügen

Nach normaler Einrichtung versucht die Integration die Frontend-Ressource automatisch in Lovelace zu registrieren.

Danach im Dashboard eine Karte hinzufügen und **JackenBerater** auswählen.

Falls Lovelace komplett über YAML verwaltet wird, die Modul-Ressource manuell eintragen:

`/jackenberater/frontend/jackenberater-card.js?v=0.1.3`

Karten-YAML:

```yaml
type: custom:jackenberater-card
```

Optional:

```yaml
type: custom:jackenberater-card
title: Jacke heute
shared: true
```

## ⓘ Info & Lerndiagnose

Ein kleines eingekreistes **ⓘ** öffnet eine verständliche Erklärung der aktuellen Empfehlung. Dort stehen nur die für die Entscheidung relevanten Annahmen, z. B.:

- betrachteter Zeitraum
- Aufenthaltsdauer bzw. ob sie unbekannt ist
- thermischer Trend (wärmer / kälter / stabil / wechselhaft)
- ob Arbeits- oder Kalenderkontext verwendet wurde
- Forecast-Abdeckung
- persönliche Entscheidungs-Confidence
- Hinweis auf saisonale oder Kurzzeit-Feinanpassung, falls aktiv

Unter **„Was hat dieses Profil gelernt?“** zeigt die persönliche Karte die festen Lernparameter und Statistikwerte des eigenen Profils. Shared-/Wandtablet-Konten erhalten diese Detailwerte weder in der Vorschau noch nach dem Öffnen einer Session oder dem Abgeben von Feedback.

Zusätzlich wird pro Profil ein Diagnose-Sensor vorbereitet, zum Beispiel `sensor.jackenberater_sven_lernprofil`. Er ist aus Datenschutzgründen **standardmäßig deaktiviert** und gelangt damit nicht automatisch als lesbare Entität in den HA-Zustandsautomaten. Ein Administrator kann ihn für gezieltes Troubleshooting manuell aktivieren. Sein Zustand ist die Anzahl verarbeiteter Bewertungen; die kompakten Modellwerte liegen als Attribute vor und sind von der Recorder-Historie ausgeschlossen. Wichtig: Home-Assistant-Rechte gelten auf Entitätsebene. Wer den Sensor aktiviert, muss dessen Sichtbarkeit deshalb mit den eigenen HA-Berechtigungen passend begrenzen.

### Sicherer Testmodus über Entwicklerwerkzeuge

Nach dem bewussten Aktivieren des Diagnose-Sensors kann dessen Zustand oder ein Attribut unter **Entwicklerwerkzeuge → Zustände** vorübergehend verändert werden. Die Empfehlung reagiert mit einer Simulation; die Karte kennzeichnet das sichtbar mit **„Testmodus aktiv – keine Speicherung, keine Session, kein Lernen.“**

Die simulierten Werte werden begrenzt und ausschließlich auf einer flüchtigen Kopie des Lernmodells ausgewertet. Währenddessen werden keine Session, kein Nutzungszähler, kein Feedback und keine Lern- oder Undo-Änderung erzeugt. Das gespeicherte Profil bleibt unverändert. Ein echter Profilvorgang oder Neustart beendet den Testmodus und stellt die gespeicherten Werte wieder her.

Der vorhandene Code für JSON-Export und -Import bleibt zunächst erhalten, ist in v0.1.3 aber vollständig deaktiviert: Die Karte zeigt keine Schaltflächen und die zugehörigen WebSocket-Befehle werden nicht registriert.

## Kartenverhalten

- **eindeutig warm + stabil:** Karte kann nach eingerichtetem Profil vollständig verschwinden
- **eindeutig kalt + stabil:** kompakter Status
- **Grenzbereich / Wechsel / Regen / Arbeitsort / Unsicherheit:** volle Karte

Damit soll die Karte nicht im Hochsommer monatelang Platz verschwenden.

## Berechnungsmodell

v0.1.3 verwendet bewusst **kein großes ML-Modell** und auch nicht den vollständigen UTCI-Polynomblock. Stattdessen nutzt die Engine eine transparente, kleine thermische Bewertung mit den gleichen wichtigen Kategorien: Temperatur, Wind, Feuchte, Strahlung/Sonne, Nässe, Aktivitätskontext und Bekleidung.

Im kalten Bereich wird die offizielle Wind-Chill-Gleichung nur innerhalb ihres sinnvollen Temperatur-/Windbereichs verwendet. Oberhalb davon wird Wind deutlich schwächer als Komfortkorrektur gewertet.

Die Startgrenzen sind absichtlich nur Ausgangswerte. Das persönliche Lernprofil verschiebt sie mit echtem Feedback.

## Datenschutz / Datenminimierung

- keine GPS-Pflicht
- keine Anwesenheitspflicht
- kein Bewegungsprofil
- keine Kalenderinhaltsanalyse
- keine Speicherung einer jahrelangen Wetter-/Feedbackhistorie
- Nutzertrennung über die bestehende HA-Authentifizierung

Bei Kalendern werden in der normalen Logik nur Start-/Endzeiten genutzt. Titel, Beschreibung und Ort werden vom Code absichtlich ignoriert.

## Hinweis

JackenBerater ist ein Komfortberater und keine Sicherheits- oder Gesundheitsanwendung. Bei extremen Wetterlagen, amtlichen Warnungen oder gesundheitlichen Besonderheiten haben geeignete Schutzmaßnahmen und offizielle Warnhinweise Vorrang.

## Teststatus v0.1.3

Die lokale Regressionstest-Suite umfasst aktuell **142 Python-Tests** sowie einen funktionalen JavaScript-Test für den Feedback-/Frontend-Pfad. Dazu gehören insbesondere Rollen- und Sessiontrennung für normal/shared/admin, UTC-/DST-Grenzfälle, die Unterscheidung zwischen leeren und nicht verfügbaren Kalendern sowie Unveränderlichkeitsprüfungen für gespeichertes Modell und Sessions während einer Simulation. Ein zusätzlicher CI-Job unter Python 3.14 und Home Assistant 2026.9 durchläuft den echten Integrationslebenszyklus mit WebSocket-Preview, Session, Feedback, Shared-Preview, Reload und Unload. Außerdem prüft CI Python-Kompilierung, Ruff-F/E9, JavaScript-Syntax, hassfest und HACS.
