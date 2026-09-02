# JackenBerater – Projektkontext

Dieses lokale Projekt wurde am 2. September 2026 aus dem ChatGPT-Projekt
„Jackenberater“ übernommen.

- Quellprojekt: https://chatgpt.com/g/g-p-6a983d3dc0288191b241cbfcd430cacf-jackenberater/project
- Übernommener Chat: „Kältegefühl Tracken“
- Importierter Stand: JackenBerater v0.1.2
- Originalpaket: `JackenBerater_v0.1.2.zip`

## Zweck

JackenBerater ist eine Home-Assistant-Integration, die auf Basis von Wetter,
persönlichem Kälteempfinden und optionalem Arbeits-/Kalenderkontext eine
Jackenempfehlung erzeugt.

## In v0.1.2 umgesetzte Schwerpunkte

- Persönliche Trend- und Kurzzeitlogik mit einem Anti-Flattern-Mindestfenster
  von ungefähr 15 Minuten.
- Bewertung kurzfristiger Phasen anhand von Dauer, Abstand zur persönlichen
  Jackengrenze, Wetterverstärkern und anschließendem thermischem Trend.
- Separat lernende Kurzzeit-Toleranz, ohne die normalen Jackengrenzen
  unbeabsichtigt zu verändern.
- Saisonale Feinanpassung mit kompakter, begrenzter Historie.
- Dauerhafte lokale Personenauswahl für Wandtablets.
- Verständliches Infofeld zu Zeitraum, Trend, Forecast-Abdeckung, Confidence
  und verwendetem Arbeits-/Kalenderkontext.
- Export und Import des kompakten Lernprofils als JSON.

## Letzter dokumentierter Prüfstand

Der Quellchat nennt 108/108 erfolgreiche Python-Tests sowie erfolgreiche
Prüfungen für Frontend-Vertrag, JavaScript-Syntax, Python-Compile, JSON und
Paketstruktur. Diese Angaben stammen aus dem Browserprojekt und sollten lokal
erneut verifiziert werden, bevor v0.1.2 weiterentwickelt oder veröffentlicht
wird.

## Wichtige Produktentscheidung

Eine Jackenstufe soll nicht wegen eines winzigen Zeitfensters zur
Hauptempfehlung werden. Das Mindestfenster schützt gegen Empfehlungen für nur
wenige Minuten; oberhalb davon entscheidet weiterhin die persönliche
thermische Belastung zusammen mit dem längerfristigen Verlauf. Kleidung unter
der Jacke wird nicht abgefragt.
