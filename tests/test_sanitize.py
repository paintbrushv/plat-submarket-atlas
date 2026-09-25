# sanitize gate — public release tree
"""Public-tree sanitize gate.

Fails if any private/company identity literal leaks into the public tree:
real property names, personal identity, private host paths, or the company
token. The gate file itself is skipped (it necessarily contains the literals
it forbids).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()

_FORBIDDEN = {
    # Personal identity
    "matthewdickson": "personal username",
    "matthew dickson": "personal name",
    "dickson": "personal name",
    # Real property names / deal slugs
    "chatham court": "real property name",
    "chatham-court": "real property slug",
    "chatham_court": "real property slug",
    "woodford on mockingbird": "real property name",
    "woodford-on-mockingbird": "real property slug",
    "woodford_on_mockingbird": "real property slug",
    "woodford": "real property name",
    "mccallum blvd": "real property address",
    "mockingbird ln, midland": "real property address",
    "tower village": "real property name",
    "terrace cove": "real property name",
    "the principal": "real property name",
    # Company / private host identity
    "uplift partners": "company name",
    "sharepoint": "private SharePoint tenant references",
    # Host identity and private paths
    "/home/mdai": "private host path",
    "/users/matthewdickson": "private laptop path",
    "spark-17d5": "private hostname",
}

_SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".pytest-tmp"}
_TEXT_SUFFIXES = {
    ".py", ".json", ".md", ".toml", ".txt", ".yml", ".yaml", ".cfg",
    ".ini", ".csv", ".html", ".css", ".js", ".sh", ".example", ".j2", "",
}


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def test_no_private_literals_in_tree() -> None:
    hits = []
    for path in _iter_text_files():
        if path.resolve() == _SELF:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for lit, why in _FORBIDDEN.items():
            if lit in text:
                hits.append(f"{path}: {lit!r} ({why})")
    assert not hits, "private identity literals found:\n" + "\n".join(hits)


def test_no_private_literals_in_filenames() -> None:
    hits = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        name = path.name.lower()
        for lit, why in _FORBIDDEN.items():
            if lit in name:
                hits.append(f"{path}: {lit!r} ({why})")
    assert not hits, "private identity in filenames:\n" + "\n".join(hits)