# Grundwasser (Deutschland) für Home Assistant

[![hassfest](https://github.com/hnehnes/niwis/actions/workflows/hassfest.yml/badge.svg)](https://github.com/hnehnes/niwis/actions/workflows/hassfest.yml)
[![HACS](https://github.com/hnehnes/niwis/actions/workflows/hacs.yml/badge.svg)](https://github.com/hnehnes/niwis/actions/workflows/hacs.yml)

Home-Assistant-Integration für **Grundwasserstände in Deutschland** aus mehreren
Quellen hinter einer gemeinsamen **Provider-Architektur**. Deutschland-Grundwasser
ist föderal organisiert – ein bundesweites, kuratiertes Netz (NIWIS/BfG) plus je
Bundesland ein dichtes Landesnetz. Diese Integration bündelt die Quellen und bietet
im Config-Flow die **tatsächlich nächste** Messstelle quellenübergreifend an.

## Datenquellen (Provider)

| Provider | Quelle | Abdeckung | Besonderheit |
| -------- | ------ | --------- | ------------ |
| `niwis` | Niedrigwasserinformationssystem der BfG – [niwis-online.de](https://niwis-online.de) | bundesweit | zusätzlich **Niedrigwasserklasse** + Trend (Bezug 1991–2020) |
| `lfu_bb` | LfU Brandenburg, Auskunftsplattform Wasser – [apw.brandenburg.de](https://apw.brandenburg.de) | Brandenburg (~2000 Stellen) | teils tägliche/wöchentliche Werte, m ü. NHN |

Weitere Landesnetze (Bayern GKD, Berlin, NRW ELWAS …) lassen sich als zusätzliche
Provider unter `custom_components/grundwasser_de/providers/` ergänzen; das Interface
ist in [`providers/base.py`](custom_components/grundwasser_de/providers/base.py)
dokumentiert.

## Funktionsumfang

Pro ausgewählter Messstelle wird ein **Gerät** angelegt, mit diesen Sensoren:

| Sensor | Beispiel-State | Einheit | Quellen |
| ------ | -------------- | ------- | ------- |
| Grundwasserstand | `42.0` | m (ü. NHN) | alle |
| Niedrigwasserklasse | `sehr niedrig` | ENUM-Text | nur NIWIS |
| Trend | `gleichbleibend` | ENUM-Text | nur NIWIS |

Die Niedrigwasserklasse ist ein Text-Sensor (ENUM) mit den Zuständen
**kein Niedrigwasser · niedrig · sehr niedrig · extrem niedrig · keine Daten**.
Die Quelle steht als **Hersteller** am Gerät, die Stations-ID als **Seriennummer**.

## Installation

### HACS (empfohlen)

1. HACS öffnen → *Integrationen* → Menü → **Benutzerdefinierte Repositories**.
2. `https://github.com/hnehnes/niwis` als Kategorie *Integration* hinzufügen.
3. „Grundwasser (Deutschland)" installieren und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/grundwasser_de` nach
`<config>/custom_components/grundwasser_de` kopieren und Home Assistant neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → **Grundwasser (Deutschland)***.
2. Suche wählen:
   - **Umkreis** um den Home-Assistant-Standort (Radius konfigurierbar) – sucht über
     **alle** Provider und sortiert nach Entfernung, oder
   - **Name/Stations-ID**.
3. Eine oder mehrere Messstellen aus der quellenübergreifenden Liste auswählen.

### Optionen

Über *Konfigurieren* am Eintrag:

- **Aktualisierungsintervall** (Standard 3 h, Minimum 1 h – Fair Use gegenüber den APIs).
- **Weitere Messstellen** per Umkreis- oder Namenssuche nachrüsten.

## Hinweise zur Datenlage

- Nicht jede Messstelle liefert jede Größe: manche Brunnen sind reine **Güte**-Pegel
  ohne Grundwasserstand – deren Wert-Sensor bleibt dann *unbekannt*.
- Die Kennziffern der LfU (Shapefile-`MKZ`) decken sich nicht immer 1:1 mit den
  Kennziffern der Auskunftsplattform; Stationen ohne dort abrufbare Zeitreihe
  liefern *unbekannt* statt eines Fehlers.

## Datenquelle & Attribution

- **NIWIS**: Bundesanstalt für Gewässerkunde (BfG), Bund/Länder und DWD –
  [niwis-online.de](https://niwis-online.de).
- **LfU Brandenburg**: Landesamt für Umwelt, Auskunftsplattform Wasser –
  [apw.brandenburg.de](https://apw.brandenburg.de), Datenlizenz **dl-de/by-2-0**.

Bitte die jeweils geltenden Nutzungs-/Lizenzbedingungen der Betreiber beachten.
Diese Integration steht in keiner Verbindung zu BfG oder LfU und wird nicht von
ihnen unterstützt. Das reverse-engineerte APW-Protokoll ist in
[`docs/research/apw-brandenburg.md`](docs/research/apw-brandenburg.md) dokumentiert.

## Logo / brands

Icon-/Logo-Dateien liegen unter
[`brands/custom_integrations/grundwasser_de/`](brands/custom_integrations/grundwasser_de/).
Für die Anzeige in Home Assistant und HACS die Dateien per PR bei
[home-assistant/brands](https://github.com/home-assistant/brands) unter
`custom_integrations/grundwasser_de/` einreichen.
