"""Chart generation with institutional-quality Plotly theme."""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from submarket_atlas.metrics import trend_arrow, cagr


# ── Color Palette ─────────────────────────────────────────────────────────────

COLORS = {
    "primary": "#1B3A5C",
    "secondary": "#2E86AB",
    "accent": "#A23B72",
    "positive": "#2D936C",
    "negative": "#C1292E",
    "neutral": "#6B7280",
    "background": "#FFFFFF",
    "grid": "#E5E7EB",
    "text": "#1F2937",
    "light_bg": "#F9FAFB",
}

# Series colors for multi-line charts
SERIES_COLORS = [
    COLORS["primary"],
    COLORS["secondary"],
    COLORS["accent"],
    COLORS["positive"],
    "#E07A5F",  # warm terracotta
    "#81B29A",  # sage
    "#F2CC8F",  # sand
]


def _atlas_layout(**overrides) -> dict:
    """Base layout for all charts."""
    layout = dict(
        font=dict(family="Inter, system-ui, sans-serif", size=13, color=COLORS["text"]),
        plot_bgcolor=COLORS["background"],
        paper_bgcolor=COLORS["background"],
        margin=dict(l=60, r=30, t=70, b=60),
        xaxis=dict(
            showgrid=False,
            linecolor=COLORS["grid"],
            linewidth=1,
            tickfont=dict(size=12),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=COLORS["grid"],
            gridwidth=0.5,
            linecolor=COLORS["grid"],
            linewidth=1,
            tickfont=dict(size=12),
            zeroline=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        ),
        hoverlabel=dict(
            bgcolor=COLORS["primary"],
            font_size=12,
            font_color="white",
        ),
    )
    layout.update(overrides)
    return layout


def _source_annotation(text: str = "Source: U.S. Census Bureau, ACS 5-Year Estimates") -> dict:
    return dict(
        text=text,
        xref="paper",
        yref="paper",
        x=0,
        y=-0.22,
        showarrow=False,
        font=dict(size=10, color=COLORS["neutral"]),
    )


def _save_chart(fig: go.Figure, output_dir: Path, filename: str, width=1200, height=800):
    """Save chart as PNG at 300 DPI."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    fig.write_image(str(path), width=width, height=height, scale=2)  # scale=2 → effective 300 DPI
    return path


# ── Chart Functions ───────────────────────────────────────────────────────────


def population_trend(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Multi-line population trend chart."""
    fig = go.Figure()

    geo_order = ["property_tract", "1mi", "3mi", "5mi", "msa"]
    labels = {
        "property_tract": "Property Tract",
        "1mi": "1-Mile",
        "3mi": "3-Mile",
        "5mi": "5-Mile",
        "msa": msa_label,
    }

    for i, geo in enumerate(geo_order):
        if geo not in scorecard:
            continue
        ts = scorecard[geo]["time_series"]
        if ts.empty or "population" not in ts.columns:
            continue

        # Normalize to index (base year = 100) for comparability
        base = ts["population"].iloc[0]
        if base and base > 0:
            indexed = (ts["population"] / base) * 100
        else:
            continue

        fig.add_trace(go.Scatter(
            x=indexed.index,
            y=indexed.values,
            name=labels.get(geo, geo),
            mode="lines+markers",
            line=dict(width=2.5, color=SERIES_COLORS[i % len(SERIES_COLORS)]),
            marker=dict(size=5),
        ))

    latest_year = max(
        ts.index.max()
        for geo in geo_order
        if geo in scorecard and not scorecard[geo]["time_series"].empty
    )

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Population Growth Trend</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Indexed to {scorecard[geo_order[0]]['time_series'].index.min()} = 100</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Population Index",
        )
    )
    fig.add_annotation(**_source_annotation(
        f"Source: U.S. Census Bureau, ACS 5-Year Estimates (2013–{latest_year})"
    ))

    return _save_chart(fig, output_dir, "population-trend.png")


