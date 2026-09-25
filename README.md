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
# Setup (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate

# geostack is a documented prerequisite (its PyPI name is occupied by an
# unrelated project), so install the real engine from GitHub first:
pip install "geostack[viz] @ git+https://github.com/paintbrushv/geostack.git"

pip install .

# Optional: PNG chart export and PDF report export
pip install ".[png]"    # plotly kaleido engine
pip install ".[pdf]"    # weasyprint (requires system cairo/pango)

# Generate a report
python -m submarket_atlas.report --property demo-park
```

Requires PostgreSQL 17 with PostGIS 3.6.1, and the [geostack](https://github.com/paintbrushv/geostack) engine installed as a prerequisite (see Quick Start — its PyPI name is occupied by an unrelated project, so install it from GitHub).

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
├── report.py          # Full pipeline orchestrator
└── templates/
    └── report.html    # Jinja2 report template (shipped package data)
```

## Adding a New Property

1. Create a YAML config in `config/properties/` (repo) — installed-library users can point `CONFIG_DIR` anywhere, and `submarket_atlas/properties/demo-park.yaml` ships as a bundled example
2. Specify coordinates, FIPS codes, analysis radii, and peer submarkets
3. Run the report pipeline

See `src/submarket_atlas/properties/demo-park.yaml` for a complete example.

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
