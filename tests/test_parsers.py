"""Tests for dependency file parsers."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from slopcheck.parsers import (
    auto_detect,
    parse_cargo_toml,
    parse_composer_json,
    parse_gemfile,
    parse_go_mod,
    parse_package_json,
    parse_pipfile,
    parse_pipfile_lock,
    parse_pyproject_toml,
    parse_requirements_txt,
)


def _tmpfile(content: str, suffix: str = ".txt") -> Path:
    """Write content to a temp file and return the path."""
    p = Path(tempfile.mktemp(suffix=suffix))
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# requirements.txt
# ---------------------------------------------------------------------------

class TestRequirementsTxt:
    def test_basic_packages(self):
        p = _tmpfile("flask>=2.0\nrequests\nnumpy>=1.21\n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert names == ["flask", "requests", "numpy"]

    def test_comments_and_blanks(self):
        p = _tmpfile("# comment\n\nflask\n  \n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert len(result) == 1
        assert result[0] == ("pypi", "flask")

    def test_flags_skipped(self):
        p = _tmpfile("-r base.txt\n--index-url https://pypi.org\nflask\n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "flask")]

    def test_git_urls_skipped(self):
        p = _tmpfile(
            "flask\n"
            "git+https://github.com/foo/bar.git\n"
            "git+https://github.com/foo/bar.git@v1.0#egg=bar\n"
            "requests\n"
        )
        result = parse_requirements_txt(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert names == ["flask", "requests"]

    def test_vcs_urls_skipped(self):
        p = _tmpfile(
            "hg+https://example.com/repo\n"
            "svn+https://example.com/repo\n"
            "bzr+https://example.com/repo\n"
            "flask\n"
        )
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "flask")]

    def test_http_urls_skipped(self):
        p = _tmpfile("https://example.com/my-package.whl\nflask\n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "flask")]

    def test_local_paths_skipped(self):
        p = _tmpfile("./local-package\n../relative-package\n/absolute/path\nflask\n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "flask")]

    def test_file_urls_skipped(self):
        p = _tmpfile("file:///absolute-path\nflask\n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "flask")]

    def test_extras_stripped(self):
        p = _tmpfile("requests[security]\n")
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "requests")]

    def test_env_markers_stripped(self):
        p = _tmpfile('numpy ; python_version >= "3.8"\n')
        result = parse_requirements_txt(p)
        os.unlink(p)
        assert result == [("pypi", "numpy")]


# ---------------------------------------------------------------------------
# pyproject.toml
# ---------------------------------------------------------------------------

class TestPyprojectToml:
    def test_inline_array(self):
        p = _tmpfile(
            '[project]\nname = "test"\n'
            'dependencies = [\n    "flask>=2.0",\n    "requests",\n]\n',
            suffix=".toml",
        )
        result = parse_pyproject_toml(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "flask" in names
        assert "requests" in names

    def test_single_line_array(self):
        p = _tmpfile(
            '[project]\nname = "test"\ndependencies = ["flask", "requests"]\n',
            suffix=".toml",
        )
        result = parse_pyproject_toml(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert names == ["flask", "requests"]

    def test_optional_dependencies(self):
        p = _tmpfile(
            '[project.optional-dependencies]\ndev = ["pytest", "black"]\n',
            suffix=".toml",
        )
        result = parse_pyproject_toml(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "pytest" in names
        assert "black" in names

    def test_poetry_format(self):
        p = _tmpfile(
            '[tool.poetry.dependencies]\n'
            'python = "^3.9"\n'
            'flask = "^2.0"\n'
            'requests = {version = ">=2.28"}\n\n'
            '[tool.poetry.dev-dependencies]\n'
            'pytest = "^7.0"\n',
            suffix=".toml",
        )
        result = parse_pyproject_toml(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "flask" in names
        assert "requests" in names
        assert "pytest" in names
        assert "python" not in names

    def test_build_system_not_included(self):
        p = _tmpfile(
            '[build-system]\n'
            'requires = ["setuptools>=68.0", "wheel"]\n\n'
            '[project]\ndependencies = ["flask"]\n',
            suffix=".toml",
        )
        result = parse_pyproject_toml(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "flask" in names
        assert "setuptools" not in names
        assert "wheel" not in names

    def test_no_deps_key(self):
        p = _tmpfile('[project]\nname = "test"\nversion = "1.0"\n', suffix=".toml")
        result = parse_pyproject_toml(p)
        os.unlink(p)
        assert result == []


# ---------------------------------------------------------------------------
# Cargo.toml
# ---------------------------------------------------------------------------

class TestCargoToml:
    def test_basic_deps(self):
        p = _tmpfile(
            '[dependencies]\nserde = "1.0"\ntokio = "1.0"\n',
            suffix=".toml",
        )
        result = parse_cargo_toml(p)
        os.unlink(p)
        names = sorted([name for _, name in result])
        assert "serde" in names
        assert "tokio" in names

    def test_dev_dependencies(self):
        p = _tmpfile('[dev-dependencies]\ncriterion = "0.4"\n', suffix=".toml")
        result = parse_cargo_toml(p)
        os.unlink(p)
        assert ("crates.io", "criterion") in result

    def test_build_dependencies(self):
        p = _tmpfile('[build-dependencies]\ncc = "1.0"\n', suffix=".toml")
        result = parse_cargo_toml(p)
        os.unlink(p)
        assert ("crates.io", "cc") in result

    def test_dotted_table(self):
        p = _tmpfile(
            '[dependencies.reqwest]\nversion = "0.11"\nfeatures = ["json"]\n',
            suffix=".toml",
        )
        result = parse_cargo_toml(p)
        os.unlink(p)
        assert ("crates.io", "reqwest") in result

    def test_inline_table(self):
        p = _tmpfile(
            '[dependencies]\nserde = { version = "1.0", features = ["derive"] }\n',
            suffix=".toml",
        )
        result = parse_cargo_toml(p)
        os.unlink(p)
        assert ("crates.io", "serde") in result

    def test_full_cargo_toml(self):
        p = _tmpfile(
            '[package]\nname = "myapp"\n\n'
            '[dependencies]\nserde = "1.0"\ntokio = "1.0"\n\n'
            '[build-dependencies]\ncc = "1.0"\n\n'
            '[dev-dependencies]\ncriterion = "0.4"\n\n'
            '[dependencies.reqwest]\nversion = "0.11"\n',
            suffix=".toml",
        )
        result = parse_cargo_toml(p)
        os.unlink(p)
        names = sorted([name for _, name in result])
        assert names == ["cc", "criterion", "reqwest", "serde", "tokio"]


# ---------------------------------------------------------------------------
# package.json
# ---------------------------------------------------------------------------

class TestPackageJson:
    def test_all_dep_types(self):
        data = {
            "dependencies": {"express": "^4.0"},
            "devDependencies": {"jest": "^29.0"},
            "peerDependencies": {"react": "^18.0"},
        }
        p = _tmpfile(json.dumps(data), suffix=".json")
        result = parse_package_json(p)
        os.unlink(p)
        names = sorted([name for _, name in result])
        assert names == ["express", "jest", "react"]

    def test_scoped_packages(self):
        data = {"dependencies": {"@types/node": "^18.0", "@angular/core": "^16.0"}}
        p = _tmpfile(json.dumps(data), suffix=".json")
        result = parse_package_json(p)
        os.unlink(p)
        names = sorted([name for _, name in result])
        assert "@angular/core" in names
        assert "@types/node" in names

    def test_invalid_json(self):
        p = _tmpfile("not json at all", suffix=".json")
        result = parse_package_json(p)
        os.unlink(p)
        assert result == []


# ---------------------------------------------------------------------------
# go.mod
# ---------------------------------------------------------------------------

class TestGoMod:
    def test_multiline_require(self):
        p = _tmpfile(
            'module github.com/org/app\n\ngo 1.21\n\n'
            'require (\n'
            '\tgithub.com/gin-gonic/gin v1.9.1\n'
            '\tgithub.com/stretchr/testify v1.8.4 // indirect\n'
            ')\n',
            suffix=".mod",
        )
        result = parse_go_mod(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "github.com/gin-gonic/gin" in names
        assert "github.com/stretchr/testify" in names

    def test_single_require(self):
        p = _tmpfile(
            "module example.com/app\n\nrequire github.com/spf13/cobra v1.7.0\n",
            suffix=".mod",
        )
        result = parse_go_mod(p)
        os.unlink(p)
        assert ("go", "github.com/spf13/cobra") in result


# ---------------------------------------------------------------------------
# Gemfile
# ---------------------------------------------------------------------------

class TestGemfile:
    def test_basic_gems(self):
        p = _tmpfile("gem 'rails', '~> 7.0'\ngem \"devise\"\n", suffix="")
        result = parse_gemfile(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "rails" in names
        assert "devise" in names

    def test_comments_skipped(self):
        p = _tmpfile("# gem 'evil'\ngem 'good'\n", suffix="")
        result = parse_gemfile(p)
        os.unlink(p)
        assert result == [("rubygems", "good")]


# ---------------------------------------------------------------------------
# composer.json
# ---------------------------------------------------------------------------

class TestComposerJson:
    def test_require(self):
        data = {
            "require": {"php": "^8.1", "laravel/framework": "^10.0", "ext-json": "*"},
            "require-dev": {"phpunit/phpunit": "^10.0"},
        }
        p = _tmpfile(json.dumps(data), suffix=".json")
        result = parse_composer_json(p)
        os.unlink(p)
        names = [name for _, name in result]
        assert "laravel/framework" in names
        assert "phpunit/phpunit" in names
        # php and ext-* should be excluded
        assert "php" not in names
        assert "ext-json" not in names


# ---------------------------------------------------------------------------
# auto_detect
# ---------------------------------------------------------------------------

class TestAutoDetect:
    def test_finds_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\nrequests\n")
        result = auto_detect(tmp_path)
        assert len(result) == 2

    def test_empty_dir(self, tmp_path):
        result = auto_detect(tmp_path)
        assert result == []

    def test_multiple_files(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\n")
        (tmp_path / "package.json").write_text(
            json.dumps({"dependencies": {"express": "^4.0"}})
        )
        result = auto_detect(tmp_path)
        ecosystems = {eco for eco, _ in result}
        assert "pypi" in ecosystems
        assert "npm" in ecosystems
