# JackenBerater v0.3.2

JackenBerater ist eine Home-Assistant-Integration für persönliche Jackenempfehlungen. Sie verwendet aktuelle Wetterdaten, den Forecast und optional persönliche Rückmeldungen.

## Voraussetzungen

- Home Assistant ab 2026.6
- eine `weather`-Entity
- für die Vorschau möglichst ein stündlicher Forecast

## Installation

### HACS

JackenBerater wird derzeit als **Custom Repository** hinzugefügt:

1. In HACS oben rechts das **Drei-Punkte-Menü** öffnen und **Custom repositories** wählen.
2. `https://github.com/svemmiii/Jackenberater` eintragen.
3. Als Typ **Integration** auswählen und mit **Add** hinzufügen.
4. JackenBerater in HACS installieren.
5. Home Assistant neu starten.
6. Unter **Einstellungen → Geräte & Dienste** JackenBerater hinzufügen.

### Manuell

`custom_components/jackenberater` nach `/config/custom_components/jackenberater` kopieren und Home Assistant neu starten.

## Einrichtung

Pflicht:

- Wetterquelle für Zuhause

Optional:

- Innenraum-Temperatursensor
- Fallback-Innentemperatur
- Kalender für längere Zeitkontexte
- Wetterquelle für den Arbeitsort
- normale Arbeitswoche oder Schichtmodell
- Abwesenheitskalender für den Arbeitskontext
- Shared-/Wandtablet-Konten

Der normale Forecast-Horizont beträgt 9 Stunden. Bei relevanten Änderungen kann er erweitert werden; Arbeits- und Kalenderkontext können einen längeren Zeitraum erforderlich machen.

## Persönliches Profil und Feedback

Jeder normale Home-Assistant-Benutzer hat sein eigenes Lernprofil. Beim ersten Einrichten werden einige Startfragen gestellt. Später kann das Profil durch Feedback angepasst werden:

- Zu kalt
- Perfekt
- Zu warm
- Nicht genutzt

Das allgemeine Profil ist der ganzjährige persönliche Grundwert. Winter, Frühling, Sommer und Herbst besitzen daneben jeweils einen eigenen Offset. Normales thermisches Feedback verändert nach der Initialisierung nur die gerade beteiligte Jahreszeit; während der rund 30-tägigen Überblendung um den meteorologischen Saisonwechsel lernen ausschließlich die beiden benachbarten Saisonanker. Die saisonale Lernrate richtet sich nach der eigenen echten Evidenz der jeweiligen Jahreszeit und bleibt auch nach vielen Jahren reaktionsfähig.

Beim allerersten Übergang in eine noch unbekannte Jahreszeit übernimmt sie einmalig nur den Offset der direkten Vorgängersaison als Startwert. Wird die komplette 30-Tage-Übergangszone verpasst, wird dieses einmalige Seeding beim ersten späteren Zugriff in der neuen Saison nachgeholt. Evidenz, Statistik und Lernhistorie werden nie mitkopiert; in späteren Jahren verwendet die Saison ausschließlich ihren eigenen zuletzt gelernten Zustand. Wurden mehrere ganze Jahreszeiten übersprungen und ist die direkte Vorgängersaison selbst unbekannt, wird keine künstliche Seed-Kette erzeugt: Nur die aktuell erreichte Saison startet dann neutral bei 0 relativ zu Main. Erst wenn alle vier Jahreszeiten ausreichend eigene Evidenz besitzen und ihre Offsets denselben gemeinsamen positiven oder negativen Sockel zeigen, wird dieser gemeinsame Anteil verlustfrei in den ganzjährigen Grundwert verschoben. `Main + Saisonoffset` bleibt dadurch für jede Jahreszeit unverändert. Bestehende v0.3.0-Profile werden beim Laden automatisch in dieses Modell migriert; synthetische Saisonwerte ohne eigene Evidenz werden dabei nicht als echte Saisonerfahrung übernommen.

Wenn sich die Empfehlung im Tagesverlauf ändert, zeigt die Feedbackkarte auch diesen Wechsel. Bei "Zu kalt" oder "Zu warm" fragt sie konkret nach, ob die erste Empfehlung, der spätere Wechsel oder ein längerer Zeitraum nicht gepasst hat. Ein falsch getimter Wechsel korrigiert gezielt die betroffene Jackengrenze statt pauschal das ganze Wärmeprofil.

Eine sichtbare Karte allein erzeugt keine Feedback-Session. Erst das bewusste Öffnen der Empfehlungsdetails zählt als Nutzung. Automatisches Feedback wird normalerweise frühestens nach 30 Minuten freigegeben.

