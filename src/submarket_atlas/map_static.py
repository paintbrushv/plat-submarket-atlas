"""Print-quality static map + infographic generation.

Generates broker-style radius ring maps and demographic infographic
tables alongside the existing Folium interactive map (map.py).

Requires: pip install 'geostack[print-maps]'
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from rich.console import Console

console = Console()


def generate_static_maps(
    config: dict,
    geographies: dict,
    scorecard: dict,
    output_dir: Path,
) -> list[Path]:
    """Generate print-quality static maps and infographic for a property.

    Called from report.py after the Folium map step. Produces:
      - {slug}-map-static.png (radius ring choropleth, 300 dpi)
      - {slug}-infographic.png (demographic table, 300 dpi)

    Args:
        config: Property config dict (coordinates, radii, name, slug, years).
        geographies: Dict with "rings" → {radius: DataFrame with geoid, area_weight}.
        scorecard: Dict with per-geography time series and growth metrics.
        output_dir: Path for output files.

    Returns:
        List of generated file paths.
    """
    try:
        from geostack.viz_static import (
            broker_radius_map,
            demographic_infographic,
            save_map,
            INFOGRAPHIC_VARIABLES,
        )
    except ImportError:
        console.print(
            "[yellow]Skipping static maps — geostack[print-maps] not installed[/yellow]"
        )
        return []

    from geostack.db import get_engine, read_postgis
    from submarket_atlas.demographics import load_cached_data

    engine = get_engine()
    lat = config["coordinates"]["lat"]
    lon = config["coordinates"]["lon"]
    radii = config["analysis"]["radii"]
    slug = config["slug"]
    latest_year = config["analysis"]["years"][-1]
    generated = []

    # --- Build tracts GeoDataFrame with income data ---
    # Use the largest ring's tracts for the choropleth background
    max_radius = max(radii)
    ring_df = geographies["rings"].get(max_radius, pd.DataFrame())

    if ring_df.empty:
        console.print("[yellow]No tract data for static map[/yellow]")
        return []

    geoids = ring_df["geoid"].tolist()
    placeholders = ",".join(f"'{g}'" for g in geoids)

    tracts_gdf = read_postgis(
        f"SELECT geoid, name, geometry FROM census_tracts WHERE geoid IN ({placeholders})",
        engine,
    )

    # Merge income data
    tract_data = load_cached_data(geoids, [latest_year], engine)
    if not tract_data.empty and "B19013_001E" in tract_data.columns:
        income_map = tract_data.set_index("geoid")["B19013_001E"]
        tracts_gdf = tracts_gdf.merge(
            income_map.rename("median_hhi"),
            left_on="geoid",
            right_index=True,
            how="left",
        )
    else:
        console.print("[yellow]No income data for static map choropleth[/yellow]")
        tracts_gdf["median_hhi"] = float("nan")

    # --- 1. Broker radius ring map ---
    try:
        console.print("[dim]Generating static radius map...[/dim]")
        fig, ax = broker_radius_map(
            tracts_gdf,
            center=(lon, lat),
            radii_miles=radii,
            column="median_hhi",
            property_name=config["name"],
            subtitle=f"Median Household Income by Census Tract (ACS {latest_year})",
            legend_title="Median HHI ($)",
        )
        path = save_map(fig, output_dir / f"{slug}-map-static.png", dpi=300)
        generated.append(path)

        import matplotlib.pyplot as plt
        plt.close(fig)
    except Exception as e:
        console.print(f"[yellow]Static map failed: {e}[/yellow]")

    # --- 2. Demographic infographic table ---
    try:
        console.print("[dim]Generating demographic infographic...[/dim]")

        # Build ring_data from scorecard time series (latest year)
        ring_data: dict[float, dict] = {}
        for radius in radii:
            geo_key = f"{radius}mi"
            ts = scorecard.get(geo_key, {}).get("time_series", pd.DataFrame())
            if not ts.empty:
                # Get latest year row, convert ACS human names to codes for infographic
                latest = ts.iloc[-1].to_dict()
                ring_data[radius] = latest

        if ring_data:
            fig, ax = demographic_infographic(
                ring_data,
                radii_miles=radii,
                property_name=config["name"],
                mode="radius",
            )
            path = save_map(fig, output_dir / f"{slug}-infographic.png", dpi=300)
            generated.append(path)

            import matplotlib.pyplot as plt
            plt.close(fig)
        else:
            console.print("[yellow]No scorecard data for infographic[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Infographic failed: {e}[/yellow]")

    return generated
