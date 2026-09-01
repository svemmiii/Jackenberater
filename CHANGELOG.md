# Changelog

Alle nennenswerten Änderungen an JackenBerater werden in dieser Datei gesammelt.

## v0.1.0

Erste öffentliche Testversion.

### Neu

- persönliche Jackenempfehlung: keine / leichte / warme / Winterjacke
- getrennte Regenjacken-/Regenschutzlogik
- 9-h-Standardforecast mit bedingter Verlängerung bis 12 h
- optionaler Zeitkontext über Kalender bis ca. 16 h
- Innen→Außen-Übergang mit Sensor oder 21,5-°C-Fallback
- Berücksichtigung von Wind, Böen, Feuchte, Sonne/Bewölkung und Nässe, sofern vorhanden
- schwacher saisonaler Aktivitätskontext für typische Eventzeiten, abhängig von der persönlichen Abendroutine
- Profile pro Home-Assistant-User-ID
- vier fünfstufige Startfragen direkt in der Karte
- starkes Early Learning mit später schrittweise vorsichtigerer Anpassung
- separate Lernzähler für allgemeines Empfinden, Wind, Übergang und Jackengrenzen
- freiwilliges Feedback jederzeit möglich
- zeitlich eindeutig zugeordnete Feedback-Sessions
- Lernen pausieren, Profil zurücksetzen und letzte Bewertung rückgängig machen
- optionale Arbeitszone mit separater Wetterquelle
- optionaler Arbeits-/Schichtkalender und Urlaubs-/Abwesenheitskalender
- rotierende Schichtzyklen wie `F,F,S,S,N,N,N,X,X`
- eigene Lovelace-Karte inklusive Shared-Tablet-Profilwahl
- moderne, eingeklappte Einstellungsbereiche
- keine externen Python-Abhängigkeiten

### Stabilität und Robustheit

- Session-Lifecycle und Feedback-Persistenz abgesichert
- Feedback-Sampling kann nicht mathematisch einfrieren
- pausiertes Lernen verändert keine Lern-/Feedbackzähler
- Start-/Später-/Durchgehend-Feedback lernt aus dem richtigen Wetterkontext
- Böen werden beim persönlichen Windlernen berücksichtigt
- Arbeitsort und Zuhause werden innerhalb von Arbeitsfenstern nicht fälschlich vermischt
- fehlender Arbeits-Forecast erzeugt lieber eine Prognoselücke als Wetter vom falschen Ort
- Abend-/Eventkontext wird pro Forecast-Zeitpunkt berechnet
- Forecast-Horizont wird anhand realer Zeit statt bloßer Punktanzahl bestimmt
- Urlaub/Abwesenheit wird zeitlich aus Arbeitsfenstern herausgerechnet
- Shared-Profile-Zugriff auf Admins bzw. ausdrücklich freigegebene HA-Konten begrenzt
- Wetter-Einheiten werden zentral normalisiert; ungültige Einheiten werden verworfen
- UI-Zustand nach Feedback, Shared-Profilwechsel und Fehlern gehärtet
- Speicher bleibt durch begrenzte Sessions und verdichtete Lernwerte dauerhaft klein
- Regressionstests für Engine, Lernen, Profile, Sessions, Arbeitskontext und Wetterkonvertierung
- JavaScript-Syntax- und Frontend-Session-Test im CI-Workflow
