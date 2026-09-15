# JackenBerater v0.4.1

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

Jeder normale Home-Assistant-Benutzer hat sein eigenes Lernprofil. Beim ersten Einrichten werden fünf Startfragen gestellt – darunter ab v0.4.0 auch, wie früh der Nutzer normalerweise zu einem Pullover greift. Später kann das Profil durch Feedback angepasst werden:

- Zu kalt
- Perfekt
- Zu warm
- Nicht genutzt

Das allgemeine Profil ist der ganzjährige persönliche Grundwert. Winter, Frühling, Sommer und Herbst besitzen daneben jeweils einen eigenen Offset. Normales thermisches Feedback verändert nach der Initialisierung nur die gerade beteiligte Jahreszeit; während der rund 30-tägigen Überblendung um den meteorologischen Saisonwechsel lernen ausschließlich die beiden benachbarten Saisonanker. Die saisonale Lernrate richtet sich nach der eigenen echten Evidenz der jeweiligen Jahreszeit und bleibt auch nach vielen Jahren reaktionsfähig.

Beim allerersten Übergang in eine noch unbekannte Jahreszeit übernimmt sie einmalig nur den Offset der direkten Vorgängersaison als Startwert. Wird die komplette 30-Tage-Übergangszone verpasst, wird dieses einmalige Seeding beim ersten späteren Zugriff in der neuen Saison nachgeholt. Evidenz, Statistik und Lernhistorie werden nie mitkopiert; in späteren Jahren verwendet die Saison ausschließlich ihren eigenen zuletzt gelernten Zustand. Wurden mehrere ganze Jahreszeiten übersprungen und ist die direkte Vorgängersaison selbst unbekannt, wird keine künstliche Seed-Kette erzeugt: Nur die aktuell erreichte Saison startet dann neutral bei 0 relativ zu Main. Erst wenn alle vier Jahreszeiten ausreichend eigene Evidenz besitzen und ihre Offsets denselben gemeinsamen positiven oder negativen Sockel zeigen, wird dieser gemeinsame Anteil verlustfrei in den ganzjährigen Grundwert verschoben. `Main + Saisonoffset` bleibt dadurch für jede Jahreszeit unverändert. Bestehende v0.3.0-Profile werden beim Laden automatisch in dieses Modell migriert; synthetische Saisonwerte ohne eigene Evidenz werden dabei nicht als echte Saisonerfahrung übernommen.

Wenn sich die Empfehlung im Tagesverlauf ändert, zeigt die Feedbackkarte auch diesen Wechsel. Bei "Zu kalt" oder "Zu warm" fragt sie konkret nach, ob die erste Empfehlung, der spätere Wechsel oder ein längerer Zeitraum nicht gepasst hat. Ein falsch getimter Wechsel korrigiert gezielt die betroffene Jackengrenze statt pauschal das ganze Wärmeprofil.

Eine sichtbare Karte allein erzeugt keine Feedback-Session. Erst das bewusste Öffnen der Empfehlungsdetails zählt als Nutzung. Automatisches Feedback wird normalerweise frühestens nach 30 Minuten freigegeben.

Der interne thermische Rechenwert bleibt Teil der Berechnung, wird aber nicht als Temperaturwert auf der normalen Nutzerkarte angezeigt.

## Wetterempfinden ab v0.4.1

JackenBerater trennt ab v0.4.1 weitere Wetterursachen vom normalen persönlichen Wärmeprofil, damit Feedback an schwülen oder sonnigen Tagen nicht unnötig die allgemeinen Jacken-/Pullovergrenzen verschiebt.

### Luftfeuchte / Schwüle

Für warm-feuchte Luft wird nicht mehr nur die relative Luftfeuchtigkeit betrachtet. Aus Lufttemperatur und relativer Feuchte wird intern der **Taupunkt** als Maß für den tatsächlichen Feuchtegehalt der Luft abgeleitet. Dadurch werden beispielsweise 90 % rF bei kalter Luft nicht mit schwüler Sommerluft gleichgesetzt. Die warme Feuchtewirkung wird erst mit passender Lufttemperatur relevant und bleibt eine transparente Komfortheuristik, kein offizieller Heat-Index.

Das Lernmodell besitzt dafür getrennte kompakte Kanäle für **warm-feuchte/Schwüle-Empfindlichkeit** und den deutlich kleineren **kalt-feuchten Effekt**. Weil es dafür keine Startfrage und keinen persönlichen Setup-Prior gibt, dürfen diese Wetterkanäle bereits ab der ersten klar relevanten Bewertung vorsichtig eigene Evidenz sammeln. Feedback kann diese Faktoren korrigieren, ohne trockene Wetterlagen zu verschieben. Bei einer klar schwülen Situation darf selbst `Pullover + keine Jacke + zu warm` zuerst die Feuchteempfindlichkeit lernen, statt pauschal die Pullovergrenze für alle Wetterlagen zu verändern.

