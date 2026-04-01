"""Allowlist management. Simple .slopcheck file, one package per line."""

from pathlib import Path
from typing import Optional

ALLOWLIST_FILE = ".slopcheck"


def _find_allowlist(start: Optional[Path] = None) -> Path:
    """Find .slopcheck file, walking up from start dir to repo root.

    Stops at the first .git boundary or filesystem root. If no .slopcheck
    file is found, defaults to placing one in the original start directory
    (not the filesystem root).
    """
    if start is None:
        start = Path(".")
    original = start.resolve()
    current = original
    while True:
        candidate = current / ALLOWLIST_FILE
        if candidate.exists():
            return candidate
        # Stop at .git boundary -- this is the repo root
        if (current / ".git").exists():
            return current / ALLOWLIST_FILE
        # Stop at filesystem root -- fall back to start dir
        if current == current.parent:
            return original / ALLOWLIST_FILE
        current = current.parent


def load(start: Optional[Path] = None) -> set[str]:
    """Load allowlisted package names. Returns lowercase set."""
    path = _find_allowlist(start)
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.lower())
    return names


def add(name: str, start: Optional[Path] = None) -> Path:
    """Add a package to the allowlist. Creates file if needed. Returns path."""
    path = _find_allowlist(start)
    existing = set()
    if path.exists():
        existing = {
            line.strip().lower()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

    if name.lower() in existing:
        return path

    # Append to file (create with header if new)
    if not path.exists():
        path.write_text(
            "# slopcheck allowlist\n# Add package names here to skip them during scans.\n# One package per line.\n\n",
            encoding="utf-8",
        )

    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}\n")

    return path


def remove(name: str, start: Optional[Path] = None) -> bool:
    """Remove a package from the allowlist. Returns True if found and removed."""
    path = _find_allowlist(start)
    if not path.exists():
        return False

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = []
    found = False
    for line in lines:
        if line.strip().lower() == name.lower():
            found = True
        else:
            new_lines.append(line)

    if found:
        path.write_text("".join(new_lines), encoding="utf-8")
    return found
