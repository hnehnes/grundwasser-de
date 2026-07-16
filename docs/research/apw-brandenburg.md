# APW Brandenburg — Grundwasser-Zeitreihen-Endpoint (ausgegraben 2026-07-16)

Auskunftsplattform Wasser (APW) Brandenburg: `https://apw.brandenburg.de/?th=ZR_GW_ME`
Plattform: **cardoMap3 v3.9.7** (IDU), ASP.NET + AjaxPro + PostgreSQL (Npgsql). Backend-App
`IDU.cmApp.LFUBRB` (LfU Brandenburg). Datenlizenz **dl-de/by-2-0**.

Vollständige, live verifizierte Kette **MKZ → Zeitreihe**. Alle Aufrufe read-only.

## Session & Header

Session per `GET https://apw.brandenburg.de/?th=ZR_GW_ME` holen (setzt `ASP.NET_SessionId` +
`cardo3SessionGuid`). Keine weitere Auth. Jeder AjaxPro-POST braucht:

```
User-Agent: <Browser-UA>
Referer: https://apw.brandenburg.de/?th=ZR_GW_ME
X-AjaxPro-Method: <MethodenName>
Content-Type: text/plain; charset=UTF-8
Cookie: ASP.NET_SessionId=…; cardo3SessionGuid=…
Body: JSON der benannten Argumente
```

Antwortform: `{"value": …}` bei Erfolg, `{"error":{"Message":…,"Type":…}}` bei Fehler.

## Kartenthema / Layer

- Thema `ZR_GW_ME` = „1 Grundwasserstand (gesamt)", **ThemeId `256.397`**, PostgresLayer **`L305`**.
- Suchbare Felder von L305 (`IwanQueryEditor.AxGetSearchableFields(["L305"])`):
  `name` (Name der Messstelle), `kreis`, `gemeinde`, `grundwasserkoerper`,
  **`nummer` = Messstellenkennzahl (MKZ)**, `eu_cd_gb`.
- Der Attributabfrage-Record von L305 führt zusätzlich die Spalten:
  `msid` (**interne Messstellen-ID**), `param_hs`, `param_gok`, `zeitpunkt`,
  `nw_gok/mw_gok/hw_gok`, `nw_nhn/mw_nhn/hw_nhn` (Niedrig-/Mittel-/Höchstwerte + aktueller Stand).

## Schritt 1 — MKZ → interne `msid` (Attributabfrage)

Endpoint: `POST /ajaxpro/IDU.cardoMap3.WebV2.Controls.SelectionTools.SelectionControl.SelectionControl,cardo.Map3Lib.ashx`
Methode `AxExecuteQuery(themeIds, filter)`. `filter` ist ein typisiertes iwan-Filterobjekt
(`__type`-Diskriminator; für ein String-Feld `AxIOComparisonFilterString`):

```json
{"themeIds":["256.397"],
 "filter":{
   "__type":"IDU.Core.Web.Controls.SelectionTools.IwanQueryEditor.AxTypes.AxIOComparisonFilterString, IDU.Core, Version=1.0.0.0, Culture=neutral, PublicKeyToken=107e611434a88619",
   "columnName":"nummer","compareOperator":"Equal","values":["25500006"]}}
```

`compareOperator`: `"Equal"` (oder `1`). Enum `OperatorType`:
Equal, NotEqual, Greater, GreaterEqual, Less, LessEqual, Like, NotLike, In, NotIn, Between, IsNull, IsNotNull.

Antwort: `value.singleThemeResult[0].Hits[…].Text` (HTML). Darin steht der Diagramm-Link mit der
internen ID: `…/Diagramm.aspx?diagramm_config=GW_WASSERSTAND&id_messstelle=8449&…`.
→ **interne `msid` per Regex `id_messstelle=(\d+)`** herausziehen. Für MKZ `25500006` (Grimme) = **8449**.
(Hinweis: das aus dem Shapefile bekannte MKZ `35480874` Münchehofe lieferte im APW-Layer *keinen*
Treffer — die APW-`nummer` deckt sich nicht 1:1 mit dem Shapefile-`MKZ`; beim Provider-Bau abgleichen.)

