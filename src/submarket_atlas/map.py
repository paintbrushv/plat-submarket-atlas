"""Interactive map generation with Folium."""

import json
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from folium.plugins import MarkerCluster
from shapely.geometry import Point

load_dotenv()

# geostack is a documented prerequisite (see submarket_atlas._deps); its
# import is deferred to call time so this module stays importable without it.
from submarket_atlas._deps import require_geostack
from submarket_atlas.charts import COLORS


def _gs():
    """Call-time geostack.db accessor (typed prerequisite guard)."""
    require_geostack()
    from geostack import db

    return db

METERS_PER_MILE = 1609.344


def _make_circle(lat, lon, radius_miles, label):
    """Create a dashed circle for radius rings."""
    return folium.Circle(
        location=[lat, lon],
        radius=radius_miles * METERS_PER_MILE,
        color=COLORS["primary"],
        weight=2,
        dash_array="8 6",
        fill=False,
        popup=f"{label}",
        tooltip=f"{radius_miles}-mile radius",
    )


def generate_map(
    config: dict,
    geographies: dict,
    scorecard: dict = None,
    output_dir: Path = None,
) -> Path:
    """Generate the interactive Folium map."""
    engine = _gs().get_engine()
    lat = config["coordinates"]["lat"]
    lon = config["coordinates"]["lon"]

    # Create map centered on property with CartoDB Positron basemap
    m = folium.Map(
        location=[lat, lon],
        zoom_start=12,
        tiles="CartoDB Positron",
        prefer_canvas=True,
    )

    # ── Property marker ───────────────────────────────────────────────────
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(
            f"<b>{config['name']}</b><br>{config['address']}",
            max_width=300,
        ),
        tooltip=config["name"],
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
    ).add_to(m)

    # ── Radius rings ──────────────────────────────────────────────────────
    for radius in config["analysis"]["radii"]:
        _make_circle(lat, lon, radius, f"{radius}-mile radius").add_to(m)
        # Label the ring
        label_lat = lat + (radius * METERS_PER_MILE / 111320)
        folium.Marker(
            location=[label_lat, lon],
            icon=folium.DivIcon(
                html=f'<div style="font-size:11px;color:{COLORS["primary"]};font-weight:600;white-space:nowrap;">{radius} mi</div>',
                icon_size=(50, 20),
                icon_anchor=(25, 10),
            ),
        ).add_to(m)

    # ── Tract choropleth (colored by median income) ───────────────────────
    # Get tracts in the 5-mile ring for the choropleth
    ring_5mi = geographies["rings"].get(5, pd.DataFrame())
    if not ring_5mi.empty:
        geoids = ring_5mi["geoid"].tolist()
        if geoids:
            placeholders = ",".join(f"'{g}'" for g in geoids)
            tracts_gdf = _gs().read_postgis(
                f"SELECT geoid, name, geometry FROM census_tracts WHERE geoid IN ({placeholders})",
                engine,
            )

            # Get latest year income data for coloring
            if scorecard:
                ts_5mi = scorecard.get("5mi", {}).get("time_series", pd.DataFrame())
            else:
                ts_5mi = pd.DataFrame()

            # Get per-tract income for the latest year
            from submarket_atlas.demographics import load_cached_data

            latest_year = config["analysis"]["years"][-1]
            tract_data = load_cached_data(geoids, [latest_year], engine)

            if not tract_data.empty and "B19013_001E" in tract_data.columns:
                income_map = tract_data.set_index("geoid")["B19013_001E"]
                tracts_gdf = tracts_gdf.merge(
                    income_map.rename("median_hhi"), left_on="geoid", right_index=True, how="left"
                )

                # Create choropleth
                choropleth = folium.Choropleth(
                    geo_data=tracts_gdf.to_json(),
                    data=tracts_gdf,
                    columns=["geoid", "median_hhi"],
                    key_on="feature.properties.geoid",
                    fill_color="Blues",
                    fill_opacity=0.4,
                    line_opacity=0.3,
                    line_weight=0.5,
                    line_color="white",
                    legend_name="Median Household Income ($)",
                    name="Income Choropleth",
                )
                choropleth.add_to(m)

                # Add popups to each tract
                style_function = lambda x: {
                    "fillOpacity": 0.3,
                    "weight": 0.5,
                    "color": "white",
                }
                highlight_function = lambda x: {
                    "fillOpacity": 0.6,
                    "weight": 2,
                    "color": COLORS["primary"],
                }

                tooltip = folium.GeoJsonTooltip(
                    fields=["geoid", "name", "median_hhi"],
                    aliases=["Tract:", "Name:", "Median HHI:"],
                    localize=True,
                )

                folium.GeoJson(
                    tracts_gdf.to_json(),
                    style_function=style_function,
                    highlight_function=highlight_function,
                    tooltip=tooltip,
                    name="Tract Details",
                ).add_to(m)

    # ── Peer submarket markers ────────────────────────────────────────────
    for slug, peer_config in config["analysis"]["peer_submarkets"].items():
        folium.Marker(
            location=[peer_config["center_lat"], peer_config["center_lon"]],
            popup=f"<b>{peer_config['label']}</b><br>{peer_config['description']}",
            tooltip=peer_config["label"],
            icon=folium.Icon(color="blue", icon="building", prefix="fa"),
        ).add_to(m)

    # ── Layer control ─────────────────────────────────────────────────────
    folium.LayerControl().add_to(m)

    # ── Save ──────────────────────────────────────────────────────────────
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        map_path = output_dir / f"{config['slug']}-map.html"
        m.save(str(map_path))
        return map_path

    return m


def generate_static_map_image(config: dict, output_dir: Path) -> Path | None:
    """Generate a simple static map context image for the cover page.

    Uses a basic Folium map saved as HTML (screenshot would need Selenium).
    For the report, we embed the interactive HTML or reference it.
    """
    # For now, return None — the HTML report will embed the interactive map
    return None


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    import argparse
    from submarket_atlas.config import load_property
    from submarket_atlas.spatial import build_all_geographies

    parser = argparse.ArgumentParser(description="Generate interactive map")
    parser.add_argument("--property", required=True, help="Property slug")
    args = parser.parse_args()

    config = load_property(args.property)
    engine = _gs().get_engine()
    geographies = build_all_geographies(config, engine)

    output_dir = Path(__file__).resolve().parent.parent.parent / "output" / config["slug"]
    path = generate_map(config, geographies, output_dir=output_dir)
    print(f"Map saved to: {path}")


if __name__ == "__main__":
    main()
