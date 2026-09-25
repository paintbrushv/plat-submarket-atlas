"""Metrics computation engine — derived analytics from raw ACS data."""

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from geostack.db import get_engine
from submarket_atlas.demographics import load_cached_data, ALL_VARIABLES


def cagr(start_val, end_val, years: int) -> float | None:
    """Compound annual growth rate."""
    if start_val is None or end_val is None or years <= 0:
        return None
    if start_val <= 0 or end_val <= 0:
        return None
    return (end_val / start_val) ** (1 / years) - 1


def trend_direction(cagr_val: float | None, threshold: float = 0.005) -> str:
    """Return directional indicator: improving/stable/declining."""
    if cagr_val is None:
        return "N/A"
    if cagr_val > threshold:
        return "improving"
    elif cagr_val < -threshold:
        return "declining"
    return "stable"


def trend_arrow(cagr_val: float | None, threshold: float = 0.005) -> str:
    """Return trend arrow for tables."""
    if cagr_val is None:
        return "—"
    if cagr_val > threshold:
        return "▲"
    elif cagr_val < -threshold:
        return "▼"
    return "►"


def aggregate_tracts(
    tract_data: pd.DataFrame,
    weights: pd.Series | None = None,
) -> pd.Series:
    """Population-weighted aggregation of tract-level data.

    For median-type variables (median_hhi, median_gross_rent, etc.), use
    population-weighted average as an approximation. For count variables, sum.
    """
    if tract_data.empty:
        return pd.Series(dtype=float)

    # Identify median vs count variables
    median_vars = {
        "B01002_001E",  # median age
        "B19013_001E",  # median HHI
        "B19301_001E",  # per capita income
        "B25064_001E",  # median gross rent
        "B25077_001E",  # median home value
        "B25071_001E",  # median rent % income
    }

    result = {}
    pop_col = "B01003_001E"

    if weights is None and pop_col in tract_data.columns:
        weights = tract_data[pop_col].fillna(0)
    elif weights is None:
        weights = pd.Series(1, index=tract_data.index)

    total_weight = weights.sum()
    if total_weight == 0:
        total_weight = 1

    for col in tract_data.columns:
        if col in ("geoid", "year"):
            continue
        vals = tract_data[col].copy()
        # Census API uses large negative sentinels for suppressed/unavailable data
        vals = vals.where(vals > -999999, other=np.nan)
        if col in median_vars:
            # Population-weighted average for medians (exclude NaN tracts)
            valid = vals.notna()
            if valid.any():
                w = weights[valid]
                v = vals[valid]
                tw = w.sum()
                result[col] = (v * w).sum() / tw if tw > 0 else np.nan
            else:
                result[col] = np.nan
        else:
            # Sum for count variables
            result[col] = vals.fillna(0).sum()

    return pd.Series(result)


def compute_derived_metrics(agg: pd.Series) -> dict:
    """Compute all derived metrics from aggregated ACS variables."""
    m = {}

    pop = agg.get("B01003_001E", 0)
    total_units = agg.get("B25001_001E", 0)
    occupied = agg.get("B25002_002E", 0)
    vacant = agg.get("B25002_003E", 0)
    owner_occ = agg.get("B25003_002E", 0)
    renter_occ = agg.get("B25003_003E", 0)

    # Prime renter cohort (age 20-34)
    prime_renter = (
        agg.get("B01001_009E", 0)
        + agg.get("B01001_010E", 0)
        + agg.get("B01001_011E", 0)
        + agg.get("B01001_033E", 0)
        + agg.get("B01001_034E", 0)
        + agg.get("B01001_035E", 0)
    )

    # MF units (5+ units in structure)
    mf_units = (
        agg.get("B25024_007E", 0)
        + agg.get("B25024_008E", 0)
        + agg.get("B25024_009E", 0)
    )

    # Rent burden (30%+ of income)
    rent_burdened = (
        agg.get("B25070_007E", 0)
        + agg.get("B25070_008E", 0)
        + agg.get("B25070_009E", 0)
        + agg.get("B25070_010E", 0)
    )

    # Education (bachelor's+)
    bachelors_plus = (
        agg.get("B15003_022E", 0)
        + agg.get("B15003_023E", 0)
        + agg.get("B15003_024E", 0)
        + agg.get("B15003_025E", 0)
    )
    edu_total = agg.get("B15003_001E", 0)

    median_rent = agg.get("B25064_001E")
    median_hhi = agg.get("B19013_001E")

    # Pass through all raw aggregated values for chart use
    for key, val in agg.items():
        if key not in ("geoid", "year"):
            m[key] = val

    m["population"] = pop
    m["median_age"] = agg.get("B01002_001E")
    m["median_hhi"] = median_hhi
    m["per_capita_income"] = agg.get("B19301_001E")
    m["median_rent"] = median_rent
    m["median_home_value"] = agg.get("B25077_001E")
    m["total_housing_units"] = total_units
    m["occupied_units"] = occupied
    m["vacant_units"] = vacant
    m["owner_occupied"] = owner_occ
    m["renter_occupied"] = renter_occ
    m["prime_renter_pop"] = prime_renter
    m["mf_units"] = mf_units

    # Derived ratios
    m["rent_to_income"] = (
        (median_rent * 12) / median_hhi if median_rent and median_hhi and median_hhi > 0 else None
    )
    m["renter_propensity"] = renter_occ / occupied if occupied > 0 else None
    m["prime_renter_share"] = prime_renter / pop if pop > 0 else None
    m["mf_density"] = mf_units / total_units if total_units > 0 else None
    m["vacancy_proxy"] = vacant / total_units if total_units > 0 else None
    m["homeownership_rate"] = owner_occ / occupied if occupied > 0 else None
    m["in_migration_rate"] = (
        agg.get("B07001_065E", 0) / pop if pop > 0 else None
    )
    m["bachelors_plus_share"] = bachelors_plus / edu_total if edu_total > 0 else None
    m["units_per_capita"] = total_units / pop if pop > 0 else None
    m["rent_burden_rate"] = rent_burdened / renter_occ if renter_occ > 0 else None
    m["employment_rate"] = (
        1 - agg.get("B23025_005E", 0) / agg.get("B23025_003E", 1)
        if agg.get("B23025_003E", 0) > 0
        else None
    )
    m["wfh_rate"] = (
        agg.get("B08301_021E", 0) / agg.get("B08301_001E", 1)
        if agg.get("B08301_001E", 0) > 0
        else None
    )

    return m


