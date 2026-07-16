# NIWIS – Niedrigwasser für Home Assistant

[![hassfest](https://github.com/hnehnes/niwis/actions/workflows/hassfest.yml/badge.svg)](https://github.com/hnehnes/niwis/actions/workflows/hassfest.yml)
[![HACS](https://github.com/hnehnes/niwis/actions/workflows/hacs.yml/badge.svg)](https://github.com/hnehnes/niwis/actions/workflows/hacs.yml)

Home-Assistant-Integration für das **Niedrigwasserinformationssystem (NIWIS)**
der Bundesanstalt für Gewässerkunde (BfG). NIWIS ist seit dem 15.07.2026 unter
[niwis-online.de](https://niwis-online.de) verfügbar und bündelt bundesweit
Grundwasserstände, Wasserstände, Abflüsse und Quellschüttungen samt einheitlicher
**Niedrigwasserklassifikation** (Bezugszeitraum 1991–2020).

## Funktionsumfang

Pro ausgewählter Messstelle wird ein Gerät angelegt, mit – je nach Messgröße –
diesen Sensoren:

| Sensor | Beispiel-State | Einheit |
| ------ | -------------- | ------- |
| Grundwasserstand / Wasserstand / Abfluss / Quellschüttung | `37.0` | m · cm · m³/s · L/s |
| Niedrigwasserklasse | `extrem niedrig` | ENUM-Text |
| Trend | `gleichbleibend` | ENUM-Text |

Die Niedrigwasserklasse ist ein reiner Text-Sensor (ENUM) mit den Zuständen
**kein Niedrigwasser · niedrig · sehr niedrig · extrem niedrig · keine Daten**.

## Installation

### HACS (empfohlen)

1. HACS öffnen → *Integrationen* → Menü → **Benutzerdefinierte Repositories**.
2. `https://github.com/hnehnes/niwis` als Kategorie *Integration* hinzufügen.
3. „NIWIS Niedrigwasser“ installieren und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/niwis` nach `<config>/custom_components/niwis`
kopieren und Home Assistant neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → **NIWIS***.
2. Suche wählen:
   - **Umkreis** um den Home-Assistant-Standort (Radius konfigurierbar), oder
   - **Name/Stations-ID**.
3. Eine oder mehrere Messstellen aus der Liste auswählen – fertig.

### Optionen

Über *Konfigurieren* am Eintrag:

- **Aktualisierungsintervall** (Standard 3 h, Minimum 1 h – Fair Use gegenüber der BfG-API).
- **Klassifikationsart** (`DYNAMISCH` – App-Standard – oder `STATISCH`).
- **Weitere Messstellen** per Umkreis- oder Namenssuche nachrüsten.

## Datenquelle & Attribution

Datenbasis: **Niedrigwasserinformationssystem NIWIS** der Bundesanstalt für
Gewässerkunde (BfG), Bund/Länder und DWD – [niwis-online.de](https://niwis-online.de).
Bitte die jeweils geltenden Nutzungs-/Datenlizenzbedingungen der BfG beachten.
Diese Integration steht in keiner Verbindung zur BfG und wird nicht von ihr unterstützt.

## Hinweise

- Für ein Integrations-Icon/-Logo in Home Assistant und HACS einen PR bei
  [home-assistant/brands](https://github.com/home-assistant/brands) mit der
  Domain `niwis` anlegen.
- Vor der Aufnahme in den HACS-Default-Store das Repository öffentlich machen und
  einmalig ein Release/Tag (z. B. `v1.0.0`) erstellen.
