"""Demographics data pipeline — pull ACS 5-year estimates and cache in PostGIS."""

import os
import sys
import time
import logging

import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv()

# geostack is a documented prerequisite (see submarket_atlas._deps); its
# import is deferred to call time so this module stays importable (and its
# constants/metadata usable) without it.
from submarket_atlas._deps import require_geostack


def _gs():
    """Call-time geostack.db accessor (typed prerequisite guard)."""
    require_geostack()
    from geostack import db

    return db


logger = logging.getLogger(__name__)

CENSUS_BASE = "https://api.census.gov/data"

# ── ACS Variable Groups ──────────────────────────────────────────────────────
# Organized by analytical theme, matching the build prompt spec.

POPULATION_VARS = {
    "B01003_001E": "total_population",
    "B01002_001E": "median_age",
}

# Age/sex breakdown for prime renter cohort (20-34)
# B01001: Male 20-24 (_009E), 25-29 (_010E), 30-34 (_011E)
#         Female 20-24 (_033E), 25-29 (_034E), 30-34 (_035E)
AGE_VARS = {
    "B01001_001E": "pop_total_sex",
    "B01001_009E": "male_20_24",
    "B01001_010E": "male_25_29",
    "B01001_011E": "male_30_34",
    "B01001_033E": "female_20_24",
    "B01001_034E": "female_25_29",
    "B01001_035E": "female_30_34",
}

INCOME_VARS = {
    "B19013_001E": "median_hhi",
    "B19301_001E": "per_capita_income",
    # Income distribution brackets
    "B19001_002E": "hhi_lt_10k",
    "B19001_003E": "hhi_10k_15k",
    "B19001_004E": "hhi_15k_20k",
    "B19001_005E": "hhi_20k_25k",
    "B19001_006E": "hhi_25k_30k",
    "B19001_007E": "hhi_30k_35k",
    "B19001_008E": "hhi_35k_40k",
    "B19001_009E": "hhi_40k_45k",
    "B19001_010E": "hhi_45k_50k",
    "B19001_011E": "hhi_50k_60k",
    "B19001_012E": "hhi_60k_75k",
    "B19001_013E": "hhi_75k_100k",
    "B19001_014E": "hhi_100k_125k",
    "B19001_015E": "hhi_125k_150k",
    "B19001_016E": "hhi_150k_200k",
    "B19001_017E": "hhi_200k_plus",
}

EMPLOYMENT_VARS = {
    "B23025_003E": "labor_force",
    "B23025_005E": "unemployed",
}

HOUSING_VARS = {
    "B25001_001E": "total_housing_units",
    "B25002_002E": "occupied_units",
    "B25002_003E": "vacant_units",
    "B25003_002E": "owner_occupied",
    "B25003_003E": "renter_occupied",
    # Units in structure
    "B25024_002E": "struct_1_detached",
    "B25024_005E": "struct_2",
    "B25024_006E": "struct_3_4",
    "B25024_007E": "struct_5_9",
    "B25024_008E": "struct_10_19",
    "B25024_009E": "struct_20_plus",
    "B25024_010E": "struct_mobile",
}

RENT_VARS = {
    "B25064_001E": "median_gross_rent",
    "B25077_001E": "median_home_value",
    "B25071_001E": "median_rent_pct_income",
    # Rent burden brackets (gross rent as % of HHI)
    "B25070_007E": "rent_burden_30_35",
    "B25070_008E": "rent_burden_35_40",
    "B25070_009E": "rent_burden_40_50",
    "B25070_010E": "rent_burden_50_plus",
}

MOBILITY_VARS = {
    "B07001_001E": "geo_mobility_total",
    "B07001_065E": "moved_from_diff_state",
}

COMMUTE_VARS = {
    "B08301_001E": "commute_total",
    "B08301_003E": "commute_drive_alone",
    "B08301_010E": "commute_transit",
    "B08301_021E": "commute_wfh",
}

EDUCATION_VARS = {
    "B15003_001E": "edu_total_25plus",
    "B15003_022E": "edu_bachelors",
    "B15003_023E": "edu_masters",
    "B15003_024E": "edu_professional",
    "B15003_025E": "edu_doctorate",
}

