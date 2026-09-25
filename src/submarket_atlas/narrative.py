"""Narrative generation — transform metrics into boardroom-ready text."""

import math

from submarket_atlas.metrics import cagr, trend_direction


def _is_missing(val):
    """Check if a value is missing (None, NaN, or inf)."""
    if val is None:
        return True
    try:
        return math.isnan(val) or math.isinf(val)
    except (TypeError, ValueError):
        return False


def fmt_pct(val, decimals=1):
    """Format as percentage."""
    if _is_missing(val):
        return "—"
    return f"{val * 100:.{decimals}f}%"


def fmt_dollar(val, decimals=0):
    """Format as dollar amount."""
    if _is_missing(val):
        return "—"
    return f"${val:,.{decimals}f}"


def fmt_number(val, decimals=0):
    """Format with commas."""
    if _is_missing(val):
        return "—"
    return f"{val:,.{decimals}f}"


def fmt_cagr(val, decimals=1):
    """Format CAGR as basis points or percentage."""
    if _is_missing(val):
        return "—"
    return f"{val * 100:.{decimals}f}%"


def fmt_bps(val, decimals=0):
    """Format as basis points."""
    if _is_missing(val):
        return "—"
    return f"{val * 10000:.{decimals}f} bps"


def generate_executive_summary(scorecard: dict, config: dict) -> dict:
    """Generate executive summary bullets and thesis from the scorecard.

    Returns dict with keys: bullets (list of str), thesis (str), scorecard_items (list of dicts)
    """
    bullets = []
    thesis_parts = []

    sub = scorecard.get("3mi", {})
    msa = scorecard.get("msa", {})
    sub_ts = sub.get("time_series")
    msa_ts = msa.get("time_series")

    if sub_ts is None or sub_ts.empty or msa_ts is None or msa_ts.empty:
        return {"bullets": ["Insufficient data for executive summary."], "thesis": "", "scorecard_items": []}

    sub_latest = sub_ts.iloc[-1]
    sub_earliest = sub_ts.iloc[0]
    msa_latest = msa_ts.iloc[-1]
    msa_earliest = msa_ts.iloc[0]
    latest_year = sub_ts.index.max()
    earliest_year = sub_ts.index.min()
    years_span = latest_year - earliest_year

    # ── Population bullet ──
    pop_start = sub_earliest.get("population")
    pop_end = sub_latest.get("population")
    pop_cagr_sub = cagr(pop_start, pop_end, years_span) if pop_start and pop_end else None
    pop_cagr_msa = cagr(
        msa_earliest.get("population"), msa_latest.get("population"), years_span
    )
    msa_label = config.get("msa_label", "the metro")
    if pop_cagr_sub is not None:
        pop_diff = pop_end - pop_start if pop_start else 0
        bps_diff = ((pop_cagr_sub or 0) - (pop_cagr_msa or 0)) * 10000
        direction = "outpaces" if bps_diff > 0 else "trails"
        bullets.append(
            f"The 3-mile submarket has added {fmt_number(pop_diff)} residents since {earliest_year}, "
            f"a {fmt_cagr(pop_cagr_sub)} CAGR that {direction} the {msa_label} metro by {abs(bps_diff):.0f} basis points."
        )
        thesis_parts.append("growing" if pop_cagr_sub > 0.005 else ("mature" if pop_cagr_sub > 0 else "declining"))

    # ── Income bullet ──
    hhi_start = sub_earliest.get("median_hhi")
    hhi_end = sub_latest.get("median_hhi")
    hhi_cagr = cagr(hhi_start, hhi_end, years_span) if hhi_start and hhi_end else None
    if hhi_cagr is not None:
        bullets.append(
            f"Median household income has grown from {fmt_dollar(hhi_start)} to {fmt_dollar(hhi_end)} "
            f"({fmt_cagr(hhi_cagr)} CAGR), supporting continued rent growth."
        )

    # ── Renter propensity bullet ──
    rp = sub_latest.get("renter_propensity")
    rp_msa = msa_latest.get("renter_propensity")
    if rp is not None and rp_msa is not None:
        comparison = "above" if rp > rp_msa else "below"
        bullets.append(
            f"Renter propensity is {fmt_pct(rp)}, {comparison} the metro average of {fmt_pct(rp_msa)}, "
            f"indicating {'structural rental demand' if rp > rp_msa else 'a more ownership-oriented market'}."
        )

    # ── Prime renter bullet ──
    pr = sub_latest.get("prime_renter_share")
    pr_trend = trend_direction(
        cagr(sub_earliest.get("prime_renter_share"), pr, years_span) if pr else None
    )
    if pr is not None:
        bullets.append(
            f"The prime renter cohort (age 20-34) represents {fmt_pct(pr)} of the submarket, "
            f"trending {pr_trend}."
        )

    # ── Rent-to-income bullet ──
    rti = sub_latest.get("rent_to_income")
    if rti is not None:
        headroom = "headroom" if rti < 0.30 else "pressure"
        bullets.append(
            f"Rent-to-income ratio of {fmt_pct(rti)} indicates {headroom} for rent increases."
        )

    # ── Thesis ──
    character = thesis_parts[0] if thesis_parts else "established"
    attrs = []
    if hhi_end and hhi_end > 80000:
        attrs.append("above-average incomes")
    if rp and rp > 0.40:
        attrs.append("strong rental demand")
    if pr and pr > 0.15:
        attrs.append("a healthy prime-renter demographic")
    attr_str = ", ".join(attrs) if attrs else "moderate fundamentals"

    positive = (pop_cagr_sub or 0) > 0 and (hhi_cagr or 0) > 0
    sentiment = "positive" if positive else "mixed"

    submarket_name = config.get("market", "The submarket")
    thesis = (
        f"{submarket_name} is a {character} submarket characterized by {attr_str}, "
        f"with {sentiment} fundamentals for multifamily investment."
    )

    # ── Scorecard items ──
    scorecard_items = []

    def _add_item(label, value, fmt_func, compare_msa=None, higher_is_better=True):
        item = {"label": label, "value": fmt_func(value)}
        if compare_msa is not None and value is not None:
            diff = value - compare_msa
            if abs(diff) < 0.001:
                item["vs_msa"] = "In line with MSA"
                item["vs_msa_class"] = "neutral"
            else:
                better = (diff > 0) == higher_is_better
                item["vs_msa"] = f"{'▲' if diff > 0 else '▼'} vs MSA"
                item["vs_msa_class"] = "positive" if better else "negative"
        scorecard_items.append(item)

    _add_item("Population", pop_end, lambda v: fmt_number(v), msa_latest.get("population"))
    _add_item("Median HHI", hhi_end, fmt_dollar, msa_latest.get("median_hhi"))
    _add_item("Median Rent", sub_latest.get("median_rent"), fmt_dollar, msa_latest.get("median_rent"))
    _add_item("Renter Share", rp, fmt_pct, rp_msa)
    _add_item("Rent-to-Income", rti, fmt_pct, msa_latest.get("rent_to_income"), higher_is_better=False)
    _add_item("Vacancy Proxy", sub_latest.get("vacancy_proxy"), fmt_pct,
              msa_latest.get("vacancy_proxy"), higher_is_better=False)

    return {
        "bullets": bullets,
        "thesis": thesis,
        "scorecard_items": scorecard_items,
    }


