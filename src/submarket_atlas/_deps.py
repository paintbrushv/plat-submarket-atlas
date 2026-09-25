"""Optional-dependency guards.

geostack (the spatial-engine library backing the PostGIS query layer) is a
documented prerequisite, not a PyPI-resolvable core dependency: the PyPI name
``geostack`` is occupied by an unrelated 2023 placeholder project and the
real engine lives at https://github.com/paintbrushv/geostack (not yet
published under an installable name). Install it explicitly:

    pip install "geostack[viz] @ git+https://github.com/paintbrushv/geostack.git"

Any geostack-backed entry point calls :func:`require_geostack` first so a
missing install surfaces as a typed, actionable error instead of a naked
``ModuleNotFoundError`` deep inside the import graph.
"""

from __future__ import annotations

GEOSTACK_INSTALL_HINT = (
    "submarket-atlas requires the geostack spatial engine for this "
    "operation. It is not on PyPI under that name; install it from GitHub:\n"
    '    pip install "geostack[viz] @ '
    'git+https://github.com/paintbrushv/geostack.git"'
)


class MissingGeostackError(ImportError):
    """Raised when a geostack-backed API is called without geostack installed."""

    def __init__(self) -> None:
        super().__init__(GEOSTACK_INSTALL_HINT)
        self.hint = GEOSTACK_INSTALL_HINT


def require_geostack() -> None:
    """Raise a typed, actionable error if geostack is not importable."""
    try:
        import geostack  # noqa: F401
    except ImportError as exc:
        raise MissingGeostackError() from exc