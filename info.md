# Grundwasser (Deutschland)

Grundwasserstände für Home Assistant aus **mehreren Quellen** über eine
gemeinsame Provider-Architektur:

- **NIWIS** (Bundesanstalt für Gewässerkunde, BfG) – bundesweit, zusätzlich mit
  einheitlicher **Niedrigwasserklasse** (Bezug 1991–2020).
- **LfU Brandenburg** (Auskunftsplattform Wasser) – dichtes Landesnetz mit teils
  täglichen/wöchentlichen Messwerten.

Funktionen:

- **Quellenübergreifende Umkreissuche**: findet die tatsächlich nächste
  Messstelle über alle Quellen hinweg – oder Suche per Name/Stations-ID.
- Ein Gerät je Messstelle mit **Grundwasserstand** (m ü. NHN); NIWIS-Stationen
  zusätzlich mit **Niedrigwasserklasse** und **Trend**.
- Aktualisierung standardmäßig alle 3 Stunden (Fair Use).

Weitere Bundesland-Netze lassen sich als zusätzliche Provider ergänzen.