### Sonne / Strahlungspotenzial

Sonne wird bewusst als **Strahlungspotenzial** und nicht als behauptete direkte Besonnung modelliert. Eine Weather-Entity kann Bewölkung und einen Zustand wie `sunny` liefern, weiß aber nicht, ob die Person gerade unter einem Baum, zwischen Gebäuden oder auf freier Fläche steht. `sunny` erhält deshalb nur einen konservativen Wärmeaufschlag, der durch vorhandene Bewölkungsdaten gedämpft wird. `partlycloudy` bleibt ohne zusätzliche sichere Tageslicht-/Expositionsinformation thermisch neutral: Bewölkungsprozent allein beweisen weder Tageslicht noch persönliche Besonnung und einige Provider können `partlycloudy` auch nachts liefern.

Das separate Solarlernen startet nur bei einem starken `sunny`-Signal und lernt absichtlich langsamer als eindeutige Kleidungsgrenzen oder Wind. Wiederholtes Feedback kann dadurch abbilden, dass sonnige Wetterlagen für den Nutzer typischerweise stärker oder schwächer wirken, ohne zu behaupten, seine tatsächliche Schattenposition zu kennen. Treffen mehrere Wetter-Spezialfaktoren gleichzeitig zu, wird ihre Lernstärke geteilt, damit ein einzelnes Feedback nicht mehrere Ursachen voll verstärkt.

Die normale Nutzerkarte zeigt die verfügbare relative Luftfeuchte zusätzlich zur Temperatur an. Taupunkt, persönliche Feuchte-/Solarparameter und die übrigen internen Rechenwerte bleiben Diagnose-/Lernwerte und werden nicht als amtliche „gefühlte Temperatur“ ausgegeben.

Ein materiell aktiver Feuchte-/Solar-Spezialist mit noch weniger als drei eigenen Evidenzpunkten hält eine sonst vollständig ausgeblendete stabile Empfehlung mindestens kompakt erreichbar, damit der neue Kanal überhaupt gezielt Feedback sammeln kann. Reines Feedback zum **späteren Jackenwechsel** (`PHASE_LATER`) bewertet dagegen ausschließlich die betreffende Jackengrenze und verändert Feuchte-/Solarlernen nicht.

Nach einem Upgrade von v0.4.0 kann der angezeigte **Lernfortschritt leicht sinken**. Das ist kein Verlust alter Lerndaten: v0.4.1 erweitert die Breitenmetrik um Warmfeuchte, Kaltfeuchte und Solar, die bei bestehenden Profilen naturgemäß zunächst noch keine eigene Evidenz besitzen.

## Pullover / Midlayer ab v0.4.0

JackenBerater unterscheidet jetzt zwischen **Grundschicht am Oberkörper** und **abnehmbarer Außenschicht**. Die Grundschicht ist entweder Shirt oder Pullover; die bestehende Jackenskala bleibt unverändert `keine / leichte / warme / Winterjacke`. Hosen oder andere Kleidungsbereiche sind bewusst nicht Teil dieses Modells.

Der Pullover wird nicht als „später anziehen“-Forecast geplant. Er ist eine Entscheidung für den betrachteten Zeitraum. Bleiben die Bedingungen über mehrere Stunden kühl und ausreichend stabil, kann der Berater beispielsweise **Pullover ohne Jacke** statt **Shirt + leichte Jacke** empfehlen. Wird im Tages- oder Arbeitsverlauf dagegen eine deutliche Erwärmung erwartet, bevorzugt er bei vergleichbarer Wärme **Shirt + abnehmbare Jacke**, weil die Außenschicht später ausgezogen, getragen oder verstaut werden kann.

Bei anhaltend starker Kälte darf der Pullover zusätzlich mit einer Jacke kombiniert werden, zum Beispiel **Pullover + Winterjacke**. Dadurch kann der Berater unterhalb der bisherigen Winterjacken-Skala feiner unterscheiden, ohne den Pullover künstlich als weitere Jackenklasse zu behandeln. Die Pulloverwärme ist eine transparente Komfortheuristik und keine direkte Umrechnung eines `clo`-Wertes in Lufttemperatur.

Bestehende v0.3.x-Profile werden neutral migriert: Die bisherige Jacken-, Saison-, Wind- und Threshold-Personalisierung bleibt erhalten; der neue Pulloverbereich startet neutral und sammelt erst anschließend eigene Evidenz. Ein „zu warm“-Feedback bei **Pullover ohne Jacke** verschiebt gezielt die Pulloverentscheidung zu kühleren Bedingungen – auch wenn die Empfehlung zugleich eine kurzfristige Transient-Ausnahme verwendet. Ist zusätzlich eine abnehmbare Jacke beteiligt, wird weiterhin zuerst deren Außenschichtentscheidung bewertet, statt beide Kleidungsbereiche doppelt zu verändern.

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

`/jackenberater/frontend/jackenberater-card.js?v=0.4.1&ui=18`

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
