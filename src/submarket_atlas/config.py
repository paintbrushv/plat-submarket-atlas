"""Property configuration loader."""

import os
from pathlib import Path

import yaml


# Repo-level property configs (config/properties/) take precedence; the
# shipped example (submarket_atlas/properties/) is the fallback so an
# installed package still resolves `demo-park` without a checkout.
_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "properties"
CONFIG_DIR = _REPO_CONFIG_DIR if _REPO_CONFIG_DIR.is_dir() else _PACKAGE_DIR / "properties"


REQUIRED_FIELDS = (
    "name",
    "slug",
    "state_fips",
    "property_tract",
    "cbsa_code",
    "msa_label",
    "msa_centroid",
)


def load_property(slug: str) -> dict:
    """Load a property configuration by slug name.

    Validates that required fields are present and fails loudly if any are
    missing. `cbsa_code` / `msa_label` / `msa_centroid` are required so the
    MSA comparison row reflects the property's own metro rather than a
    hardcoded default.
    """
    path = CONFIG_DIR / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Property config not found: {path}")
    with open(path) as f:
        config = yaml.safe_load(f)

    missing = [f for f in REQUIRED_FIELDS if config.get(f) in (None, "")]
    if missing:
        raise ValueError(
            f"Property config {path} is missing required field(s): {missing}. "
            "Add these top-level keys to the YAML."
        )

    centroid = config["msa_centroid"]
    if not isinstance(centroid, dict) or "lat" not in centroid or "lon" not in centroid:
        raise ValueError(
            f"Property config {path} 'msa_centroid' must be a mapping with 'lat' and 'lon' keys."
        )

    # Optional narrative fields with fallbacks so older configs still render.
    config.setdefault("market_blurb", "(market blurb not configured)")
    config.setdefault("peer_market_label", "regional multifamily corridors")
    # state_label drives the Methodology MSA-definition prose. Default to the
    # state postal code when it can be inferred from the YAML, otherwise blank.
    state = config.get("state")
    if state and len(state) == 2:
        config.setdefault("state_label", state.upper())
    else:
        config.setdefault("state_label", "")

    return config


def list_properties() -> list[str]:
    """List all configured property slugs."""
    return sorted(p.stem for p in CONFIG_DIR.glob("*.yaml"))