def generate_section_takeaways(scorecard: dict) -> dict:
    """Generate key takeaway text for each report section."""
    takeaways = {}

    sub = scorecard.get("3mi", {}).get("time_series")
    msa = scorecard.get("msa", {}).get("time_series")

    if sub is None or sub.empty:
        return takeaways

    sub_latest = sub.iloc[-1]
    msa_latest = msa.iloc[-1] if msa is not None and not msa.empty else {}

    # Demographics takeaway
    pop_cagr = cagr(sub.iloc[0].get("population"), sub_latest.get("population"), len(sub) - 1)
    pr = sub_latest.get("prime_renter_share")
    takeaways["demographics"] = (
        f"Population growth of {fmt_cagr(pop_cagr)} annually supports sustained housing demand. "
        f"The prime renter cohort at {fmt_pct(pr)} {'remains healthy for multifamily absorption' if pr and pr > 0.12 else 'is modest'}."
    )

    # Income/affordability takeaway
    rti = sub_latest.get("rent_to_income")
    burden = sub_latest.get("rent_burden_rate")
    takeaways["income"] = (
        f"With a rent-to-income ratio of {fmt_pct(rti)}, "
        f"{'there is room to push rents without exceeding the 30% affordability threshold' if rti and rti < 0.30 else 'rents are approaching the affordability ceiling'}. "
        f"Rent burden rate at {fmt_pct(burden)} {'warrants monitoring' if burden and burden > 0.45 else 'is manageable'}."
    )

    # Housing supply takeaway
    mf = sub_latest.get("mf_density")
    vac = sub_latest.get("vacancy_proxy")
    takeaways["housing"] = (
        f"Multifamily density at {fmt_pct(mf)} reflects a {'well-developed' if mf and mf > 0.30 else 'moderately developed'} MF submarket. "
        f"The vacancy proxy of {fmt_pct(vac)} {'signals tight conditions' if vac and vac < 0.06 else 'is within normal bounds'}."
    )

    return takeaways