Der interne thermische Rechenwert bleibt Teil der Berechnung, wird aber nicht als Temperaturwert auf der normalen Nutzerkarte angezeigt.

## Wandtablet / Shared-Konto

Ein als Shared-Konto freigegebener Home-Assistant-Benutzer wählt vor der Beratung ein vorhandenes Personenprofil aus. Konten, die aktuell selbst als Shared-/Steuerkonto konfiguriert sind, werden dabei nicht als beratbare Person angeboten; ihr eventuell früher gelerntes persönliches Profil bleibt nur konserviert und erscheint automatisch wieder, wenn der Shared-Status später entfernt wird.

- Die Auswahl wird lokal im Browser gespeichert.
- Details werden nur für das ausgewählte Profil geöffnet.
- Fälliges Feedback gehört zum Profil und kann auch auf einem anderen Gerät beantwortet werden.
- Nahezu identische Öffnungen desselben Profils innerhalb kurzer Zeit werden nicht doppelt als Lerngelegenheit gezählt.
- Nicht-administrative Shared-Konten dürfen keine Profilverwaltung, kein Reset und kein freiwilliges Sofort-Feedback ausführen. Home-Assistant-Administratoren behalten die vorgesehenen administrativen Rechte.

Wird ein gespeichertes Profil gelöscht oder ändert sich der Shared-Status des Kontos, korrigiert die Karte die Auswahl automatisch.

## Lovelace-Karte

Nach der Einrichtung versucht JackenBerater die Frontend-Ressource automatisch zu registrieren.

Karten-YAML:

```yaml
type: custom:jackenberater-card
```

Optional:

```yaml
type: custom:jackenberater-card
title: Jacke heute
```

Bei vollständig YAML-verwaltetem Lovelace muss die Ressource manuell eingetragen werden:

`/jackenberater/frontend/jackenberater-card.js?v=0.3.2&ui=13`

Nach einem JackenBerater-Update sollte die Lovelace-Seite einmal vollständig neu geladen werden. Bereits registrierte Browser-Custom-Elements können innerhalb derselben JavaScript-Session technisch nicht durch eine neu geladene Klasse ersetzt werden; der versionsgebundene Ressourcenpfad verhindert dabei normale Cache-Probleme.

Die beiden aufklappbaren Bereiche der Karte sind gegenseitig exklusiv: Entweder sind die Empfehlungsdetails oder das Infofeld geöffnet, nicht beide gleichzeitig.

## Arbeitskontext

Wenn eine Arbeitswetterquelle eingerichtet ist, kann JackenBerater für geplante Arbeitszeiten das Wetter am Arbeitsort berücksichtigen. Das aktuelle Arbeitswetter wird während der tatsächlichen Arbeitszeit verwendet. Außerhalb davon bleibt Zuhause die aktuelle Wetterquelle. Für die Planung gilt weiterhin der ±30-Minuten-Puffer; nach dem echten Schichtende wird dieser ausdrücklich als Puffer und nicht als laufende Arbeitszeit bezeichnet. Bei stündlichen Forecasts darf ein ausreichend frischer Forecastanker ein kurzes Restfenster bis zum Pufferende abdecken, damit zum Feierabend nicht fälschlich „Arbeitsforecast fehlt“ erscheint.

State-Änderungen des Kontext-/Terminkalenders oder Abwesenheitskalenders invalidieren den Arbeitskontext-Cache unmittelbar. Home Assistant garantiert allerdings nicht bei jeder Kalender-CRUD-Änderung sofort einen Entity-State-Change. Deshalb ist der JackenBerater-eigene Cache zusätzlich auf nur **1 Minute** begrenzt; providerseitige Aktualisierungsintervalle von Home Assistant bzw. der jeweiligen Kalenderintegration können unabhängig davon weiterhin gelten.

Die Arbeitszone dient nur als Name für die Anzeige. Sie wird nicht für Standorttracking oder Anwesenheit verwendet.

## Daten

JackenBerater speichert nur kompakte Profil- und Sessiondaten in Home Assistant. Es wird keine langfristige Wetterhistorie und kein Bewegungsprofil angelegt.

Der Diagnose-Sensor ist standardmäßig deaktiviert und vom Recorder ausgeschlossen. Wird er von einem Administrator bewusst aktiviert, enthalten seine Attribute das vollständige persönliche Lernmodell des jeweiligen Profils. Home-Assistant-Berechtigungen gelten für die Entity als Ganzes und nicht für einzelne Attribute; Zugriff auf diesen Diagnose-Sensor sollte deshalb nur vertrauenswürdigen Benutzern gewährt werden.

## Hinweis

JackenBerater ist ein Komfortberater. Amtliche Wetterwarnungen und notwendige Schutzmaßnahmen haben Vorrang.