ALL_VARIABLES = {}
for group in [
    POPULATION_VARS,
    AGE_VARS,
    INCOME_VARS,
    EMPLOYMENT_VARS,
    HOUSING_VARS,
    RENT_VARS,
    MOBILITY_VARS,
    COMMUTE_VARS,
    EDUCATION_VARS,
]:
    ALL_VARIABLES.update(group)


def _fetch_acs_tract(
    variables: list[str],
    state_fips: str,
    county_fips: str,
    year: int,
    api_key: str,
) -> pd.DataFrame:
    """Fetch ACS 5-year tract-level data for one county/year."""
    var_str = ",".join(variables)
    url = f"{CENSUS_BASE}/{year}/acs/acs5"
    params = {
        "get": f"NAME,{var_str}",
        "for": "tract:*",
        "in": f"state:{state_fips} county:{county_fips}",
        "key": api_key,
    }

    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Server error {resp.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 3:
                raise
            wait = 2 ** (attempt + 1)
            logger.warning(f"Request failed: {e}, retrying in {wait}s...")
            time.sleep(wait)
    else:
        raise RuntimeError(f"Failed after 4 attempts: {url}")

    data = resp.json()
    if not data or len(data) < 2:
        return pd.DataFrame()

    df = pd.DataFrame(data[1:], columns=data[0])

    # Build GEOID
    df["geoid"] = df["state"] + df["county"] + df["tract"]

    # Convert variable columns to numeric
    for v in variables:
        if v in df.columns:
            df[v] = pd.to_numeric(df[v], errors="coerce")

    return df[["geoid"] + [v for v in variables if v in df.columns]]


def _fetch_acs_msa(
    variables: list[str],
    year: int,
    api_key: str,
    msa_code: str,
) -> pd.DataFrame:
    """Fetch ACS 5-year MSA-level data for the given CBSA code."""
    var_str = ",".join(variables)
    url = f"{CENSUS_BASE}/{year}/acs/acs5"
    params = {
        "get": f"NAME,{var_str}",
        "for": "metropolitan statistical area/micropolitan statistical area:" + msa_code,
        "key": api_key,
    }

    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if resp.status_code >= 500:
                time.sleep(2 ** (attempt + 1))
                continue
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    else:
        raise RuntimeError(f"Failed to fetch MSA data for year {year}")

    data = resp.json()
    if not data or len(data) < 2:
        return pd.DataFrame()

    df = pd.DataFrame(data[1:], columns=data[0])
    df["geoid"] = "MSA_" + msa_code

    for v in variables:
        if v in df.columns:
            df[v] = pd.to_numeric(df[v], errors="coerce")

    return df[["geoid"] + [v for v in variables if v in df.columns]]


def _store_to_db(df: pd.DataFrame, year: int, engine):
    """Store ACS data in acs_tract_data table (long format)."""
    variable_cols = [c for c in df.columns if c not in ("geoid",)]

    # Melt to long format
    long = df.melt(id_vars=["geoid"], value_vars=variable_cols, var_name="variable", value_name="value")
    long["year"] = year
    long = long.dropna(subset=["value"])

    if long.empty:
        return 0

    # Upsert using ON CONFLICT
    with engine.begin() as conn:
        for _, row in long.iterrows():
            conn.execute(
                text("""
                    INSERT INTO acs_tract_data (geoid, year, variable, value)
                    VALUES (:geoid, :year, :variable, :value)
                    ON CONFLICT (geoid, year, variable) DO UPDATE SET value = :value
                """),
                {
                    "geoid": row["geoid"],
                    "year": int(row["year"]),
                    "variable": row["variable"],
                    "value": float(row["value"]),
                },
            )
    return len(long)


def _store_batch_to_db(df: pd.DataFrame, year: int, engine):
    """Batch-store ACS data using executemany for performance."""
    variable_cols = [c for c in df.columns if c not in ("geoid",)]
    long = df.melt(id_vars=["geoid"], value_vars=variable_cols, var_name="variable", value_name="value")
    long["year"] = year
    long = long.dropna(subset=["value"])

    if long.empty:
        return 0

    records = [
        {"geoid": r.geoid, "year": int(r.year), "variable": r.variable, "value": float(r.value)}
        for r in long.itertuples()
    ]

    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO acs_tract_data (geoid, year, variable, value)
                VALUES (:geoid, :year, :variable, :value)
                ON CONFLICT (geoid, year, variable) DO UPDATE SET value = EXCLUDED.value
            """),
            records,
        )
    return len(records)


def check_cached(geoids: list[str], year: int, engine) -> bool:
    """Check if we already have data cached for these tracts/year."""
    if not geoids:
        return False
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(DISTINCT geoid) FROM acs_tract_data WHERE year = :year AND geoid = ANY(:geoids)"),
            {"year": year, "geoids": geoids},
        ).scalar()
    return result >= len(geoids) * 0.8  # 80% coverage = cached enough


def pull_demographics(
    config: dict,
    geographies: dict,
    force_refresh: bool = False,
) -> None:
    """Pull all ACS data for the configured property and cache in PostGIS.

    This is the main entry point for the demographics pipeline.
    """
    engine = _gs().get_engine()
    api_key = os.environ.get("CENSUS_API_KEY", "")
    years = config["analysis"]["years"]
    state_fips = config["state_fips"]

    # Collect all unique county FIPS we need data for
    all_counties = set(config["analysis"]["msa_counties"])

    # Also add counties from radius rings
    for radius, ring_df in geographies["rings"].items():
        all_counties.update(ring_df["county_fips"].unique())

    all_variables = list(ALL_VARIABLES.keys())

    # Census API limits to 50 variables per call — split into chunks
    chunk_size = 48  # leave room for NAME + geo fields
    var_chunks = [all_variables[i : i + chunk_size] for i in range(0, len(all_variables), chunk_size)]

    total_calls = len(years) * len(all_counties) * len(var_chunks) + len(years)  # +MSA calls
    call_count = 0

    for year in years:
        logger.info(f"Pulling ACS {year} data...")

        # ── Tract-level data by county ──
        for county in sorted(all_counties):
            for chunk_idx, var_chunk in enumerate(var_chunks):
                call_count += 1

                # Check cache
                if not force_refresh:
                    with engine.connect() as conn:
                        cached = conn.execute(
                            text("""
                                SELECT COUNT(*) FROM acs_tract_data
                                WHERE year = :year
                                  AND variable = ANY(:vars)
                                  AND geoid LIKE :county_pattern
                            """),
                            {
                                "year": year,
                                "vars": var_chunk[:3],  # spot-check a few
                                "county_pattern": f"{state_fips}{county}%",
                            },
                        ).scalar()
                    if cached > 0:
                        print(f"  [{call_count}/{total_calls}] {year} county {county} chunk {chunk_idx+1} — cached, skipping")
                        continue

                print(f"  [{call_count}/{total_calls}] {year} county {county} chunk {chunk_idx+1}/{len(var_chunks)}...")

                try:
                    df = _fetch_acs_tract(var_chunk, state_fips, county, year, api_key)
                    if not df.empty:
                        rows = _store_batch_to_db(df, year, engine)
                        print(f"    → {rows} values stored")
                    else:
                        print(f"    → no data returned")
                except Exception as e:
                    logger.error(f"Failed: {year} county {county}: {e}")
                    print(f"    → ERROR: {e}")

                time.sleep(0.5)  # rate limiting

        # ── MSA-level data ──
        call_count += 1
        cbsa_code = config["cbsa_code"]
        msa_label = config["msa_label"]
        msa_centroid = config["msa_centroid"]
        msa_geoid = f"MSA_{cbsa_code}"
        print(f"  [{call_count}/{total_calls}] {year} {msa_label} (CBSA {cbsa_code})...")

        # MSA data needs to be fetched in one go (fewer variables issue less likely)
        try:
            # Check cache for this specific MSA
            if not force_refresh:
                with engine.connect() as conn:
                    msa_cached = conn.execute(
                        text("SELECT COUNT(*) FROM acs_tract_data WHERE year = :year AND geoid = :geoid"),
                        {"year": year, "geoid": msa_geoid},
                    ).scalar()
                if msa_cached > 0:
                    print(f"    → cached, skipping")
                    continue

            for var_chunk in var_chunks:
                msa_df = _fetch_acs_msa(var_chunk, year, api_key, msa_code=cbsa_code)
                if not msa_df.empty:
                    # Store MSA data — need to handle the foreign key constraint
                    # MSA geoid won't be in census_tracts, so we store separately
                    _store_msa_data(msa_df, year, engine, cbsa_code, msa_label, msa_centroid, state_fips)
                time.sleep(0.5)
            print(f"    → MSA data stored")
        except Exception as e:
            logger.error(f"Failed MSA {year}: {e}")
            print(f"    → MSA ERROR: {e}")

    print(f"\nDemographics pull complete. {call_count} API calls made.")


def _ensure_msa_tract_row(engine, cbsa_code: str, msa_label: str, msa_centroid: dict, state_fips: str):
    """Ensure a dummy census_tracts row exists for the given MSA's data.

    The row's geoid is `MSA_<cbsa_code>` and the geometry is a tiny polygon
    centered on the MSA centroid (sufficient to satisfy the MultiPolygon FK
    constraint; not used for spatial analysis).
    """
    geoid = f"MSA_{cbsa_code}"
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM census_tracts WHERE geoid = :geoid LIMIT 1"),
            {"geoid": geoid},
        ).fetchone()
        if not exists:
            # Create a tiny polygon (not a point) to satisfy the MultiPolygon geometry type
            conn.execute(
                text("""
                    INSERT INTO census_tracts (geoid, state_fips, county_fips, name, geometry)
                    VALUES (:geoid, :state_fips, '000', :name,
                            ST_Multi(ST_Buffer(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 100)::geometry))
                """),
                {
                    "geoid": geoid,
                    "state_fips": state_fips,
                    "name": msa_label,
                    "lon": msa_centroid["lon"],
                    "lat": msa_centroid["lat"],
                },
            )


def _store_msa_data(df: pd.DataFrame, year: int, engine, cbsa_code: str, msa_label: str, msa_centroid: dict, state_fips: str):
    """Store MSA-level data, handling the FK constraint."""
    _ensure_msa_tract_row(engine, cbsa_code, msa_label, msa_centroid, state_fips)
    _store_batch_to_db(df, year, engine)


def load_cached_data(geoids: list[str], years: list[int] = None, engine=None) -> pd.DataFrame:
    """Load cached ACS data from PostGIS for given tracts and years.

    Returns wide-format DataFrame with geoid, year, and one column per variable.
    """
    engine = engine or _gs().get_engine()

    conditions = ["geoid = ANY(:geoids)"]
    params = {"geoids": geoids}
    if years:
        conditions.append("year = ANY(:years)")
        params["years"] = years

    where = " AND ".join(conditions)

    with engine.connect() as conn:
        long_df = pd.read_sql(
            text(f"SELECT geoid, year, variable, value FROM acs_tract_data WHERE {where}"),
            conn,
            params=params,
        )

    if long_df.empty:
        return pd.DataFrame()

    # Pivot to wide format
    wide = long_df.pivot_table(index=["geoid", "year"], columns="variable", values="value").reset_index()
    wide.columns.name = None
    return wide


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Pull ACS demographics data")
    parser.add_argument("--property", required=True, help="Property slug")
    parser.add_argument("--force", action="store_true", help="Force refresh (ignore cache)")
    args = parser.parse_args()

    from submarket_atlas.config import load_property
    from submarket_atlas.spatial import build_all_geographies

    config = load_property(args.property)
    print(f"Pulling demographics for: {config['name']}")

    engine = _gs().get_engine()
    geographies = build_all_geographies(config, engine)

    print(f"Property tract: {geographies['property_tract']}")
    for r, df in geographies["rings"].items():
        print(f"  {r}-mile ring: {len(df)} tracts")
    for slug, peer in geographies["peers"].items():
        print(f"  Peer '{peer['label']}': {len(peer['tracts'])} tracts")

    pull_demographics(config, geographies, force_refresh=args.force)


if __name__ == "__main__":
    main()
