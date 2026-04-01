"""Parse dependency files into (ecosystem, package_name) pairs."""

import json
import re
from pathlib import Path
from typing import List, Tuple


def parse_requirements_txt(path: Path) -> List[Tuple[str, str]]:
    """Parse requirements.txt / requirements-dev.txt etc."""
    results = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Skip VCS refs, URLs, local paths, and editable installs
        if (line.startswith(("git+", "hg+", "svn+", "bzr+"))
                or "://" in line
                or line.startswith(("./", "../", "/"))
                or line.startswith("file:")):
            continue
        # Strip version specifiers, extras, environment markers
        name = re.split(r"[>=<!\[;@\s]", line)[0].strip()
        if name:
            results.append(("pypi", name))
    return results


def parse_pyproject_toml(path: Path) -> List[Tuple[str, str]]:
    """Parse pyproject.toml dependencies. Handles PEP 621 and Poetry formats."""
    results = []
    text = path.read_text()

    in_array = False      # inside a [...] array block
    in_optional = False   # inside [project.optional-dependencies]
    in_poetry_deps = False  # inside [tool.poetry.*dependencies]
    in_project = False    # inside [project] section (for catching `dependencies = [`)

    for line in text.splitlines():
        stripped = line.strip()

        # Detect section headers (lines starting with [)
        if stripped.startswith("[") and not stripped.startswith("[["):
            in_array = False
            in_optional = False
            in_poetry_deps = False
            in_project = False

            if stripped == "[project]":
                in_project = True
                continue
            elif stripped == "[project.dependencies]":
                in_array = True
                continue
            elif stripped == "[project.optional-dependencies]":
                in_optional = True
                continue
            elif stripped.startswith("[project.optional-dependencies."):
                # Named extra group as its own table, deps are array items
                in_array = True
                continue
            elif stripped in (
                "[tool.poetry.dependencies]",
                "[tool.poetry.dev-dependencies]",
                "[tool.poetry.group.dev.dependencies]",
            ) or re.match(r'\[tool\.poetry\.group\.\w+\.dependencies\]', stripped):
                in_poetry_deps = True
                continue
            else:
                continue

        # Inside [project], catch `dependencies = [` as start of inline array
        if in_project and stripped.startswith("dependencies") and "=" in stripped:
            match_inline = re.match(r'dependencies\s*=\s*\[', stripped)
            if match_inline:
                # Grab any deps on the same line
                for m in re.finditer(r'["\']([a-zA-Z0-9_.-]+)', stripped):
                    results.append(("pypi", m.group(1)))
                if "]" not in stripped:
                    in_array = True
                continue

        # --- PEP 621 array blocks: lines like "flask>=2.0", ---
        if in_array:
            if stripped == "]":
                in_array = False
                continue
            match = re.match(r'["\']([a-zA-Z0-9_.-]+)', stripped)
            if match:
                results.append(("pypi", match.group(1)))
            continue

        # --- PEP 621 optional-dependencies inline: dev = ["pytest", "black"] ---
        if in_optional:
            # Could be `key = [` (multiline) or `key = ["a", "b"]` (inline)
            inline = re.match(r'\w+\s*=\s*\[', stripped)
            if inline:
                # Grab everything in the brackets on this line
                for m in re.finditer(r'["\']([a-zA-Z0-9_.-]+)', stripped):
                    results.append(("pypi", m.group(1)))
                if "]" not in stripped:
                    in_array = True  # continues on next lines
            continue

        # --- Poetry: key = "^1.0" or key = {version = "^1.0", ...} ---
        if in_poetry_deps:
            if "=" in stripped and not stripped.startswith("#"):
                name = stripped.split("=")[0].strip()
                # Skip the `python` key, it's not a real dep
                if name and name != "python":
                    results.append(("pypi", name))
            continue

    return results


def parse_package_json(path: Path) -> List[Tuple[str, str]]:
    """Parse package.json dependencies + devDependencies."""
    results = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return results
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        deps = data.get(key, {})
        if isinstance(deps, dict):
            for name in deps:
                results.append(("npm", name))
    return results


def parse_cargo_toml(path: Path) -> List[Tuple[str, str]]:
    """Parse Cargo.toml [dependencies], [dev-dependencies], [build-dependencies],
    and dotted table syntax like [dependencies.reqwest]."""
    results = []
    in_deps = False
    dep_sections = {"[dependencies]", "[dev-dependencies]", "[build-dependencies]"}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped in dep_sections:
            in_deps = True
            continue
        # Dotted table: [dependencies.crate-name] or [dev-dependencies.crate-name]
        dotted = re.match(
            r'\[(dependencies|dev-dependencies|build-dependencies)\.([a-zA-Z0-9_-]+)\]',
            stripped,
        )
        if dotted:
            in_deps = False  # stop parsing key=value as deps
            results.append(("crates.io", dotted.group(2)))
            continue
        if stripped.startswith("[") and in_deps:
            in_deps = False
            continue
        if in_deps and "=" in stripped:
            name = stripped.split("=")[0].strip()
            if name and not name.startswith("#"):
                results.append(("crates.io", name))
    return results


