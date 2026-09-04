# Changelog

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
- Der Testmodus erkennt manuelle Zustandsänderungen über deren Benutzerkontext und besitzt keinen hängenbleibenden „ignoriere nächstes Ereignis“-Schalter mehr.
- Die neue Diagnose-Entität ersetzt nicht die alten v0.1.1-Schalter und Buttons; deren Registry-Einträge und verwaiste Gerätekarte werden beim Start weiterhin bereinigt.
- Teststand v0.1.3: **141 lokale Python-Tests** plus funktionaler Frontend-Vertragstest. CI enthält zusätzlich einen echten Home-Assistant-2026.9-Runtime-Smoke-Test unter Python 3.14 für Setup, Sensorplattform, WebSockets, Reload und Unload.

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
