"""Property configuration loader tests for the public example config.

These tests exercise the config contract (required fields, validation
failures, listing) against the shipped example config only — no real
property configs ship with the public tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from submarket_atlas import config as cfg


def test_example_config_loads():
    p = cfg.load_property("demo-park")
    assert p["name"]
    assert p["slug"] == "demo-park"
    for field in cfg.REQUIRED_FIELDS:
        assert p.get(field) not in (None, "")


def test_list_properties_includes_example():
    assert "demo-park" in cfg.list_properties()


def test_missing_config_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        cfg.load_property("no-such-property")


def test_config_missing_required_field_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"name": "Bad", "slug": "bad"}))
    with pytest.raises(ValueError, match="missing required field"):
        cfg.load_property("bad")


def test_config_msa_centroid_shape_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    doc = {f: "x" for f in cfg.REQUIRED_FIELDS}
    doc["msa_centroid"] = {"lat": 1.0}
    bad = tmp_path / "bad2.yaml"
    bad.write_text(yaml.safe_dump(doc))
    with pytest.raises(ValueError, match="msa_centroid"):
        cfg.load_property("bad2")


def test_optional_fields_backfilled(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "CONFIG_DIR", tmp_path)
    doc = {f: "x" for f in cfg.REQUIRED_FIELDS}
    doc["msa_centroid"] = {"lat": 1.0, "lon": 2.0}
    doc["state"] = "TX"
    ok = tmp_path / "ok.yaml"
    ok.write_text(yaml.safe_dump(doc))
    p = cfg.load_property("ok")
    assert p["market_blurb"]
    assert p["state_label"] == "TX"