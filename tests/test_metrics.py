"""Derived-analytics tests for metrics that need no database.

CAGR and trend helpers are pure functions; exercising them keeps the
public tree's suite from being config+gate only.
"""

from __future__ import annotations

import pytest

from submarket_atlas.metrics import cagr, trend_direction, trend_arrow


def test_cagr_positive_growth():
    assert cagr(100.0, 121.0, years=2) == pytest.approx(0.1, rel=1e-9)


def test_cagr_invalid_inputs_return_none():
    assert cagr(0.0, 10.0, years=2) is None
    assert cagr(100.0, -5.0, years=2) is None
    assert cagr(100.0, 120.0, years=0) is None
    assert cagr(None, 120.0, years=2) is None


def test_trend_direction_buckets():
    assert trend_direction(0.10) == "improving"
    assert trend_direction(-0.10) == "declining"
    assert trend_direction(0.001) == "stable"
    assert trend_direction(None) == "N/A"


def test_trend_arrow_symbols():
    assert trend_arrow(0.10) == "▲"
    assert trend_arrow(-0.10) == "▼"
    assert trend_arrow(0.001) == "►"
    assert trend_arrow(None) == "—"