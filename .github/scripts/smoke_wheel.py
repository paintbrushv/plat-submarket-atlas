#!/usr/bin/env python3
"""Install the freshly built wheel into a throwaway venv and smoke it.

Run from the repo root after `python -m build`; expects exactly one wheel in
dist/. geostack (the spatial-engine prerequisite) is intentionally not a
core dependency — its PyPI name is occupied by an unrelated project — so the
wheel installs standalone from PyPI-resolvable deps only. Verifies: install
resolves, pure analytics modules import and compute, the report template and
example property config ship as package data, and the geostack prerequisite
guard raises the typed, actionable error.
"""

from __future__ import annotations

import glob
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "dist"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def main() -> int:
    wheels = sorted(glob.glob(str(DIST / "*.whl")))
    if len(wheels) != 1:
        print(f"expected exactly one wheel in dist/, found: {wheels}")
        return 1
    wheel = wheels[0]

    with tempfile.TemporaryDirectory(prefix="submarket-atlas-smoke-") as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.create(venv_dir, with_pip=True)
        py = str(venv_dir / "bin" / "python")

        run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
        run([py, "-m", "pip", "install", "--quiet", wheel])

        # Pure modules: imports + version
        run([py, "-c",
             "import submarket_atlas; "
             "from submarket_atlas.metrics import cagr, trend_direction; "
             "assert abs(cagr(100.0, 121.0, years=2) - 0.10) < 1e-9; "
             "assert trend_direction(0.10) == 'improving'; "
             "print('metrics-ok', submarket_atlas.__version__)"])

        # Report template ships in the wheel and is locatable
        run([py, "-c",
             "from submarket_atlas.report import TEMPLATE_DIR; "
             "p = TEMPLATE_DIR / 'report.html'; "
             "assert p.exists(), f'missing {p}'; "
             "print('template-ok')"])

        # Example property config ships as package data and loads
        run([py, "-c",
             "from submarket_atlas.config import load_property; "
             "p = load_property('demo-park'); "
             "assert p['slug'] == 'demo-park'; "
             "print('config-ok')"])

        # geostack prerequisite guard: typed, actionable error when absent
        run([py, "-c",
             "from submarket_atlas._deps import require_geostack, "
             "MissingGeostackError\n"
             "try:\n"
             "    require_geostack()\n"
             "    raise SystemExit('geostack unexpectedly present')\n"
             "except MissingGeostackError as e:\n"
             "    assert 'git+https://github.com/paintbrushv/geostack' in "
             "str(e)\n"
             "    print('geostack-guard-ok')"])

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())