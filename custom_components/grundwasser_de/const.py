"""Constants for the NIWIS integration.

NIWIS – Niedrigwasserinformationssystem der Bundesanstalt für Gewässerkunde (BfG),
live seit 15.07.2026 unter https://niwis-online.de.

Verified API (Stand 15.07.2026, gegen die Live-API geprüft)
-----------------------------------------------------------
Die öffentliche NIWIS-Web-App ist eine Angular-SPA und spricht ein eigenes
REST-Backend an (kein direkter ArcGIS-FeatureServer). Basis-URL::

    https://niwis-online.de/api

Relevante, ohne Authentifizierung erreichbare Endpunkte:

* ``GET /config``
      Liefert u. a. die Klimareferenzperiode ``{"von": 1991, "bis": 2020}``
      sowie die Standard-Klassifikationsart ``DYNAMISCH``.

* ``GET /karte/messstelle/{MESSGROESSE}?klassifikationsart={DYNAMISCH|STATISCH}``
      Liste **aller** Messstellen einer Messgröße inkl. aktueller Messwerte.
      Dies ist die Datenquelle für Sensoren *und* für die Umkreissuche im
      Config-Flow (die Objekte enthalten Koordinaten).
      Beispielobjekt (verifiziert)::

          {
            "nummer": "DESM_DEBY16607001",
            "anzeigeName": "Inkofen (Amper)",
            "koordinate": {"x": 11.8655273, "y": 48.4606574},  # x=lon, y=lat (WGS84)
            "aktuellerMesswert": 37.0,
            "niedrigwasserKlasse": "EXTREM_NIEDRIG",
            "entwicklung": "GLEICHBLEIBEND",
            "pegelUnterGlw": null,
            "anzahlTageUnterGlw": null,
            "hatSchifffahrtsrelevantenKennwert": false
          }

* ``GET /karte/{grundwasser|wasserstand|abfluss}/{nummer}``
      Stammdaten (Metadaten) einer Messstelle – Gewässer, Institution, Betreiber,
      Höhensystem etc. Wird einmalig zur Anreicherung der DeviceInfo genutzt.

Messgrößen / Stationsfamilien (verifiziert)::

    GRUNDWASSER      DEGM_… Grundwasserstand     Einheit  m ü. NHN   (232 Stationen)
    QUELLSCHUETTUNG  DEGM_… Quellschüttung       Einheit  l/s        ( 14 Stationen)
    WASSERSTAND      DESM_… Wasserstand          Einheit  cm         (361 Stationen)
    ABFLUSS          DESM_… Abfluss              Einheit  m³/s       (354 Stationen)

Eine Oberflächen-Messstelle (DESM_) kann sowohl WASSERSTAND als auch ABFLUSS
liefern (329 der Stationen liegen in beiden Listen). Grundwasser- (DEGM_) und
Quellschüttungs-Stationen sind disjunkt. Der Niedrigwasserbezug ist konstruktiv
die Klimareferenzperiode 1991–2020.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "grundwasser_de"

# --- API -------------------------------------------------------------------
API_BASE: Final = "https://niwis-online.de/api"
# Ein Browser-User-Agent ist nötig: das WAF (Airlock) vor niwis-online.de
# blockt Requests ohne bzw. mit CLI-User-Agents.
USER_AGENT: Final = (
    "Mozilla/5.0 (compatible; homeassistant-niwis/1.0; "
    "+https://github.com/hnehnes/niwis)"
)
API_TIMEOUT: Final = 60  # Sekunden; die Listen-Endpunkte rechnen serverseitig.

# NIWIS/BfG kodiert fehlende Messwerte als Sentinel -777 ("Lücke"). Solche Werte
# (und noch negativere Varianten) sind keine echten Messwerte -> als unbekannt
# behandeln. Reale Tiefstwerte liegen weit darüber (z. B. -1 cm, -0,94 m ü. NHN).
MISSING_VALUE_SENTINEL: Final = -777.0

# Messgrößen (Kartenthemen), wie vom Backend erwartet.
MG_GRUNDWASSER: Final = "GRUNDWASSER"
MG_QUELLSCHUETTUNG: Final = "QUELLSCHUETTUNG"
MG_WASSERSTAND: Final = "WASSERSTAND"
MG_ABFLUSS: Final = "ABFLUSS"

MESSGROESSEN: Final = (
    MG_GRUNDWASSER,
    MG_QUELLSCHUETTUNG,
    MG_WASSERSTAND,
    MG_ABFLUSS,
)

# Klassifikationsart: DYNAMISCH ist die App-Voreinstellung, STATISCH die
# statische Einstufung gegen 1991–2020. Beide sind live verifiziert.
KLASS_DYNAMISCH: Final = "DYNAMISCH"
KLASS_STATISCH: Final = "STATISCH"
KLASSIFIKATIONSARTEN: Final = (KLASS_DYNAMISCH, KLASS_STATISCH)

# --- Niedrigwasserklasse (ENUM-Sensor) -------------------------------------
# Verifizierte Enum-Werte inkl. deutscher Anzeigetexte aus der Web-App.
LWK_KEIN: Final = "KEIN_NIEDRIGWASSER"
LWK_NIEDRIG: Final = "NIEDRIG"
LWK_SEHR_NIEDRIG: Final = "SEHR_NIEDRIG"
LWK_EXTREM_NIEDRIG: Final = "EXTREM_NIEDRIG"
LWK_KEINE_DATEN: Final = "KEINE_DATEN"

NIEDRIGWASSERKLASSEN: Final = (
    LWK_KEIN,
    LWK_NIEDRIG,
    LWK_SEHR_NIEDRIG,
    LWK_EXTREM_NIEDRIG,
    LWK_KEINE_DATEN,
)

# --- Entwicklung / Trend ---------------------------------------------------
ENTWICKLUNG_STEIGEND: Final = "STEIGEND"
ENTWICKLUNG_GLEICHBLEIBEND: Final = "GLEICHBLEIBEND"
ENTWICKLUNG_FALLEND: Final = "FALLEND"

ENTWICKLUNGEN: Final = (
    ENTWICKLUNG_STEIGEND,
    ENTWICKLUNG_GLEICHBLEIBEND,
    ENTWICKLUNG_FALLEND,
    LWK_KEINE_DATEN,  # das Backend liefert für den Trend ebenfalls "KEINE_DATEN"
)

# Deutsche Anzeigetexte (verifiziert aus der Web-App) – dienen direkt als
# Text-State der ENUM-Sensoren, wie in der Aufgabenstellung gefordert.
LWK_DISPLAY: Final[dict[str, str]] = {
    LWK_KEIN: "kein Niedrigwasser",
    LWK_NIEDRIG: "niedrig",
    LWK_SEHR_NIEDRIG: "sehr niedrig",
    LWK_EXTREM_NIEDRIG: "extrem niedrig",
    LWK_KEINE_DATEN: "keine Daten",
}
LWK_DISPLAY_OPTIONS: Final = list(LWK_DISPLAY.values())

ENTWICKLUNG_DISPLAY: Final[dict[str, str]] = {
    ENTWICKLUNG_STEIGEND: "steigend",
    ENTWICKLUNG_GLEICHBLEIBEND: "gleichbleibend",
    ENTWICKLUNG_FALLEND: "fallend",
    LWK_KEINE_DATEN: "keine Daten",
}
ENTWICKLUNG_DISPLAY_OPTIONS: Final = list(ENTWICKLUNG_DISPLAY.values())

# Sprechende Bezeichnung der Messgröße (Entity-Name-Bestandteil).
MESSGROESSE_DISPLAY: Final[dict[str, str]] = {
    MG_GRUNDWASSER: "Grundwasserstand",
    MG_QUELLSCHUETTUNG: "Quellschüttung",
    MG_WASSERSTAND: "Wasserstand",
    MG_ABFLUSS: "Abfluss",
}

# Einheiten je Messgröße (verifiziert aus der App).
UNIT_BY_MESSGROESSE: Final[dict[str, str]] = {
    MG_GRUNDWASSER: "m",  # "m ü. NHN" – HA-kompatible Einheit ist Meter
    MG_QUELLSCHUETTUNG: "L/s",
    MG_WASSERSTAND: "cm",
    MG_ABFLUSS: "m³/s",
}

# Detail-/Stammdaten-Pfadsegment je Messgröße (für DeviceInfo-Anreicherung).
DETAIL_PATH_BY_MESSGROESSE: Final[dict[str, str]] = {
    MG_GRUNDWASSER: "grundwasser",
    MG_QUELLSCHUETTUNG: "grundwasser",  # Quellschüttung nutzt die GW-Stammdaten
    MG_WASSERSTAND: "wasserstand",
    MG_ABFLUSS: "abfluss",
}

# --- Config / Options ------------------------------------------------------
CONF_STATIONS: Final = "stations"
CONF_STATION_NUMMER: Final = "nummer"
CONF_STATION_NAME: Final = "name"
CONF_STATION_MESSGROESSEN: Final = "messgroessen"
CONF_RADIUS: Final = "radius"
CONF_KLASSIFIKATIONSART: Final = "klassifikationsart"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_QUERY: Final = "query"

# Provider-neutral station descriptor keys (grundwasser_de architecture).
# A configured station is {provider, station_id, name}. ``provider`` names the
# source (see providers/), ``station_id`` is that source's native id.
CONF_PROVIDER: Final = "provider"
CONF_STATION_ID: Final = "station_id"

DEFAULT_RADIUS_KM: Final = 25.0
DEFAULT_SCAN_INTERVAL_HOURS: Final = 3
MIN_SCAN_INTERVAL_HOURS: Final = 1  # Fair Use gegenüber der BfG-API
DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS)

ATTRIBUTION: Final = (
    "Datenbasis: Niedrigwasserinformationssystem NIWIS der Bundesanstalt für "
    "Gewässerkunde (BfG), Bund/Länder und DWD – niwis-online.de"
)
MANUFACTURER: Final = "Bundesanstalt für Gewässerkunde (NIWIS)"
