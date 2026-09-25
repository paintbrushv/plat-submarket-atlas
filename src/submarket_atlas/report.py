"""Report generation — orchestrates the full pipeline."""

import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

load_dotenv()

# geostack is a documented prerequisite (see submarket_atlas._deps); its
# import is deferred to call time so this module (and the report template
# machinery) stays importable without it.
from submarket_atlas._deps import require_geostack
from submarket_atlas.config import load_property, list_properties
from submarket_atlas.spatial import build_all_geographies
from submarket_atlas.demographics import pull_demographics, load_cached_data
from submarket_atlas.metrics import build_scorecard, cagr, trend_arrow
from submarket_atlas.charts import generate_all_charts
from submarket_atlas.map import generate_map
from submarket_atlas.narrative import (
    generate_executive_summary,
    generate_section_takeaways,
    fmt_pct,
    fmt_dollar,
    fmt_number,
    fmt_cagr,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Report template ships as package data (submarket_atlas/templates/).
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _build_snapshot_table(scorecard: dict, config: dict) -> tuple:
    """Build the demographic snapshot table for the latest year."""
    msa_label = config["msa_label"]
    geos = [
        ("property_tract", "Property Tract"),
        ("1mi", "1-Mile"),
        ("3mi", "3-Mile"),
        ("5mi", "5-Mile"),
        ("msa", msa_label),
    ]

    geo_labels = [{"key": k, "label": l} for k, l in geos]

    metrics = [
        ("Population", "population", fmt_number),
        ("Median Age", "median_age", lambda v: f"{v:.1f}" if v and not (isinstance(v, float) and (v != v)) else "—"),
        ("Median HHI", "median_hhi", fmt_dollar),
        ("Per Capita Income", "per_capita_income", fmt_dollar),
        ("Median Rent", "median_rent", fmt_dollar),
        ("Median Home Value", "median_home_value", fmt_dollar),
        ("Total Housing Units", "total_housing_units", fmt_number),
        ("Renter Propensity", "renter_propensity", fmt_pct),
        ("Homeownership Rate", "homeownership_rate", fmt_pct),
        ("Prime Renter Share", "prime_renter_share", fmt_pct),
        ("MF Density", "mf_density", fmt_pct),
        ("Vacancy Proxy", "vacancy_proxy", fmt_pct),
        ("Rent-to-Income", "rent_to_income", fmt_pct),
        ("Rent Burden Rate", "rent_burden_rate", fmt_pct),
        ("In-Migration Rate", "in_migration_rate", fmt_pct),
        ("Bachelor's+ Share", "bachelors_plus_share", fmt_pct),
        ("Employment Rate", "employment_rate", fmt_pct),
        ("Units per Capita", "units_per_capita", lambda v: f"{v:.3f}" if v and not (isinstance(v, float) and (v != v)) else "—"),
    ]

    rows = []
    for metric_label, metric_key, fmt_func in metrics:
        values = []
        for geo_key, _ in geos:
            ts = scorecard.get(geo_key, {}).get("time_series", pd.DataFrame())
            if ts.empty:
                values.append("—")
            else:
                val = ts.iloc[-1].get(metric_key)
                values.append(fmt_func(val))
        rows.append({"metric": metric_label, "values": values})

    return rows, geo_labels


def _build_growth_table(scorecard: dict, config: dict) -> tuple:
    """Build the growth summary table with CAGRs."""
    msa_label = config["msa_label"]
    geos = [
        ("property_tract", "Property Tract"),
        ("3mi", "3-Mile"),
        ("5mi", "5-Mile"),
        ("msa", msa_label),
    ]
    geo_labels = [{"key": k, "label": l} for k, l in geos]

    growth_metrics = [
        "population",
        "median_hhi",
        "median_rent",
        "total_housing_units",
    ]
    labels = {
        "population": "Population",
        "median_hhi": "Median HHI",
        "median_rent": "Median Rent",
        "total_housing_units": "Housing Units",
    }
    periods = ["3yr", "5yr"]

    rows = []
    for metric in growth_metrics:
        for period in periods:
            key = f"{metric}_cagr_{period}"
            values = []
            for geo_key, _ in geos:
                growth = scorecard.get(geo_key, {}).get("growth", {})
                val = growth.get(key)
                arrow = trend_arrow(val)
                if val is not None:
                    cls = "trend-up" if val > 0.005 else ("trend-down" if val < -0.005 else "trend-flat")
                    values.append({"text": f"{arrow} {fmt_cagr(val)}", "cls": cls})
                else:
                    values.append({"text": "—", "cls": ""})
            rows.append({"metric": f"{labels[metric]} ({period} CAGR)", "values": values})

    return rows, geo_labels


def _build_peer_table(scorecard: dict, config: dict) -> tuple:
    """Build the peer comparison table."""
    msa_label = config["msa_label"]
    property_short = config["name"].split("&")[0].split("(")[0].strip()
    geos = [("3mi", f"{property_short} 3mi")]
    for slug, peer in config["analysis"].get("peer_submarkets", {}).items():
        geos.append((slug, peer["label"]))
    geos.append(("msa", msa_label))
    geo_labels = [{"key": k, "label": l} for k, l in geos]

    metrics = [
        ("Population", "population", fmt_number),
        ("Median HHI", "median_hhi", fmt_dollar),
        ("Median Rent", "median_rent", fmt_dollar),
        ("Renter Propensity", "renter_propensity", fmt_pct),
        ("Prime Renter Share", "prime_renter_share", fmt_pct),
        ("MF Density", "mf_density", fmt_pct),
        ("Rent-to-Income", "rent_to_income", fmt_pct),
        ("Bachelor's+", "bachelors_plus_share", fmt_pct),
        ("Vacancy Proxy", "vacancy_proxy", fmt_pct),
    ]

    rows = []
    for metric_label, metric_key, fmt_func in metrics:
        values = []
        for geo_key, _ in geos:
            ts = scorecard.get(geo_key, {}).get("time_series", pd.DataFrame())
            if ts.empty:
                values.append("—")
            else:
                val = ts.iloc[-1].get(metric_key)
                values.append(fmt_func(val))
        rows.append({"metric": metric_label, "values": values})

    return rows, geo_labels


def _export_data(scorecard: dict, geographies: dict, config: dict, output_dir: Path):
    """Export data CSVs for verification."""
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Demographic snapshot
    snapshot_rows, geos = _build_snapshot_table(scorecard, config)
    snapshot_df = pd.DataFrame(
        [{r["metric"]: v for v in r["values"]} for r in snapshot_rows]
    )
    # Better approach: structured CSV
    rows_for_csv = []
    for row in snapshot_rows:
        d = {"metric": row["metric"]}
        for i, geo in enumerate(geos):
            d[geo["label"]] = row["values"][i]
        rows_for_csv.append(d)
    pd.DataFrame(rows_for_csv).to_csv(data_dir / "demographic-snapshot.csv", index=False)

    # Growth summary
    growth_rows, growth_geos = _build_growth_table(scorecard, config)
    rows_for_csv = []
    for row in growth_rows:
        d = {"metric": row["metric"]}
        for i, geo in enumerate(growth_geos):
            d[geo["label"]] = row["values"][i]["text"]
        rows_for_csv.append(d)
    pd.DataFrame(rows_for_csv).to_csv(data_dir / "growth-summary.csv", index=False)

    # Time series
    all_ts = []
    for geo_key, geo_data in scorecard.items():
        ts = geo_data.get("time_series", pd.DataFrame())
        if not ts.empty:
            ts_copy = ts.copy()
            ts_copy["geography"] = geo_data.get("label", geo_key)
            all_ts.append(ts_copy.reset_index())
    if all_ts:
        pd.concat(all_ts).to_csv(data_dir / "time-series-all-metrics.csv", index=False)

    # Tracts in radius
    ring_rows = []
    for radius, ring_df in geographies["rings"].items():
        for _, row in ring_df.iterrows():
            ring_rows.append({
                "radius_miles": radius,
                "geoid": row["geoid"],
                "name": row["name"],
                "county_fips": row["county_fips"],
                "distance_miles": row["distance_miles"],
                "area_weight": row["area_weight"],
            })
    pd.DataFrame(ring_rows).to_csv(data_dir / "tracts-in-radius.csv", index=False)

    # Peer comparison
    peer_rows, peer_geos = _build_peer_table(scorecard, config)
    rows_for_csv = []
    for row in peer_rows:
        d = {"metric": row["metric"]}
        for i, geo in enumerate(peer_geos):
            d[geo["label"]] = row["values"][i]
        rows_for_csv.append(d)
    pd.DataFrame(rows_for_csv).to_csv(data_dir / "peer-submarket-comparison.csv", index=False)


def generate_report(slug: str, skip_pull: bool = False, output_dir: Path | None = None):
    """Full pipeline: pull data, compute metrics, generate report."""
    config = load_property(slug)
    require_geostack()
    from geostack.db import get_engine

    engine = get_engine()
    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR / config["slug"]
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"═══ Submarket Atlas — {config['name']} ═══\n")

    # Step 1: Build geographies
    print("1. Building analysis geographies...")
    geographies = build_all_geographies(config, engine)
    print(f"   Property tract: {geographies['property_tract']}")
    for r, df in geographies["rings"].items():
        print(f"   {r}-mile ring: {len(df)} tracts")
    for slug_peer, peer in geographies["peers"].items():
        print(f"   Peer '{peer['label']}': {len(peer['tracts'])} tracts")

    # Step 2: Pull demographics (or use cache)
    if not skip_pull:
        print("\n2. Pulling demographics data (this may take several minutes)...")
        pull_demographics(config, geographies)
    else:
        print("\n2. Skipping demographics pull (using cache)...")

    # Step 3: Compute metrics
    print("\n3. Computing metrics scorecard...")
    scorecard = build_scorecard(geographies, config, engine)
    for geo_key, geo_data in scorecard.items():
        ts = geo_data.get("time_series", pd.DataFrame())
        label = geo_data.get("label", geo_key)
        if not ts.empty:
            print(f"   {label}: {len(ts)} years of data")
        else:
            print(f"   {label}: no data")

    # Step 4: Generate charts
    print("\n4. Generating charts...")
    chart_paths = generate_all_charts(scorecard, output_dir, config)

    # Step 5: Generate map
    print("\n5. Generating interactive map...")
    map_path = generate_map(config, geographies, scorecard, output_dir)
    print(f"   Map: {map_path}")

    # Step 5b: Generate print-quality static maps + infographic
    print("\n5b. Generating static maps + infographic...")
    try:
        from submarket_atlas.map_static import generate_static_maps

        static_paths = generate_static_maps(config, geographies, scorecard, output_dir)
        for p in static_paths:
            print(f"   {p}")
    except Exception as e:
        print(f"   Static maps skipped: {e}")

    # Step 6: Generate narrative
    print("\n6. Generating narrative...")
    exec_summary = generate_executive_summary(scorecard, config)
    takeaways = generate_section_takeaways(scorecard)

    # Step 7: Build tables
    print("\n7. Building data tables...")
    snapshot_table, snapshot_geos = _build_snapshot_table(scorecard, config)
    growth_table, growth_geos = _build_growth_table(scorecard, config)
    peer_table, peer_geos = _build_peer_table(scorecard, config)

    # Step 8: Render HTML report
    print("\n8. Rendering HTML report...")
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("report.html")

    years = config["analysis"]["years"]
    ring_counts = {r: len(df) for r, df in geographies["rings"].items()}

    # MSA-agnostic narrative context derived from the property config.
    peer_submarkets_cfg = config["analysis"].get("peer_submarkets", {}) or {}
    peer_descriptions = {
        slug: peer.get("description", "")
        for slug, peer in peer_submarkets_cfg.items()
    }
    peer_entries = [
        {
            "slug": slug,
            "label": peer.get("label", slug),
            "description": peer.get("description", ""),
            "radius_miles": peer.get("radius_miles"),
        }
        for slug, peer in peer_submarkets_cfg.items()
    ]
    msa_county_count = len(config["analysis"].get("msa_counties", []) or [])

    html = template.render(
        title=f"Submarket Intelligence Report — {config['name']}",
        property_name=config["name"],
        address=config["address"],
        market=config["market"],
        report_date=date.today().strftime("%B %d, %Y"),
        latest_year=years[-1],
        earliest_year=years[0],
        lat=config["coordinates"]["lat"],
        lon=config["coordinates"]["lon"],
        property_tract=geographies["property_tract"],
        property_county=config["county"],
        ring_1mi_tracts=ring_counts.get(1, 0),
        ring_3mi_tracts=ring_counts.get(3, 0),
        ring_5mi_tracts=ring_counts.get(5, 0),
        map_filename=f"{config['slug']}-map.html",
        exec_summary=exec_summary,
        takeaways=takeaways,
        charts={k: True for k in chart_paths},
        snapshot_table=snapshot_table,
        snapshot_geos=snapshot_geos,
        growth_table=growth_table,
        growth_geos=growth_geos,
        peer_comparison_table=peer_table,
        peer_geos=peer_geos,
        # MSA-agnostic narrative context
        msa_label=config["msa_label"],
        cbsa_code=config["cbsa_code"],
        msa_county_count=msa_county_count,
        state_label=config.get("state_label", ""),
        market_blurb=config.get("market_blurb", "(market blurb not configured)"),
        peer_market_label=config.get("peer_market_label", "regional multifamily corridors"),
        peer_descriptions=peer_descriptions,
        peer_entries=peer_entries,
    )

    report_path = output_dir / f"{config['slug']}-submarket-report.html"
    report_path.write_text(html)
    print(f"   Report: {report_path}")

    # Step 9: Export data CSVs
    print("\n9. Exporting data CSVs...")
    _export_data(scorecard, geographies, config, output_dir)
    print("   CSVs exported to data/")

    # Step 10: Generate PDF (best-effort)
    print("\n10. Generating PDF...")
    try:
        from weasyprint import HTML as WeasyHTML

        pdf_path = output_dir / f"{config['slug']}-submarket-report.pdf"
        WeasyHTML(string=html, base_url=str(output_dir)).write_pdf(str(pdf_path))
        print(f"   PDF: {pdf_path}")
    except Exception as e:
        print(f"   PDF generation failed (non-blocking): {e}")
        print("   The HTML report is the primary deliverable.")

    # Step 11: Write metadata
    metadata = {
        "property": config["name"],
        "slug": config["slug"],
        "generated": date.today().isoformat(),
        "acs_years": years,
        "geographies": {
            "property_tract": geographies["property_tract"],
            "rings": {str(r): len(df) for r, df in geographies["rings"].items()},
            "peers": {k: len(v["tracts"]) for k, v in geographies["peers"].items()},
        },
        "charts_generated": list(chart_paths.keys()),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    print(f"\n═══ Report complete: {output_dir} ═══")
    return report_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse

    logging.basicConfig(level=logging.INFO)

    # Typed prerequisite check: geostack is a documented prerequisite, not a
    # PyPI-resolvable dependency (see submarket_atlas._deps).
    from submarket_atlas._deps import require_geostack

    try:
        require_geostack()
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)

    parser = argparse.ArgumentParser(description="Generate submarket intelligence report")
    parser.add_argument("--property", help="Property slug")
    parser.add_argument("--list", action="store_true", help="List configured properties")
    parser.add_argument("--skip-pull", action="store_true", help="Skip demographics pull (use cache)")
    parser.add_argument("--output-dir", help="Write reports to this directory (default: ./output/<slug>)")
    args = parser.parse_args()

    if args.list:
        props = list_properties()
        print("Configured properties:")
        for p in props:
            print(f"  • {p}")
        return

    if not args.property:
        parser.error("--property is required (or use --list)")

    generate_report(args.property, skip_pull=args.skip_pull, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
