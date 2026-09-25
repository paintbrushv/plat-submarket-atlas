# Submarket Atlas

Institutional-quality multifamily submarket intelligence platform. Generates narrative-driven analytical reports from U.S. Census Bureau ACS data, suitable for REIT board reviews, LP presentations, and lender underwriting committees.

## Features

- **Concentric ring analysis** — 1, 3, and 5-mile radius demographics around any multifamily property
- **Peer submarket benchmarking** — compare against recognized market corridors
- **MSA-level context** — every local metric compared to the metro benchmark
- **11-year time series** — ACS 5-year estimates from 2013–2023 for full trend analysis
- **Institutional-quality charts** — custom Plotly theme with consistent color palette
- **Interactive maps** — Folium with choropleth, radius rings, and tract-level popups
- **Narrative-driven output** — executive summary bullets, section takeaways, and a submarket thesis
- **Print-ready HTML/PDF** — clean typography, proper page breaks, source citations

## Quick Start

```bash
# Setup
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ../geostack
pip install -e "../geostack[viz,notebooks,census]"
pip install -e .

# Generate a report
python -m submarket_atlas.report --property demo-park
```

Requires PostgreSQL 17 with PostGIS 3.6.1, and the [geostack](https://github.com/paintbrushv/geostack) library installed.

## Architecture

```
src/submarket_atlas/
├── config.py          # YAML property configuration loader
├── spatial.py         # PostGIS spatial queries (radius rings, peer tracts)
├── demographics.py    # Census API pipeline with PostGIS caching
├── metrics.py         # Derived analytics (CAGRs, ratios, aggregation)
├── charts.py          # Plotly chart generation with institutional theme
├── map.py             # Folium interactive map generation
├── narrative.py       # Executive summary and takeaway generation
└── report.py          # Full pipeline orchestrator
```

## Adding a New Property

1. Create a YAML config in `config/properties/`
2. Specify coordinates, FIPS codes, analysis radii, and peer submarkets
3. Run the report pipeline

See `config/properties/demo-park.yaml` for a complete example.

## Data Sources

- U.S. Census Bureau American Community Survey, 5-Year Estimates (2013–2023)
- Census TIGER/Line boundary files for spatial geometry
- OpenStreetMap Nominatim for geocoding

## Output

Reports are generated in `output/<property-slug>/` and include:
- Self-contained HTML report (print-ready)
- PDF version (via WeasyPrint)
- Interactive map (standalone HTML)
- Individual chart PNGs at 300 DPI
- CSV data exports for verification