## Schritt 2 — Parameter je Messstelle

Endpoint (Zeitreihen-Control): `POST /ajaxpro/IDU.cmApp.LFUBRB.Diagramme.Controls.MultiExportControl.MultiExport,IDU.cmApp.LFUBRB.Diagramme.ashx`
Methode `AxGetAvailableParameterChoice(ids, blackAndWhiteListings)`:

```json
{"ids":[8449],"blackAndWhiteListings":null}
```

Liefert `parameterAuswahl` — für GW-Stellen zwei Parameter:
- **`50503000`** „Wasserstand(NHN)" — Höhensystem, Einheit **m ü. NHN** (analog NIWIS-Grundwasser).
- `36503010` „Wasserstand(GOK)" — unter Geländeoberkante, Einheit cm uGOK.

## Schritt 3 — verfügbarer Zeitraum (optional)

`AxGetZeitraum(parameterIds, mstIds)`:
```json
{"parameterIds":[50503000],"mstIds":[8449]}
```
→ `{"anfang":"/Date(ms)/","ende":"/Date(ms)/"}` (WCF-Datum, ms seit Epoch). Grimme: **1962-11-01 … 2024-07-03**.

## Schritt 4 — Export der Zeitreihe

`AxExport(parameterIds, mstIds, zusammenfassungVersion, userBeginn, userEnde, format)`:
```json
{"parameterIds":[50503000],"mstIds":[8449],
 "zusammenfassungVersion":4,"userBeginn":null,"userEnde":null,"format":1}
```
- `userBeginn`/`userEnde`: `null` = kompletter Zeitraum, sonst WCF-Datum `"/Date(ms)/"`.
- `zusammenfassungVersion` (Enum): `null`/`Einzeldatei` · `2`=DreiSpalten · **`4`=EineSpalte**.
- **`format`**: **`0` = XLSX**, **`1` = CSV** (empfohlen, leicht zu parsen). Werte 2–5 → Fehler.

Antwort ist **kein** Inline-Payload, sondern ein Download-Link auf eine **ZIP** im Session-Temp:
```
value = "/cminetusr/ogc.ashx?Service=UTIL&Request=DownloadFileFromSessionTempFolder&file=<guid>.zip&mode=Attachment&name=Messreihen&mimetype=application%2fzip&<ts>"
```
Diesen Pfad mit derselben Session per GET holen → ZIP.

## Payload-Schema (format=1, CSV)

ZIP-Inhalt:
- `<MKZ>,<Name>/Metadaten.csv` — Stammdaten (siehe unten)
- `<MKZ>,<Name>/<MKZ>,<Name>_messreihen.csv` — **die Zeitreihe**
- `Parameterübersicht.csv` — Messstelle × Parameter (Kreuztabelle)
- `Impressum.pdf` — Attribution/Lizenz

**Zeitreihen-CSV** (UTF-8 **mit BOM**, `;`-getrennt, Werte in `"…"`, **Dezimal-Komma**):
```
;"Mengendaten"
"Zeitpunkt";"Wasserstand(NHN) [mNHN]"
01.11.1962;"26,32"
08.11.1962;"26,38"
…
03.07.2024;"25,19"
```
- Datum `dd.MM.yyyy`, Wert deutsches Komma (`25,19` → 25.19). ~wöchentlich, hier **2768 Punkte** 1962–2024.
- Fehlwerte: leere Zellen (im Beispiel keine); beim Provider defensiv auf leere/`-`-Werte prüfen.

**Metadaten.csv** (Auszug): Ostwert/Nordwert (EPSG **25833**), Messstellennummer, Messstellenart
(z. B. Brunnen), Höhensystem (NHN16), Geländehöhe, Filter OK/UK, NW/MW/HW in cm uGOK **und** m ü. NHN,
Bezugszeitraum Hauptwerte (`1963 / 2025`).

## Gespeicherte Fixtures (`scratchpad/fixtures/`)