def income_trend(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Median household income trend."""
    fig = go.Figure()

    geos = ["3mi", "5mi", "msa"]
    labels = {"3mi": "3-Mile Submarket", "5mi": "5-Mile Submarket", "msa": msa_label}

    for i, geo in enumerate(geos):
        if geo not in scorecard:
            continue
        ts = scorecard[geo]["time_series"]
        if ts.empty or "median_hhi" not in ts.columns:
            continue

        fig.add_trace(go.Scatter(
            x=ts.index,
            y=ts["median_hhi"],
            name=labels.get(geo, geo),
            mode="lines+markers",
            line=dict(width=2.5, color=SERIES_COLORS[i % len(SERIES_COLORS)]),
            marker=dict(size=5),
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Median Household Income</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Submarket vs. {msa_label}</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Median HHI ($)",
            yaxis_tickprefix="$",
            yaxis_tickformat=",",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "income-trend.png")


def rent_vs_income(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Rent growth vs income growth overlay — the money chart."""
    fig = go.Figure()

    geo = "3mi"
    if geo not in scorecard:
        geo = "5mi"
    ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
    if ts.empty:
        return None

    # Index both series to base year = 100
    for metric, label, color in [
        ("median_rent", "Median Rent", COLORS["accent"]),
        ("median_hhi", "Median HHI", COLORS["secondary"]),
    ]:
        if metric not in ts.columns:
            continue
        base = ts[metric].iloc[0]
        if base and base > 0:
            indexed = (ts[metric] / base) * 100
            fig.add_trace(go.Scatter(
                x=indexed.index,
                y=indexed.values,
                name=label,
                mode="lines+markers",
                line=dict(width=3, color=color),
                marker=dict(size=6),
            ))

    # Add rent-to-income ratio on secondary axis
    if "rent_to_income" in ts.columns:
        fig.add_trace(go.Scatter(
            x=ts.index,
            y=ts["rent_to_income"] * 100,
            name="Rent-to-Income %",
            mode="lines+markers",
            line=dict(width=2, color=COLORS["neutral"], dash="dot"),
            marker=dict(size=4),
            yaxis="y2",
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Rent Growth vs. Income Growth</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>3-Mile Submarket — Indexed to Base Year = 100</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Growth Index (Base = 100)",
            yaxis2=dict(
                title="Rent-to-Income %",
                overlaying="y",
                side="right",
                showgrid=False,
                ticksuffix="%",
                tickfont=dict(size=11, color=COLORS["neutral"]),
            ),
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "rent-vs-income.png")


def rent_burden(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Rent burden distribution chart."""
    fig = go.Figure()

    geo = "3mi"
    ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
    if ts.empty or "rent_burden_rate" not in ts.columns:
        return None

    fig.add_trace(go.Scatter(
        x=ts.index,
        y=ts["rent_burden_rate"] * 100,
        name="3-Mile Submarket",
        mode="lines+markers",
        line=dict(width=2.5, color=COLORS["accent"]),
        marker=dict(size=5),
        fill="tozeroy",
        fillcolor="rgba(162, 59, 114, 0.1)",
    ))

    msa_ts = scorecard.get("msa", {}).get("time_series", pd.DataFrame())
    if not msa_ts.empty and "rent_burden_rate" in msa_ts.columns:
        fig.add_trace(go.Scatter(
            x=msa_ts.index,
            y=msa_ts["rent_burden_rate"] * 100,
            name=msa_label,
            mode="lines+markers",
            line=dict(width=2, color=COLORS["neutral"], dash="dash"),
            marker=dict(size=4),
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Rent Burden Rate</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Share of Renters Paying 30%+ of Income on Rent</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Rent-Burdened (%)",
            yaxis_ticksuffix="%",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "rent-burden.png")


def housing_supply(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Total housing units trend."""
    fig = go.Figure()

    geos = ["3mi", "5mi", "msa"]
    labels = {"3mi": "3-Mile Submarket", "5mi": "5-Mile Submarket", "msa": msa_label}

    for i, geo in enumerate(geos):
        ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
        if ts.empty or "total_housing_units" not in ts.columns:
            continue

        base = ts["total_housing_units"].iloc[0]
        if base and base > 0:
            indexed = (ts["total_housing_units"] / base) * 100
            fig.add_trace(go.Scatter(
                x=indexed.index,
                y=indexed.values,
                name=labels.get(geo, geo),
                mode="lines+markers",
                line=dict(width=2.5, color=SERIES_COLORS[i % len(SERIES_COLORS)]),
                marker=dict(size=5),
            ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Housing Supply Growth</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Total Housing Units — Indexed to Base Year = 100</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Housing Units Index",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "housing-supply.png")


def renter_propensity(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Renter propensity trend."""
    fig = go.Figure()

    geos = ["3mi", "5mi", "msa"]
    labels = {"3mi": "3-Mile Submarket", "5mi": "5-Mile Submarket", "msa": msa_label}

    for i, geo in enumerate(geos):
        ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
        if ts.empty or "renter_propensity" not in ts.columns:
            continue

        fig.add_trace(go.Scatter(
            x=ts.index,
            y=ts["renter_propensity"] * 100,
            name=labels.get(geo, geo),
            mode="lines+markers",
            line=dict(width=2.5, color=SERIES_COLORS[i % len(SERIES_COLORS)]),
            marker=dict(size=5),
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Renter Propensity</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Renter-Occupied as % of Total Occupied Units</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Renter Share (%)",
            yaxis_ticksuffix="%",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "renter-propensity.png")


def age_distribution(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Age distribution comparison — submarket vs MSA."""
    fig = go.Figure()

    # We need raw age bracket data — construct from time series latest year
    geos = {"3mi": "3-Mile Submarket", "msa": msa_label}
    bar_colors = [COLORS["primary"], COLORS["neutral"]]

    for idx, (geo, label) in enumerate(geos.items()):
        ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
        if ts.empty:
            continue

        latest = ts.iloc[-1]
        pop = latest.get("population", 0)
        if pop == 0:
            continue

        prime = latest.get("prime_renter_share", 0)
        # We can show key cohort shares
        data = {
            "Prime Renter\n(20-34)": prime * 100 if prime else 0,
        }

        fig.add_trace(go.Bar(
            x=list(data.keys()),
            y=list(data.values()),
            name=label,
            marker_color=bar_colors[idx],
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Prime Renter Cohort (Age 20-34)</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Share of Total Population</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Share of Population (%)",
            yaxis_ticksuffix="%",
            barmode="group",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "age-distribution.png")


def prime_renter_trend(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Prime renter cohort (20-34) share trend."""
    fig = go.Figure()

    geos = ["3mi", "5mi", "msa"]
    labels = {"3mi": "3-Mile Submarket", "5mi": "5-Mile Submarket", "msa": msa_label}

    for i, geo in enumerate(geos):
        ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
        if ts.empty or "prime_renter_share" not in ts.columns:
            continue

        fig.add_trace(go.Scatter(
            x=ts.index,
            y=ts["prime_renter_share"] * 100,
            name=labels.get(geo, geo),
            mode="lines+markers",
            line=dict(width=2.5, color=SERIES_COLORS[i % len(SERIES_COLORS)]),
            marker=dict(size=5),
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Prime Renter Cohort Trend</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Age 20-34 as Share of Total Population</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Prime Renter Share (%)",
            yaxis_ticksuffix="%",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "prime-renter-trend.png")


def income_distribution(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Income distribution — stacked bar by bracket for submarket vs MSA."""
    fig = go.Figure()

    # We need the raw income bracket data from the latest year
    brackets = [
        ("< $25K", ["B19001_002E", "B19001_003E", "B19001_004E", "B19001_005E"]),
        ("$25-50K", ["B19001_006E", "B19001_007E", "B19001_008E", "B19001_009E", "B19001_010E"]),
        ("$50-75K", ["B19001_011E", "B19001_012E"]),
        ("$75-100K", ["B19001_013E"]),
        ("$100-150K", ["B19001_014E", "B19001_015E"]),
        ("$150K+", ["B19001_016E", "B19001_017E"]),
    ]

    bracket_colors = ["#C1292E", "#E07A5F", "#F2CC8F", "#81B29A", "#2E86AB", "#1B3A5C"]

    geos_to_plot = ["3mi", "msa"]
    geo_labels = {"3mi": "3-Mile Submarket", "msa": msa_label}

    for geo in geos_to_plot:
        ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
        if ts.empty:
            continue
        latest = ts.iloc[-1]

        total_hh = sum(
            latest.get(v, 0) or 0
            for bracket_name, vars_list in brackets
            for v in vars_list
        )
        if total_hh == 0:
            continue

        shares = []
        for bracket_name, vars_list in brackets:
            count = sum(latest.get(v, 0) or 0 for v in vars_list)
            shares.append(count / total_hh * 100)

        for i, (bracket_name, _) in enumerate(brackets):
            showlegend = geo == geos_to_plot[0]
            fig.add_trace(go.Bar(
                x=[geo_labels[geo]],
                y=[shares[i]],
                name=bracket_name if showlegend else None,
                marker_color=bracket_colors[i],
                showlegend=showlegend,
                legendgroup=bracket_name,
            ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Household Income Distribution</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>Share of Households by Income Bracket</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Share (%)",
            yaxis_ticksuffix="%",
            barmode="stack",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "income-distribution.png", width=800, height=800)


def units_by_structure(scorecard: dict, output_dir: Path, msa_label: str) -> Path:
    """Units by structure type — stacked area showing MF share."""
    fig = go.Figure()

    geo = "3mi"
    ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
    if ts.empty:
        return None

    struct_vars = [
        ("1-Unit Detached", "B25024_002E", "#81B29A"),
        ("2-4 Units", ["B25024_005E", "B25024_006E"], "#F2CC8F"),
        ("5-19 Units", ["B25024_007E", "B25024_008E"], "#2E86AB"),
        ("20+ Units", "B25024_009E", "#1B3A5C"),
        ("Mobile/Other", "B25024_010E", "#6B7280"),
    ]

    for name, vars_key, color in struct_vars:
        if isinstance(vars_key, list):
            vals = sum(ts[v] if v in ts.columns else pd.Series(0, index=ts.index) for v in vars_key)
        else:
            vals = ts[vars_key] if vars_key in ts.columns else pd.Series(0, index=ts.index)

        fig.add_trace(go.Scatter(
            x=ts.index,
            y=vals,
            name=name,
            mode="lines",
            line=dict(width=0.5, color=color),
            stackgroup="one",
            fillcolor=color,
        ))

    fig.update_layout(
        **_atlas_layout(
            title=dict(
                text="<b>Housing Units by Structure Type</b><br>"
                     f"<span style='font-size:12px;color:{COLORS['neutral']}'>3-Mile Submarket</span>",
                x=0,
                xanchor="left",
            ),
            yaxis_title="Housing Units",
            yaxis_tickformat=",",
        )
    )
    fig.add_annotation(**_source_annotation())

    return _save_chart(fig, output_dir, "units-by-structure.png")


def peer_comparison_radar(scorecard: dict, output_dir: Path, msa_label: str, property_short: str, peer_slugs: list) -> Path:
    """Radar chart comparing property submarket vs peers."""
    metrics_to_compare = [
        ("population", "Pop. Growth", True),
        ("median_hhi", "Income Level", True),
        ("renter_propensity", "Renter Share", True),
        ("prime_renter_share", "Prime Renters", True),
        ("mf_density", "MF Density", True),
        ("bachelors_plus_share", "Education", True),
    ]

    # Get latest year values for normalization
    all_vals = {}
    geos = ["3mi", *peer_slugs, "msa"]
    geo_labels = {
        "3mi": f"{property_short} 3mi",
        "msa": msa_label,
    }
    for slug in peer_slugs:
        geo_labels[slug] = scorecard.get(slug, {}).get("label", slug)

    for geo in geos:
        ts = scorecard.get(geo, {}).get("time_series", pd.DataFrame())
        if ts.empty:
            continue
        latest = ts.iloc[-1]
        all_vals[geo] = {m: latest.get(m) for m, _, _ in metrics_to_compare}

    if not all_vals:
        return None

    # Normalize to 0-100 scale based on min/max across all geos
    categories = [label for _, label, _ in metrics_to_compare]

    fig = go.Figure()

    for i, geo in enumerate(geos):
        if geo not in all_vals:
            continue

        values = []
        for metric, _, higher_is_better in metrics_to_compare:
            val = all_vals[geo].get(metric)
            if val is None:
                values.append(50)
                continue

            # Get range across all geos
            all_metric_vals = [
                all_vals[g].get(metric) for g in geos if g in all_vals and all_vals[g].get(metric) is not None
            ]
            if not all_metric_vals:
                values.append(50)
                continue

            mn, mx = min(all_metric_vals), max(all_metric_vals)
            if mx == mn:
                values.append(50)
            else:
                normalized = (val - mn) / (mx - mn) * 100
                values.append(normalized)

        values.append(values[0])  # close the polygon

        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=categories + [categories[0]],
            name=geo_labels.get(geo, geo),
            line=dict(width=2, color=SERIES_COLORS[i % len(SERIES_COLORS)]),
        ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], showticklabels=False),
            bgcolor=COLORS["background"],
        ),
        font=dict(family="Inter, system-ui, sans-serif", size=12, color=COLORS["text"]),
        paper_bgcolor=COLORS["background"],
        title=dict(
            text="<b>Peer Submarket Comparison</b><br>"
                 f"<span style='font-size:12px;color:{COLORS['neutral']}'>Relative Positioning on Key Metrics (Normalized 0-100)</span>",
            x=0,
            xanchor="left",
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.1,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        ),
        margin=dict(t=80, b=80),
    )

    return _save_chart(fig, output_dir, "peer-comparison-radar.png", width=900, height=900)


def generate_all_charts(scorecard: dict, output_dir: Path, config: dict) -> dict:
    """Generate all charts and return paths."""
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    msa_label = config["msa_label"]
    property_short = config["name"].split("&")[0].split("(")[0].strip()
    peer_slugs = list(config["analysis"].get("peer_submarkets", {}).keys())

    paths = {}
    simple_charts = [
        ("population_trend", population_trend),
        ("income_trend", income_trend),
        ("rent_vs_income", rent_vs_income),
        ("rent_burden", rent_burden),
        ("housing_supply", housing_supply),
        ("renter_propensity", renter_propensity),
        ("age_distribution", age_distribution),
        ("prime_renter_trend", prime_renter_trend),
        ("income_distribution", income_distribution),
        ("units_by_structure", units_by_structure),
    ]

    for name, func in simple_charts:
        try:
            path = func(scorecard, charts_dir, msa_label)
            if path:
                paths[name] = path
                print(f"  ✓ {name}")
            else:
                print(f"  ⚠ {name} — no data")
        except Exception as e:
            print(f"  ✗ {name} — {e}")

    try:
        path = peer_comparison_radar(scorecard, charts_dir, msa_label, property_short, peer_slugs)
        if path:
            paths["peer_comparison_radar"] = path
            print(f"  ✓ peer_comparison_radar")
        else:
            print(f"  ⚠ peer_comparison_radar — no data")
    except Exception as e:
        print(f"  ✗ peer_comparison_radar — {e}")

    return paths
