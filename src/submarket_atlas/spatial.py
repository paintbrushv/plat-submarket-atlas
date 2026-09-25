"""Spatial analysis — identify tracts in radius rings and peer submarkets."""

import os

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from dotenv import load_dotenv

load_dotenv()

from geostack.db import get_engine, read_postgis, read_sql


METERS_PER_MILE = 1609.344


def get_property_tract(lon: float, lat: float, engine=None) -> str:
    """Find the census tract GEOID containing a point."""
    engine = engine or get_engine()
    result = read_sql(
        """
        SELECT geoid FROM census_tracts
        WHERE ST_Contains(geometry, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
        LIMIT 1
        """,
        engine,
        params={"lon": lon, "lat": lat},
    )
    # read_sql doesn't support %s params — use text() approach
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT geoid FROM census_tracts "
                "WHERE ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
                "LIMIT 1"
            ),
            {"lon": lon, "lat": lat},
        ).fetchone()
    if row is None:
        raise ValueError(f"No census tract found containing ({lat}, {lon})")
    return row[0]


def tracts_in_radius(
    lon: float, lat: float, radius_miles: float, engine=None
) -> pd.DataFrame:
    """Find all census tracts whose centroids fall within a radius.

    Returns DataFrame with geoid, name, county_fips, distance_miles,
    and area_weight (fraction of tract area inside the ring).
    """
    engine = engine or get_engine()
    radius_m = radius_miles * METERS_PER_MILE

    from sqlalchemy import text

    sql = text("""
        WITH prop AS (
            SELECT ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography AS geog
        )
        SELECT
            t.geoid,
            t.name,
            t.county_fips,
            ST_Distance(ST_Centroid(t.geometry)::geography, p.geog) / 1609.344 AS distance_miles,
            -- Area weight: fraction of tract geometry inside the buffer
            CASE
                WHEN ST_Within(t.geometry, ST_Buffer(p.geog, :radius_m)::geometry)
                THEN 1.0
                ELSE ST_Area(
                    ST_Intersection(t.geometry::geography, ST_Buffer(p.geog, :radius_m))
                ) / NULLIF(ST_Area(t.geometry::geography), 0)
            END AS area_weight
        FROM census_tracts t, prop p
        WHERE ST_DWithin(
            ST_Centroid(t.geometry)::geography,
            p.geog,
            :radius_m
        )
        ORDER BY distance_miles
    """)

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"lon": lon, "lat": lat, "radius_m": radius_m})

    return df


def tracts_for_peer_submarket(
    center_lon: float, center_lat: float, radius_miles: float, engine=None
) -> list[str]:
    """Get tract GEOIDs for a peer submarket defined by center + radius."""
    df = tracts_in_radius(center_lon, center_lat, radius_miles, engine)
    return df["geoid"].tolist()


def build_all_geographies(config: dict, engine=None) -> dict:
    """Build tract lists for all analysis geographies.

    Returns dict with keys:
        property_tract: str (single GEOID)
        rings: {1: DataFrame, 3: DataFrame, 5: DataFrame}
        peers: {slug: {label, description, tracts: [GEOIDs]}}
        msa_counties: [county FIPS codes]
    """
    engine = engine or get_engine()
    lon = config["coordinates"]["lon"]
    lat = config["coordinates"]["lat"]

    # Property tract
    prop_tract = config.get("property_tract") or get_property_tract(lon, lat, engine)

    # Radius rings
    rings = {}
    for r in config["analysis"]["radii"]:
        rings[r] = tracts_in_radius(lon, lat, r, engine)

    # Peer submarkets
    peers = {}
    for slug, peer in config["analysis"]["peer_submarkets"].items():
        tracts = tracts_for_peer_submarket(
            peer["center_lon"], peer["center_lat"], peer["radius_miles"], engine
        )
        peers[slug] = {
            "label": peer["label"],
            "description": peer["description"],
            "tracts": tracts,
        }

    return {
        "property_tract": prop_tract,
        "rings": rings,
        "peers": peers,
        "msa_counties": config["analysis"]["msa_counties"],
    }


def get_tract_geometries(geoids: list[str], engine=None) -> gpd.GeoDataFrame:
    """Load tract geometries for a list of GEOIDs."""
    engine = engine or get_engine()
    if not geoids:
        return gpd.GeoDataFrame()
    placeholders = ",".join(f"'{g}'" for g in geoids)
    return read_postgis(
        f"SELECT geoid, name, county_fips, geometry FROM census_tracts WHERE geoid IN ({placeholders})",
        engine,
    )