| Datei | Inhalt |
|---|---|
| `axexecutequery_response.json` | AxExecuteQuery-Antwort MKZ 25500006 (enthält `id_messstelle=8449`) |
| `axparameterchoice.json` | AxGetAvailableParameterChoice([8449]) |
| `axgetzeitraum.json` | AxGetZeitraum → 1962-11-01…2024-07-03 |
| `axexport_request.json` / `axexport_response.json` | AxExport-Request + Download-Link |
| `axexport_full.zip` | echtes Export-ZIP (format=1) |
| `messreihen_25500006.csv` | extrahierte Zeitreihe (2768 Punkte) |
| `metadaten_25500006.csv` | extrahierte Stammdaten |

## Copy-paste curl (komplette Kette)

```bash
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36'
B=https://apw.brandenburg.de
SEL="$B/ajaxpro/IDU.cardoMap3.WebV2.Controls.SelectionTools.SelectionControl.SelectionControl,cardo.Map3Lib.ashx"
DIA="$B/ajaxpro/IDU.cmApp.LFUBRB.Diagramme.Controls.MultiExportControl.MultiExport,IDU.cmApp.LFUBRB.Diagramme.ashx"
TYPE='IDU.Core.Web.Controls.SelectionTools.IwanQueryEditor.AxTypes.AxIOComparisonFilterString, IDU.Core, Version=1.0.0.0, Culture=neutral, PublicKeyToken=107e611434a88619'
curl -s -c cookies.txt -A "$UA" "$B/?th=ZR_GW_ME" -o /dev/null            # Session
ax(){ curl -s -A "$UA" -b cookies.txt -e "$B/?th=ZR_GW_ME" -H "X-AjaxPro-Method: $1" -H 'Content-Type: text/plain; charset=UTF-8' --data "$2" "$3"; }
# 1) MKZ -> msid (Regex id_messstelle=\d+ aus der Antwort)
ax AxExecuteQuery "{\"themeIds\":[\"256.397\"],\"filter\":{\"__type\":\"$TYPE\",\"columnName\":\"nummer\",\"compareOperator\":\"Equal\",\"values\":[\"25500006\"]}}" "$SEL"
# 2) Parameter
ax AxGetAvailableParameterChoice '{"ids":[8449],"blackAndWhiteListings":null}' "$DIA"
# 3) Export -> Download-Link, dann ZIP holen
LINK=$(ax AxExport '{"parameterIds":[50503000],"mstIds":[8449],"zusammenfassungVersion":4,"userBeginn":null,"userEnde":null,"format":1}' "$DIA" | python3 -c 'import sys,json;print(json.load(sys.stdin)["value"])')
curl -s -A "$UA" -b cookies.txt -e "$B/?th=ZR_GW_ME" "$B$LINK" -o messreihen.zip
```

## Konsequenzen für den `lfu_bb`-Provider (Teil B)

- **Umkreissuche**: aus dem Shapefile (Koordinaten + MKZ), wie geplant. Achtung MKZ-Abgleich
  Shapefile↔APW-`nummer` (Münchehofe-Diskrepanz oben).
- **Aktueller Wert**: entweder (a) günstig direkt aus dem L305-Attributrecord (`zeitpunkt` + `*_nhn`),
  oder (b) letzter Punkt der Zeitreihe. (a) spart die 4er-Kette pro Poll.
- **msid-Auflösung** einmalig beim Hinzufügen der Station cachen (MKZ→msid + parameterId).
- **Parsing**: CSV (format=1), UTF-8-BOM, `;`, Dezimal-Komma; Datum `dd.MM.yyyy`. Einheit m ü. NHN
  (parameter 50503000) passt zur NIWIS-Grundwasser-Einheit „m".
- **Fair Use / Session**: cardo3-Session je Client halten; Poll-Intervall wie NIWIS (Stunden).
- **Export erzeugt serverseitig eine Temp-ZIP** — etwas schwergewichtig pro Station; ggf. später
  prüfen, ob `Diagramm.aspx`/ein leichterer Datenendpoint (`id_messstelle`) direkt JSON liefert.
```
