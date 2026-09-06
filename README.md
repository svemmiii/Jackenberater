# JackenBerater v0.2.0

JackenBerater ist eine Home-Assistant-Integration für persönliche Jackenempfehlungen. Sie verwendet aktuelle Wetterdaten, den Forecast und optional persönliche Rückmeldungen.

## Voraussetzungen

- Home Assistant ab 2026.6
- eine `weather`-Entity
- für die Vorschau möglichst ein stündlicher Forecast

## Installation

### HACS

1. Repository in HACS als Integration hinzufügen.
2. JackenBerater installieren.
3. Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste** JackenBerater hinzufügen.

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

Eine sichtbare Karte allein erzeugt keine Feedback-Session. Erst das bewusste Öffnen der Empfehlungsdetails zählt als Nutzung. Automatisches Feedback wird normalerweise frühestens nach 30 Minuten freigegeben.

Der interne thermische Rechenwert bleibt Teil der Berechnung, wird aber nicht als Temperaturwert auf der normalen Nutzerkarte angezeigt.

## Wandtablet / Shared-Konto

Ein als Shared-Konto freigegebener Home-Assistant-Benutzer wählt vor der Beratung ein vorhandenes Personenprofil aus.

- Die Auswahl wird lokal im Browser gespeichert.
- Details werden nur für das ausgewählte Profil geöffnet.
- Fälliges Feedback gehört zum Profil und kann auch auf einem anderen Gerät beantwortet werden.
- Nahezu identische Öffnungen desselben Profils innerhalb kurzer Zeit werden nicht doppelt als Lerngelegenheit gezählt.
- Shared-Konten dürfen keine Profilverwaltung, kein Reset und kein freiwilliges Sofort-Feedback ausführen.

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

`/jackenberater/frontend/jackenberater-card.js?v=0.2.0&ui=1`

Die beiden aufklappbaren Bereiche der Karte sind gegenseitig exklusiv: Entweder sind die Empfehlungsdetails oder das Infofeld geöffnet, nicht beide gleichzeitig.

## Arbeitskontext

Wenn eine Arbeitswetterquelle eingerichtet ist, kann JackenBerater für geplante Arbeitszeiten das Wetter am Arbeitsort berücksichtigen. Das aktuelle Arbeitswetter wird während der tatsächlichen Arbeitszeit verwendet. Außerhalb davon bleibt Zuhause die aktuelle Wetterquelle.

Die Arbeitszone dient nur als Name für die Anzeige. Sie wird nicht für Standorttracking oder Anwesenheit verwendet.

## Daten

JackenBerater speichert nur kompakte Profil- und Sessiondaten in Home Assistant. Es wird keine langfristige Wetterhistorie und kein Bewegungsprofil angelegt.

## Hinweis

JackenBerater ist ein Komfortberater. Amtliche Wetterwarnungen und notwendige Schutzmaßnahmen haben Vorrang.
