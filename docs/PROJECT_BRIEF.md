# Projekt-Übergabe: von NIWIS zu „grundwasser_de"

Stand: 2026-07-16. Dieser Brief fasst den aktuellen Stand zusammen, damit ein
**neuer Chat** sofort produktiv weiterarbeiten kann. Einstieg dort z. B.:
*„Lies docs/PROJECT_BRIEF.md — wir bauen `grundwasser_de`."*

---

## 1. Was existiert (NIWIS-Integration – fertig, v1.0.2)

- **Repo:** dieses Repo (lokal ausgecheckt) → GitHub `github.com/hnehnes/niwis` (public).
  Releases v1.0.0 / v1.0.1 / v1.0.2. CI (hassfest, HACS, pytest/ruff) grün.
- **Installiert & läuft** in der HA-Instanz des Nutzers (via HACS Custom Repository).
- **HA-Zugang:** Home-Assistant-MCP-Server `home-assistant` (ha-mcp, stdio via uvx) ist
  in Claude Code verbunden — direktes Lesen/Steuern der Instanz möglich (Basis-URL steht
  in der lokalen MCP-Config). HA-Standort im Raum Hoppegarten (Brandenburg); die genauen
  Koordinaten sind live aus der Instanz auslesbar (`zone.home`).
- **Konfiguriert:** 8 Messstellen (Berlin/Löcknitz-Raum). entity_ids sind sauber
  (z. B. `sensor.niederschonhausen_pankow_grundwasserstand`). Dashboard
  `niwis-niedrigwasser` mit 2 Tabs (Übersicht-Tabelle + Verläufe nebeneinander).

### NIWIS-API (verifiziert – Details in `custom_components/niwis/const.py`)
- Basis `https://niwis-online.de/api`; **Browser-User-Agent nötig** (WAF Airlock).
- Liste je Messgröße: `GET /karte/messstelle/{MESSGROESSE}?klassifikationsart={DYNAMISCH|STATISCH}`
  → Objekte mit `nummer, anzeigeName, koordinate{x=lon,y=lat}, aktuellerMesswert,
  niedrigwasserKlasse, entwicklung`.
- Stammdaten: `GET /karte/{grundwasser|wasserstand|abfluss}/{nummer}` (Gewässer, Ortslage…).
- `GET /config` → Klimareferenzperiode 1991–2020.
- Messgrößen: `GRUNDWASSER`/`QUELLSCHUETTUNG` (DEGM_), `WASSERSTAND`/`ABFLUSS` (DESM_).
  Einheiten: m ü. NHN / L/s / cm / m³/s.
