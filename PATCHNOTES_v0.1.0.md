# JackenBerater v0.1.0 – Patchnotes

Erste eigenständige Testversion.

## Neu

- persönliche Jackenempfehlung: keine / leichte / warme / Winterjacke
- getrennte Regenjacken-/Regenschutzlogik
- 9-h-Standardforecast mit bedingter Verlängerung bis 12 h
- optionaler Zeitkontext über Kalender bis ca. 16 h
- Innen→Außen-Übergang mit Sensor oder 21,5-°C-Fallback
- Berücksichtigung von Wind, Böen, Feuchte, Sonne/Bewölkung und Nässe, sofern vorhanden
- schwacher saisonaler Aktivitätskontext für typische Eventzeiten, abhängig von der persönlichen Abendroutine
- Profile pro Home-Assistant-User-ID
- vier fünfstufige Startfragen direkt in der Karte
- starkes Early Learning, später schrittweise vorsichtiger
- separate Lernzähler für allgemeines Empfinden, Wind, Übergang und Jackengrenzen
- freiwilliges Feedback jederzeit möglich
- Feedback-Sessions mit sichtbarem ursprünglichem Zeitpunkt und Wetterkontext
- max. 3 unbeantwortete / 20 letzte kompakte Sessions; Ablauf nach ca. 36 h
- Lernen pausieren, Profil zurücksetzen, letzte Bewertung rückgängig machen
- optionale Arbeitszone + separate Wetterquelle am Arbeitsort
- optionaler Arbeits-/Schichtkalender und Urlaubs-/Abwesenheitskalender
- rotierende Schichtzyklen wie `F,F,S,S,N,N,N,X,X`
- eigene Lovelace-Karte inkl. Wandtablet-Profilwahl
- moderne, eingeklappte Einstellungsbereiche statt einer langen grauen Konfigurationsmaske
- keine externen Python-Pakete

## Review-Hardening

- Feedback lernt bei mehrstufigen Empfehlungen aus dem richtigen Start-/Später-Kontext
- Böen fließen auch in den Lernkontext ein
- „Perfekt“ bestätigt relevante Jackengrenzen und erhöht deren Confidence
- ungewöhnliche Tage reduzieren jetzt auch das effektive Samplegewicht
- Home-/Work-Forecasts werden innerhalb von Arbeitsfenstern nicht mehr doppelt gegeneinander ausgewertet
- Shared-Tablet verlangt eine explizite Profilauswahl und setzt diese nach der Beratung zurück
- doppelte oder abgelaufene Feedbackabgaben werden sauber abgelehnt
- ft/s und Beaufort als zulässige Home-Assistant-Windeinheiten ergänzt
- unbekannte Wind-/Temperatureinheiten werden verworfen statt still falsch interpretiert
- Arbeitskonfiguration verhindert wirkungslose Work-Weather-Konfiguration ohne Zeitquelle
- Urlaub unterdrückt nur noch tatsächlich überlappende Arbeitsfenster
- CI um Unit-Tests und Compile-Prüfung ergänzt
- Regressionstest-Suite nach zweiter Review-Runde auf 35 Tests erweitert


## Zweite Review-Runde

- kritischen Session-Lifecycle repariert: neu erzeugte Sessions bleiben persistent auffindbar und können anschließend bewertet werden
- Feedback-Sampling von der Zahl abgegebener Bewertungen entkoppelt; periodische Rückfragen können nicht mehr mathematisch einfrieren
- pausiertes Lernen friert jetzt auch Lern-/Feedbackzähler vollständig ein
- Arbeitskontext ohne eigenen Hourly-Forecast entfernt Home-Prognosen aus dem Arbeitsfenster, statt Wetter vom falschen Ort zu zeigen
- saisonaler Abend-/Eventkontext wird pro Forecast-Zeitpunkt statt einmal global berechnet
- auch beim Wärmerwerden werden Temperatur, Wind, Böen und Effektivwert des späteren Punkts für Feedback gespeichert
- „Durchgehend“-Feedback lernt einmal global sowie getrennt aus Start- und Später-Kontext, ohne doppelte Gesamtbewertung
- offene angeforderte Feedbacks sind vor Verdrängung durch manuelle/unangeforderte Sessions geschützt
- Shared-Profile-Zugriff auf Administratoren bzw. ausdrücklich freigegebene HA-Konten begrenzt
- Urlaubs-/Abwesenheitsfenster werden zeitlich von Arbeitsschichten abgezogen, statt bei Teilüberschneidung die ganze Schicht zu löschen
- ein ausgewählter Arbeitskalender ist autoritativ: leerer Kalender bedeutet frei und fällt nicht auf den Schichtzyklus zurück
- Forecast-Horizont wird nach real verstrichener Zeit statt nach Anzahl der Forecast-Punkte bestimmt; vergangene Punkte werden verworfen
- „Winterjacke war zu kalt“ erhöht nicht fälschlich die Confidence einer nicht weiter verschiebbaren Wintergrenze
- „Ungewöhnlicher Tag“ ist jetzt in der Karte erreichbar und reduziert das Lerngewicht
- Setup-Werte werden beim Shared-Profilwechsel zurückgesetzt
- beschädigte RunningStat-Storage-Daten fallen robust auf ein frisches Modell zurück
- Sensor-/Switch-/Button-Namen nutzen Übersetzungs-Keys statt fest verdrahtetem Deutsch
- Geräte-Softwareversion nutzt dieselbe Runtime-Konstante; Regressionstest prüft zusätzlich Manifest ↔ Runtime-Version

## Dritte Review-Runde

- Frontend löscht eine lokal bereits bewertete Session sofort, damit dieselbe Bewertung im geöffneten Detailpanel nicht erneut angeboten wird
- englische Übersetzung für „Heute war ungewöhnlich – schwächer gewichten“ ergänzt
- Profil-Entities aktualisieren ihre Translation-Placeholder bei späteren HA-Namensänderungen
- Storage-Bereinigung wird nach dem Laden nur dann verzögert persistiert, wenn sich die gespeicherten Daten durch Cleanup/Normalisierung tatsächlich geändert haben
- RuntimeError bei Frontend-Pfadregistrierung bleibt robust abgefangen, wird aber im Debug-Log nachvollziehbar
- CI prüft jetzt zusätzlich JavaScript-Syntax und einen funktionalen Frontend-Session-Test
- Regressionstest-Suite auf 36 Python-Tests plus JavaScript-Session-Vertrag erweitert