def compute_time_series(
    geoid_list: list[str],
    years: list[int],
    area_weights: pd.Series | None = None,
    engine=None,
) -> pd.DataFrame:
    """Compute derived metrics for a geography across all years.

    Returns DataFrame with year as index and derived metrics as columns.
    """
    engine = engine or get_engine()
    raw = load_cached_data(geoid_list, years, engine)

    if raw.empty:
        return pd.DataFrame()

    results = []
    for year in sorted(years):
        year_data = raw[raw["year"] == year].copy()
        if year_data.empty:
            continue

        # If area_weights provided, multiply population by weight
        if area_weights is not None:
            year_data = year_data.merge(
                area_weights.rename("_area_weight"), left_on="geoid", right_index=True, how="left"
            )
            year_data["_area_weight"] = year_data["_area_weight"].fillna(1.0)
            pop_col = "B01003_001E"
            if pop_col in year_data.columns:
                weights = year_data[pop_col].fillna(0) * year_data["_area_weight"]
            else:
                weights = year_data["_area_weight"]
            year_data = year_data.drop(columns=["_area_weight"])
        else:
            weights = None

        agg = aggregate_tracts(
            year_data.drop(columns=["year"], errors="ignore"),
            weights=weights,
        )
        metrics = compute_derived_metrics(agg)
        metrics["year"] = year
        results.append(metrics)

    return pd.DataFrame(results).set_index("year") if results else pd.DataFrame()


def compute_growth_metrics(ts: pd.DataFrame) -> dict:
    """Compute CAGRs and growth metrics from a time series DataFrame."""
    if ts.empty or len(ts) < 2:
        return {}

    latest_year = ts.index.max()
    earliest_year = ts.index.min()

    growth = {}
    for metric in ["population", "median_hhi", "median_rent", "total_housing_units"]:
        if metric not in ts.columns:
            continue

        latest = ts.loc[latest_year, metric]
        earliest = ts.loc[earliest_year, metric]

        years_span = latest_year - earliest_year
        growth[f"{metric}_cagr_{years_span}yr"] = cagr(earliest, latest, years_span)

        # 5-year CAGR
        y5 = latest_year - 5
        if y5 in ts.index:
            growth[f"{metric}_cagr_5yr"] = cagr(ts.loc[y5, metric], latest, 5)

        # 3-year CAGR
        y3 = latest_year - 3
        if y3 in ts.index:
            growth[f"{metric}_cagr_3yr"] = cagr(ts.loc[y3, metric], latest, 3)

    return growth


def build_scorecard(
    geographies: dict,
    config: dict,
    engine=None,
) -> dict:
    """Build the full metrics scorecard for all geographies.

    Returns nested dict: {geography_name: {year: {metric: value}, growth: {...}}}
    """
    engine = engine or get_engine()
    years = config["analysis"]["years"]
    scorecard = {}

    # Property tract
    prop_tract = geographies["property_tract"]
    ts = compute_time_series([prop_tract], years, engine=engine)
    scorecard["property_tract"] = {
        "label": "Property Tract",
        "time_series": ts,
        "growth": compute_growth_metrics(ts),
    }

    # Radius rings
    for radius, ring_df in geographies["rings"].items():
        geoids = ring_df["geoid"].tolist()
        # Use area weights for population-weighted aggregation
        area_weights = ring_df.set_index("geoid")["area_weight"]
        ts = compute_time_series(geoids, years, area_weights=area_weights, engine=engine)
        scorecard[f"{radius}mi"] = {
            "label": f"{radius}-Mile Ring",
            "time_series": ts,
            "growth": compute_growth_metrics(ts),
        }

    # Peer submarkets
    for slug, peer in geographies["peers"].items():
        ts = compute_time_series(peer["tracts"], years, engine=engine)
        scorecard[slug] = {
            "label": peer["label"],
            "time_series": ts,
            "growth": compute_growth_metrics(ts),
        }

    # MSA — uses property's CBSA code; label comes from property config
    cbsa_code = config["cbsa_code"]
    msa_label = config["msa_label"]
    ts = compute_time_series([f"MSA_{cbsa_code}"], years, engine=engine)
    scorecard["msa"] = {
        "label": msa_label,
        "time_series": ts,
        "growth": compute_growth_metrics(ts),
    }

    return scorecard
