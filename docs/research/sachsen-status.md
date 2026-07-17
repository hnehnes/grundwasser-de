# Sachsen (LfULG) — Provider-Status: **SHIPPABLE: NEIN**

**Domain (reserviert):** `lfulg_sn` · **Label:** „Sachsen (LfULG)"
**Behörde:** Sächsisches Landesamt für Umwelt, Landwirtschaft und Geologie (LfULG); Betrieb durch BfUL.
**Geprüft:** 2026-07-17, live per `curl`.

## Kurzfazit

Stationen (Stammdaten + Koordinaten) sind offen und maschinenlesbar über ArcGIS REST / WFS
verfügbar — ein reiner Messstellen-Provider wäre trivial. **Aber es gibt keinen zuverlässigen,
login-freien, maschinenlesbaren Weg zu Grundwasserstand-Werten oder Ganglinien.** Die Werte liegen
ausschließlich hinter **Disy Cadenza** (iDA, `v9.4.340`, `cookielessMode`), erreichbar nur über eine
serverseitige Session und undokumentierte, versionsgebundene Workbook-XHR-Calls. Ein Werte-Provider
wäre damit ein fragiles Reverse-Engineering-Konstrukt, das bei jedem Cadenza-Upgrade bricht.

Gemäß Entscheidungsregel (nur bei **zuverlässig + login-frei + maschinenlesbar** vollen Provider
bauen) → **kein Wegwerf-Provider**. Kein `providers/lfulg_sn.py`, keine Tests/Fixtures angelegt.

## Geprüfte Endpoints

### Stationen — funktioniert (offen, maschinenlesbar)

- **ArcGIS REST MapServer:**
  `https://luis.sachsen.de/arcgis/rest/services/wasser/grundwassermessnetze/MapServer`
  - Ein Layer `0` „Grundwassermessnetze", Punktgeometrie, Query aktiviert, native SR `wkid 25833`.
  - `outSR=4326` liefert WGS84 direkt (kein `pyproj`), kompatibel mit `_arcgis.query_features`.
  - **Gesamt: 9.831 Messstellen**; Umkreis 5 km um Dresden (51.05, 13.74): **590 Treffer**.
  - Native Umkreissuche verifiziert:
    `.../MapServer/0/query?geometry=13.74,51.05&geometryType=esriGeometryPoint&inSR=4326&distance=5000&units=esriSRUnit_Meter&outFields=*&outSR=4326&f=json`
  - **Felder (nur Stammdaten, KEIN Wasserstand):** `MKZG` (Messstellenkennziffer, user-facing ID),
    `MENA` (Messstellenname), `MA` (Messstellenart: Grundwasserbeobachtungsrohr / Bohrbrunnen /
    Quelle …), `GISHOCH`/`GISRECHTS`, `NORDWERT`/`OSTWERT`, `MPH` (Messpunkthöhe),
    `GLH` (Geländehöhe), `HSYS` (Höhensystem NN/HN), `DATENBASIS_HAUPTWERTE`, `BESCHAFFENHEIT`,
    `MENGE`, `GANGLINIE`, `DATENSTAND`.
  - Beispiel-Feature: `MKZG=49484002`, `MENA="Dresden, Zschertnitz"`,
    `MA="Grundwasserbeobachtungsrohr"`, Geometrie `x=13.7413, y=51.0218`, `GLH=177.13 (NN)`.

- **WFS 2.0.0** (Spiegel derselben Stationsdaten):
  `https://luis.sachsen.de/arcgis/services/wasser/grundwassermessnetze/MapServer/WFSServer`
  - `GetCapabilities` → HTTP 200. FeatureType `grundwassermessnetze:Grundwassermessnetze`, EPSG:25833.
  - Nur als Alternative zur ArcGIS-Stationsabfrage; enthält ebenfalls **keine Werte**.

### Werte / Ganglinie — nicht login-frei erreichbar (Deal-Breaker)

- **`GANGLINIE`-Feld** = kein Wert, sondern ein Deep-Link auf die iDA-Diagrammseite. Bei
  Grundwasserständen `diagramm_w`, bei Quellen `diagramm_q`:
  `http://www.umwelt.sachsen.de/umwelt/infosysteme/ida/p/diagramm_w?mkz=<MKZG>`
  - 4.822 von 9.831 Stationen haben einen solchen Link (die übrigen gar keinen).
- **Direktaufruf `diagramm_w?mkz=…` → HTTP 401** (Cadenza-Zugriffsschutz), auch mit Cookie-Jar.
- Erst nach Öffnen der Workbook-Einstiegsseite
  `.../ida/p/grundwassermessstellen` (HTTP 200) liefert `diagramm_w` HTTP 200 —
  aber die Antwort ist **nur die Cadenza-SPA-Shell** (Titel „Diagramm: Grundwasserstand - iDA",
  amCharts + `workbook-api` + `chart-controller`-Bundles). **Keine eingebetteten Messwerte, kein
  Datum, kein CSV/JSON-Deep-Link.** Die eigentlichen Werte kommen aus nachgelagerten,
  session-gebundenen XHR-Calls in die undokumentierte Cadenza-Workbook-API.
- Cadenza-REST-Basispfade `.../ida/cadenza/repository` und `.../ida/cadenza/api` → **HTTP 401**.
- `cookielessMode: true` → Session serverseitig/URL-gebunden, nicht über einen stabilen Token
  reproduzierbar. Kein `REST_API`-Feature in `availableFeatures`
  (`ACCESS_MANAGER, CUSTOM_SKETCH_EDITORS, DATASOURCE_ARCGIS_REST, DATASOURCE_WFS, GAZETTEER,
  IMPORT_PRESETS, MAP_PRINT, PERMALINK, PROJECTS_ENABLED, TIMELINE, WEBAPP_INTEGRATION`).

## Lizenz

Laut LUIS/iDA: **dl-de/by-2.0** (Datenlizenz Deutschland – Namensnennung 2.0). Lizenz selbst wäre
also unkritisch — Blocker ist allein der fehlende offene Wert-Endpoint.

## Risiken / warum kein Provider

1. **Fragilität:** Cadenza-Workbook-XHR ist undokumentiert und an `v9.4.340` gebunden; ein Update
   bricht die Integration lautlos.
2. **Session-Handling:** cookieless, workbook-scoped Session — kein stabiler, login-freier Zugang.
3. **Wartungslast vs. Nutzen:** Ein reiner Stationen-Provider ohne Werte widerspricht dem
   Integrationszweck (aktueller Grundwasserstand + Ganglinie); Stationen ohne `value` wären zwar
   vom Interface (`value=None`) erlaubt, böten aber keinen Mehrwert.

## Wieder aufgreifen, wenn …

- LfULG/BfUL einen offenen Werte-Endpoint bereitstellt (z. B. Cadenza mit aktiviertem `REST_API`-
  Feature, ein OGC SensorThings API / WaterML-Dienst, oder ein CSV/JSON-Downloadpfad ohne Session).
- Dann: `_arcgis`-Stationen (`outSR=4326`, `MKZG`/`MENA`, Muster `hlnug_he.py`) + der neue
  Werte-Endpoint → voller Provider `providers/lfulg_sn.py` machbar.

— 🤖 Claude Opus 4.8 (via Claude Code)