- **Fehlwert-Sentinel `-777`** („Lücke") → wird in v1.0.2 als *unbekannt* behandelt.
- Niedrigwasserklasse (ENUM, Bezug 1991–2020): kein Niedrigwasser / niedrig /
  sehr niedrig / extrem niedrig / keine Daten.

### Offene NIWIS-Restpunkte (klein)
1. **brands-PR**: Icon/Logo liegen in `brands/custom_integrations/niwis/` → PR bei
   `home-assistant/brands` (nötig für HACS-Default + Icon-Anzeige).
2. **HACS-Default-PR**: `hnehnes/niwis` bei `hacs/default` eintragen (dann in HACS
   suchbar). Voraussetzungen erfüllt.
3. **Repo-Beispiel-Dashboard** `examples/niwis-dashboard.yaml` auf das finale
   Tabellen-Layout bringen (aktuell Kachel-Variante).
4. **Verwaister Alt-Sensor** `sensor.wesel_rhein_wasserstand` in der HA-Instanz löschen
   (Wächter hatte MCP-Löschung geblockt; Nutzer kann es selbst oder erneut freigeben).
5. Commit-Trailer „Co-Authored-By: Claude Opus" wurde aus Dateien entfernt; History-
   Rewrite war vom Nutzer gewünscht, aber Wächter-blockiert (Nutzer macht es selbst).

---

## 2. Neues Ziel: „grundwasser_de" – Provider-Architektur

Deutschland-Grundwasser ist föderal: NIWIS (BfG, bundesweit ~200 kuratierte Stellen,
liefert **Niedrigwasser-Klasse**) + je Bundesland ein dichtes Landesnetz.

**Eine Integration, mehrere austauschbare Provider mit gemeinsamem Interface:**

```
Provider:
  async_search(lat, lon, radius_km) -> [Station]   # Umkreissuche
  async_fetch(station)              -> Reading       # Wert, Einheit, Historie, ggf. Klasse/Trend

  niwis   (BfG)             – bundesweit, Niedrigwasser-KLASSE   ← Code vorhanden, → providers/niwis.py
  lfu_bb  (Brandenburg/APW) – ~2000 Stellen, teils tägliche Werte
  gkd_by, berlin, elwas_nrw, … – inkrementell
```

- **Config-Flow:** Standort + Radius → Suche über *alle* aktiven Provider →
  quellenübergreifend nächste Messstellen anbieten (dedupliziert). Gerät = Messstelle,
  Quelle als Attribut/Modell.
- **Nutzen:** tatsächlich nächste Station statt „nur was NIWIS zeigt"; wo NIWIS
  mitspielt zusätzlich die Klasse.
- **Migration:** bestehendes `niwis` wird ein Provider; `api.py`/`coordinator.py` sind
  bereits quellenneutral. Da lokal / kaum Nutzer → jetzt idealer Umbauzeitpunkt.
- **Risiken:** jede Landes-API anders (ArcGIS/cardoMap/WFS/custom), nicht alle Echtzeit,
  unterschiedliche CRS & **Lizenzen**, Wartungsaufwand. Realistischer Start: NIWIS + LfU-BB.

### LfU Brandenburg (bereits recherchiert)
- **Messstellen-Stammdaten (Shapefile, 2003 Stellen):**
  `https://data.geobasis-bb.de/geofachdaten/Wasser/Grundwasser/gw_basis_mn.zip`
  CRS **EPSG:25833** (ETRS89/UTM33N). Felder u. a. `MKZ` (Kennziffer), `MENA`/`LAGE`
  (Ort), `ZYKLUS` (455× „täglich"), `GWART`, `NETZART`.
  Nächste zu Hoppegarten: **„Münchehofe, Hoppegarten" MKZ 35480874, 3,8 km, täglich**
  (vs. NIWIS Niederschönhausen 17 km). Parsing-Snippet: pyshp + pyproj (siehe unten).
- **Zeitreihen/aktuelle Werte:** Auskunftsplattform `https://apw.brandenburg.de/?th=ZR_GW_ME`
  — ist ein **cardoMap3-GIS** (IDU). **AUSGEGRABEN (2026-07-16, live verifiziert)** →
  vollständige Protokoll-Doku + reale Beispiel-Payload in `docs/research/apw-brandenburg.md`,
  Provider-Implementierung in `custom_components/niwis/providers/lfu_bb.py`, Fixtures/Tests in
  `tests/fixtures/lfu_bb/` + `tests/test_lfu_bb.py`. Kurz: AjaxPro-Kette MKZ→msid
  (`SelectionControl.AxExecuteQuery`, Layer L305, Feld `nummer`) →
  `MultiExportControl.AxGetAvailableParameterChoice`/`AxGetZeitraum`/`AxExport(format=1)` →
  ZIP mit CSV (m ü. NHN). **Achtung MKZ-Mismatch:** Shapefile-`MKZ` ≠ APW-`nummer`
  (Münchehofe Shapefile 35480874 vs APW 35480875, und Letzteres ist ein Güte-Pegel *ohne*
  Wasserstand). Der Join Shapefile↔APW ist also offen (siehe Teil B unten).
- WFS-Versuche auf `maps.brandenburg.de/services/wfs/*` für GW-Stellen: 404 (Wasser-
  Layer existieren dort, aber kein direkter GW-Messstellen-WFS gefunden).

```python
# Shapefile → nächste Stationen (funktioniert, getestet)
import shapefile, math
from pyproj import Transformer
tf = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)
r = shapefile.Reader("gw_basis_mn")
# fields: MKZ, LAGE, MENA, GIS_RW, GIS_HW, ZYKLUS, GWART, NETZART, ...
```

---

## 3. Fortschritt

**Teil B abgeschlossen** (Branch `feat/grundwasser-de-lfu-bb`, 30 Tests grün, ruff sauber,
live gegen NIWIS **und** APW verifiziert):

1. ✅ APW-Endpoint ausgegraben + reale Payload (`docs/research/apw-brandenburg.md`, Fixtures).
2. ✅ Provider-Interface `providers/base.py` + `providers/lfu_bb.py` (Suche + Fetch).
3. ✅ `providers/niwis.py` – NIWIS als Provider hinter demselben Interface (inkl. Klasse/Trend).
4. ✅ Umkreissuche `lfu_bb`: gebündelte Stationsliste `providers/lfu_bb_stations.json`
   (2003 Stellen, offline aus dem Shapefile; keine pyshp/pyproj-Laufzeit-Deps). Stationen ohne
   APW-Zeitreihe (MKZ-Mismatch / Güte-Pegel) liefern *unbekannt* statt Fehler.
5. ✅ Config-Flow quellenübergreifend (alle Provider parallel, dedupliziert, nach Distanz).
6. ✅ Coordinator/Sensoren provider-neutral; **Domain-Rename `niwis`→`grundwasser_de`** (v2.0.0).
   Alte `niwis`-Instanz + Dashboard + Orphan-Sensoren aus der HA-Instanz entfernt.

**Offene Restpunkte:**
- Integration unter `grundwasser_de` in HA (HACS Custom Repo) neu hinzufügen + Stationen wählen.
- Weitere Provider (Bayern GKD, Berlin, NRW ELWAS …) inkrementell.
- `examples/niwis-dashboard.yaml` ist veraltet (alte Entities/Name) – bei Bedarf neu erstellen.
- brands-/HACS-Default-PRs jetzt unter `grundwasser_de`.