def parse_go_mod(path: Path) -> List[Tuple[str, str]]:
    """Parse go.mod require block."""
    results = []
    in_require = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_require = True
            continue
        if stripped == ")" and in_require:
            in_require = False
            continue
        if in_require:
            # Lines look like: github.com/foo/bar v1.2.3
            parts = stripped.split()
            if parts and not parts[0].startswith("//"):
                results.append(("go", parts[0]))
        elif stripped.startswith("require "):
            # Single-line require
            parts = stripped.split()
            if len(parts) >= 2:
                results.append(("go", parts[1]))
    return results


def parse_pipfile(path: Path) -> List[Tuple[str, str]]:
    """Parse Pipfile [packages] and [dev-packages] sections.

    Pipfile is TOML-ish. Each dep is a line like:
        flask = "*"
        requests = {version = ">=2.28", extras = ["security"]}
        django = "~=4.2"
    """
    results = []
    in_packages = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_packages = stripped.lower() in ("[packages]", "[dev-packages]")
            continue
        if in_packages and "=" in stripped and not stripped.startswith("#"):
            name = stripped.split("=")[0].strip()
            # Skip empty names and source/url directives
            if name and not name.startswith("_"):
                results.append(("pypi", name))
    return results


def parse_pipfile_lock(path: Path) -> List[Tuple[str, str]]:
    """Parse Pipfile.lock (JSON). Grabs keys from 'default' and 'develop' sections."""
    results = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return results
    for section in ("default", "develop"):
        pkgs = data.get(section, {})
        if isinstance(pkgs, dict):
            for name in pkgs:
                results.append(("pypi", name))
    return results


def parse_gemfile(path: Path) -> List[Tuple[str, str]]:
    """Parse Ruby Gemfile. Lines like: gem 'rails', '~> 7.0'"""
    results = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Match: gem 'name' or gem "name"
        match = re.match(r'''gem\s+['"]([a-zA-Z0-9_.-]+)['"]''', stripped)
        if match:
            results.append(("rubygems", match.group(1)))
    return results


def parse_pom_xml(path: Path) -> List[Tuple[str, str]]:
    """Parse Maven pom.xml for <dependency> blocks.

    Extracts groupId:artifactId pairs. Simple regex parser -- no XML lib needed
    for our purposes since we just need package names.
    """
    results = []
    text = path.read_text()
    # Find all <dependency> blocks and extract groupId + artifactId
    dep_pattern = re.compile(
        r'<dependency>\s*'
        r'<groupId>([^<]+)</groupId>\s*'
        r'<artifactId>([^<]+)</artifactId>',
        re.DOTALL,
    )
    for m in dep_pattern.finditer(text):
        group_id = m.group(1).strip()
        artifact_id = m.group(2).strip()
        results.append(("maven", f"{group_id}:{artifact_id}"))
    return results


def parse_build_gradle(path: Path) -> List[Tuple[str, str]]:
    """Parse Gradle build.gradle for dependency declarations.

    Handles formats like:
        implementation 'group:artifact:version'
        implementation "group:artifact:version"
        implementation group: 'com.google', name: 'guava', version: '31.0'
    """
    results = []
    dep_configs = (
        "implementation", "api", "compileOnly", "runtimeOnly",
        "testImplementation", "testCompileOnly", "testRuntimeOnly",
        "annotationProcessor", "compile", "testCompile",
    )
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        for config in dep_configs:
            if stripped.startswith(config):
                # Format: implementation 'group:artifact:version'
                match = re.search(r'''['"]([^'"]+:[^'"]+:[^'"]+)['"]''', stripped)
                if match:
                    parts = match.group(1).split(":")
                    if len(parts) >= 2:
                        results.append(("maven", f"{parts[0]}:{parts[1]}"))
                    break
                # Format: implementation group: 'x', name: 'y', version: 'z'
                group_match = re.search(r'''group:\s*['"]([^'"]+)['"]''', stripped)
                name_match = re.search(r'''name:\s*['"]([^'"]+)['"]''', stripped)
                if group_match and name_match:
                    results.append(("maven", f"{group_match.group(1)}:{name_match.group(1)}"))
                break
    return results


def parse_composer_json(path: Path) -> List[Tuple[str, str]]:
    """Parse PHP composer.json require/require-dev."""
    results = []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return results
    for key in ("require", "require-dev"):
        deps = data.get(key, {})
        if isinstance(deps, dict):
            for name in deps:
                # Skip php itself and ext-* extensions
                if name == "php" or name.startswith("ext-"):
                    continue
                results.append(("packagist", name))
    return results


# Map filenames to parsers
FILE_PARSERS = {
    "requirements.txt": parse_requirements_txt,
    "requirements-dev.txt": parse_requirements_txt,
    "requirements_dev.txt": parse_requirements_txt,
    "pyproject.toml": parse_pyproject_toml,
    "package.json": parse_package_json,
    "Cargo.toml": parse_cargo_toml,
    "go.mod": parse_go_mod,
    "Pipfile": parse_pipfile,
    "Pipfile.lock": parse_pipfile_lock,
    "Gemfile": parse_gemfile,
    "pom.xml": parse_pom_xml,
    "build.gradle": parse_build_gradle,
    "composer.json": parse_composer_json,
}


def auto_detect(directory: Path) -> List[Tuple[str, str]]:
    """Scan a directory for known dependency files and parse them all."""
    results = []
    for filename, parser in FILE_PARSERS.items():
        filepath = directory / filename
        if filepath.exists():
            results.extend(parser(filepath))
    return results
