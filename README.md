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

## Geräte, Namen & Gruppierung

- Je **Messstelle** wird ein **Gerät** angelegt. Der Gerätename ist sprechend und
  stammt aus den NIWIS-Stammdaten: **Ortslage** bei Grundwasser (z. B.
  „Niederschönhausen (Pankow)"), **Name + Gewässer** bei Oberflächenwasser
  (z. B. „Woltersdorf OP (Rüdersdorfer)"). Die technische Stations-ID steht als
  **Seriennummer** am Gerät.
- Die **Messgröße** (Grundwasserstand / Wasserstand / Abfluss / Quellschüttung)
  steht als Geräte-**Modell** und ist über die passende `device_class` typisiert –
  eine separate „Kategorie" ist in HA dafür nicht nötig (`entity_category` würde
  die Sensoren fälschlich als *Diagnose* einstufen und ausblenden). Zum Sortieren
  eignen sich **HA-Labels** oder die Gruppierung im **Dashboard** (siehe unten).

## Beispiel-Dashboard

Ein fertiges Beispiel mit Verlaufs-/Statistik-Graphen liegt unter
[`examples/niwis-dashboard.yaml`](examples/niwis-dashboard.yaml) – Sektionen je
Messgröße, aktueller Wert, Niedrigwasserklasse und History-Graph. Einfach den
Raw-Konfigurationseditor eines neuen Dashboards damit füllen und die entity_ids
an deine Messstellen anpassen.

## Datenquelle & Attribution

Datenbasis: **Niedrigwasserinformationssystem NIWIS** der Bundesanstalt für
Gewässerkunde (BfG), Bund/Länder und DWD – [niwis-online.de](https://niwis-online.de).
Bitte die jeweils geltenden Nutzungs-/Datenlizenzbedingungen der BfG beachten.
Diese Integration steht in keiner Verbindung zur BfG und wird nicht von ihr unterstützt.

## Logo / brands

Fertige Icon-/Logo-Dateien liegen unter
[`brands/custom_integrations/niwis/`](brands/custom_integrations/niwis/)
(`icon.png` 256×256, `icon@2x.png` 512×512, `logo.png`, `logo@2x.png`). Für die
Anzeige in Home Assistant und HACS die Dateien per PR bei
[home-assistant/brands](https://github.com/home-assistant/brands) unter
`custom_integrations/niwis/` einreichen.

## Hinweise

- Vor der Aufnahme in den HACS-Default-Store das Repository öffentlich machen und
  einmalig ein Release/Tag (z. B. `v1.0.1`) erstellen.
