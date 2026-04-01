"""Fix dependency files by commenting out or removing bad packages."""

import json
import re
from pathlib import Path
from typing import Callable


def _comment_lines(path: Path, bad_names: set[str], comment_char: str = "#") -> int:
    """Comment out lines in a text file that contain a bad package name.

    Works for: requirements.txt, Pipfile, Cargo.toml, go.mod.
    Returns the number of lines commented out.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    count = 0
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip already-commented or empty lines
        if not stripped or stripped.startswith(comment_char):
            new_lines.append(line)
            continue
        # Extract the package name (first token before any = > < [ ; @ space)
        token = re.split(r"[>=<!\[;@\s=\"\']", stripped)[0].strip()
        if token.lower() in bad_names:
            # Comment it out with a reason
            new_lines.append(f"{comment_char} [slopcheck] removed: {line.rstrip()}\n")
            count += 1
        else:
            new_lines.append(line)
    if count:
        path.write_text("".join(new_lines), encoding="utf-8")
    return count


def _fix_requirements_txt(path: Path, bad_names: set[str]) -> int:
    """Comment out bad packages in requirements.txt."""
    return _comment_lines(path, bad_names, "#")


def _fix_pipfile(path: Path, bad_names: set[str]) -> int:
    """Comment out bad packages in Pipfile."""
    return _comment_lines(path, bad_names, "#")


def _fix_cargo_toml(path: Path, bad_names: set[str]) -> int:
    """Comment out bad packages in Cargo.toml."""
    return _comment_lines(path, bad_names, "#")


def _fix_go_mod(path: Path, bad_names: set[str]) -> int:
    """Comment out bad packages in go.mod."""
    return _comment_lines(path, bad_names, "//")


def _fix_pyproject_toml(path: Path, bad_names: set[str]) -> int:
    """Remove bad packages from pyproject.toml (PEP 621 arrays + Poetry keys)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    count = 0
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # Check quoted strings in array lines: "flask>=2.0",
        match = re.match(r'["\']([a-zA-Z0-9_.-]+)', stripped)
        if match and match.group(1).lower() in bad_names:
            new_lines.append(f"    # [slopcheck] removed: {line.rstrip()}\n")
            count += 1
            continue
        # Check Poetry-style key = value lines
        if "=" in stripped and not stripped.startswith("#") and not stripped.startswith("["):
            key = stripped.split("=")[0].strip()
            if key.lower() in bad_names:
                new_lines.append(f"# [slopcheck] removed: {line.rstrip()}\n")
                count += 1
                continue
        new_lines.append(line)
    if count:
        path.write_text("".join(new_lines), encoding="utf-8")
    return count


def _fix_package_json(path: Path, bad_names: set[str]) -> int:
    """Remove bad packages from package.json."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    count = 0
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(section, {})
        if isinstance(deps, dict):
            to_remove = [k for k in deps if k.lower() in bad_names]
            for k in to_remove:
                del deps[k]
                count += 1
    if count:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return count


def _fix_pipfile_lock(path: Path, bad_names: set[str]) -> int:
    """Remove bad packages from Pipfile.lock."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    count = 0
    for section in ("default", "develop"):
        pkgs = data.get(section, {})
        if isinstance(pkgs, dict):
            to_remove = [k for k in pkgs if k.lower() in bad_names]
            for k in to_remove:
                del pkgs[k]
                count += 1
    if count:
        path.write_text(json.dumps(data, indent=4, sort_keys=True) + "\n", encoding="utf-8")
    return count


def _fix_gemfile(path: Path, bad_names: set[str]) -> int:
    """Comment out bad gems in Gemfile."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    count = 0
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            new_lines.append(line)
            continue
        match = re.match(r"""gem\s+['"]([a-zA-Z0-9_.-]+)['"]""", stripped)
        if match and match.group(1).lower() in bad_names:
            new_lines.append(f"# [slopcheck] removed: {line.rstrip()}\n")
            count += 1
        else:
            new_lines.append(line)
    if count:
        path.write_text("".join(new_lines), encoding="utf-8")
    return count


def _fix_pom_xml(path: Path, bad_names: set[str]) -> int:
    """Comment out bad dependencies in pom.xml."""
    text = path.read_text(encoding="utf-8")
    count = 0
    dep_pattern = re.compile(
        r"(\s*<dependency>\s*"
        r"<groupId>([^<]+)</groupId>\s*"
        r"<artifactId>([^<]+)</artifactId>"
        r".*?</dependency>)",
        re.DOTALL,
    )

    def replacer(m):
        nonlocal count
        group_id = m.group(2).strip()
        artifact_id = m.group(3).strip()
        full_name = f"{group_id}:{artifact_id}".lower()
        if full_name in bad_names:
            count += 1
            return f"<!-- [slopcheck] removed:\n{m.group(0)}\n-->"
        return m.group(0)

    new_text = dep_pattern.sub(replacer, text)
    if count:
        path.write_text(new_text, encoding="utf-8")
    return count


def _fix_composer_json(path: Path, bad_names: set[str]) -> int:
    """Remove bad packages from composer.json."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    count = 0
    for section in ("require", "require-dev"):
        deps = data.get(section, {})
        if isinstance(deps, dict):
            to_remove = [k for k in deps if k.lower() in bad_names]
            for k in to_remove:
                del deps[k]
                count += 1
    if count:
        path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
    return count


# Map filenames to fixers
FILE_FIXERS: dict[str, Callable] = {
    "requirements.txt": _fix_requirements_txt,
    "requirements-dev.txt": _fix_requirements_txt,
    "requirements_dev.txt": _fix_requirements_txt,
    "pyproject.toml": _fix_pyproject_toml,
    "package.json": _fix_package_json,
    "Cargo.toml": _fix_cargo_toml,
    "go.mod": _fix_go_mod,
    "Pipfile": _fix_pipfile,
    "Pipfile.lock": _fix_pipfile_lock,
    "Gemfile": _fix_gemfile,
    "pom.xml": _fix_pom_xml,
    "composer.json": _fix_composer_json,
}


def fix_directory(directory: Path, bad_packages: list[str]) -> dict[str, int]:
    """Remove bad packages from all dependency files in a directory.

    Returns a dict of {filename: count_removed}.
    """
    bad_names = {p.lower() for p in bad_packages}
    results = {}
    for filename, fixer in FILE_FIXERS.items():
        filepath = directory / filename
        if filepath.exists():
            count = fixer(filepath, bad_names)
            if count:
                results[filename] = count
    return results


def fix_file(filepath: Path, bad_packages: list[str]) -> int:
    """Remove bad packages from a specific dependency file.

    Returns the count of packages removed.
    """
    bad_names = {p.lower() for p in bad_packages}
    name = filepath.name
    fixer = FILE_FIXERS.get(name)
    if not fixer:
        # Try matching requirements-*.txt pattern
        if "requirements" in name and name.endswith(".txt"):
            fixer = _fix_requirements_txt
        else:
            return 0
    return fixer(filepath, bad_names)
