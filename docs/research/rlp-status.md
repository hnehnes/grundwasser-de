# Rheinland-Pfalz (LfU) — Provider-Status

**SHIPPABLE: NEIN** (Stand: 2026-07-17, live per `curl` verifiziert)

Geplante Domain: `lfu_rp` · Label: „Rheinland-Pfalz (LfU)".

## Kurzfazit / Begründung

Die **Stationen** sind hervorragend maschinenlesbar (offener WFS, GeoJSON,
WGS84). Es gibt aber **keinen** login-freien, maschinenlesbaren Weg zum
**aktuellen Grundwasserstand** oder zur **Ganglinie**:

- Weder der öffentliche WFS noch der interne GDA-GeoServer (über den offenen
  `geoserver.action`-Proxy erreichbar) tragen einen Messwert — nur
  Stammdaten + `ANZAHL_ANALYSEN` (Zähler, kein Wert).
- Die einzige Wert-/Zeitreihen-Quelle ist der Download-Assistent **AKSAM**, eine
  **Jakarta-Faces/PrimeFaces-Webapp** mit `JSESSIONID` + JSF-ViewState + POST —
  genau der fragile Session-XHR-Fall, den die Aufgabe explizit ausschließt.

Ein Provider, dessen `async_fetch` immer `value=None` liefern müsste, wäre ein
Wegwerf-Provider. Deshalb: **sauber nichts** statt dreckig etwas. Kein Code,
keine Tests, keine Fixtures angelegt — nur diese Notiz.

## Geprüfte Endpoints (alle live, 2026-07-17)

### 1. Stationen — WFS (funktioniert einwandfrei) ✅
```
https://geodienste-wasser.rlp-umwelt.de/geoserver/messstellen/grundwasser/wfs
  ?service=WFS&version=2.0.0&request=GetFeature
  &typeNames=messstellen:grundwasser
  &outputFormat=application/json&srsName=EPSG:4326
```
- `numberMatched=2678` Features. GeoServer liefert GeoJSON in WGS84,
  Koordinaten in **lon/lat**-Reihenfolge (kompatibel mit `_wfs.get_features`
  + `bbox_urn_4326`, wie bei `lfu_sh`).
- Properties je Feature: `MESSST_BEZ` (Name, z. B. „1340 II Kapsweyer"),
  `MESSST_ART` / `MESSST_ART_BEZ` (311 / „Grundwasserstände"),
  `AMTL_NR` (amtliche Nr., z. B. „1340 II"),
  `REGELMAESSIG_BEOBACHT_VON_JAHR`, `ANZAHL_ANALYSEN`.
- **Kein Messwert, kein Zeitreihen-Link, keine `MESSST_NR`** im öffentlichen WFS.
- WFS-GetCapabilities: `Fees=NONE`, `AccessConstraints=NONE`,
  Provider „Wasserwirtschaftsverwaltung Rheinland-Pfalz". Kein expliziter
  Lizenz-String (dl-de/by-2.0) im Capabilities-Dokument — Lizenz für die
  Stationen wohl offen, aber nicht formal bestätigt.

Global (`/geoserver/ows`) existiert **keine** GW-Messwert-/Ganglinien-Feature-
Type — nur Stammdaten-Layer (`messstellen:grundwasser`) und für
Oberflächenwasser `Pegel_aktuell:PEGEL_AKTUELL` (kein Grundwasser).

### 2. Interner GDA-GeoServer über offenen Proxy — ebenfalls ohne Werte ❌
Die Karte (`.../karte-grundwassermessstellen`) lädt den terrestris-React-Client
`gda-wasser.rlp-umwelt.de/.../geoportal-wasser/build/index.html?applicationId=100693`
(App „Auskunftssystem Grundwasser Messdatenauskunft MDA2"). Dessen
App-Kontext ist **ohne Login** abrufbar:
```
https://gda-wasser.rlp-umwelt.de/GDAWasser/config/getGdaAppContext.action?applicationId=100693
https://gda-wasser.rlp-umwelt.de/GDAWasser/geoserver.action?service=WMS&version=1.3.0&request=GetCapabilities
```
Der `geoserver.action`-Proxy exponiert u. a.
`GDA_Wasser:GW_GRUNDWASSERMESSSTELLEN_QUANT` (788 quantitative
GW-Messstellen, MDA2). WFS-`GetFeature` darauf liefert aber **dieselben
Stammdaten ohne Messwert** (`MESSST_NR, MESSST_BEZ, AMTL_NR, ANZAHL_ANALYSEN`).
Im gebündelten React-`app.js` (8,6 MB) findet sich **kein** Ganglinien-/
Messwert-/Zeitreihen-Endpoint (nur ag-grid-„chartService"-Interna, irrelevant).

### 3. Zeitreihe/Werte — nur AKSAM (nicht sauber automatisierbar) ❌
```
https://aksam-web.rlp-umwelt.de/aksam/index
```
- Antwort setzt `Set-Cookie: JSESSIONID=…; Path=/aksam` und liefert eine
  **Jakarta-Faces/PrimeFaces**-Seite (`jakarta.faces.resource/…`, „Download-
  Assistent", KOBIT GmbH). Interaktion = POST mit JSF-ViewState, Session-
  gebunden. CSV-Export nur interaktiv.
- Kein dokumentierter REST: `/aksam/api` → HTTP 404, `/aksam/rest` → HTTP 404.

### 4. „Tageswerte"-Seite — kein GW-Downloadpfad ❌
`https://wasserportal.rlp-umwelt.de/auskunftssysteme/tageswerte` ist eine
TYPO3-CMS-Seite (Bootstrap-Tabs, Suche `/suche?type=7384`), kein Daten-API;
Schwerpunkt Pegel/Abfluss, kein maschinenlesbarer GW-Zeitreihen-Endpoint.

## Wenn RLP später doch gebaut werden soll
- Stationen sind trivial (`_wfs.get_features`, `srsName=EPSG:4326`, `bbox_urn_4326`,
  `AMTL_NR` als `station_id`, `MESSST_BEZ` als Name) — Muster exakt wie `lfu_sh`.
- Blocker bleibt die Ganglinie. Optionen (alle offen / zu klären):
  1. AKSAM-JSF-Flow per Browser-DevTools reverse-engineeren (ViewState-Handling,
     fragil, wartungsintensiv — nicht empfohlen).
  2. Bei der LfU RLP anfragen, ob es einen offiziellen Open-Data-Export der
     GW-Ganglinien gibt (analog SH `hsi-sh.de/gw/od/…`) bzw. auf open.rlp.de.
  3. GDA-„Messdatenauskunft"-Diagramm-Endpoint der **alten** gisclient-App
     (`client/gisclient/index-dev.html`) prüfen — hier nicht abschließend
     verifiziert, evtl. Servlet mit Chart-/Datendienst.

— 🤖 Claude Opus 4.8 (via Claude Code)
