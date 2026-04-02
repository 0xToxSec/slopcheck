"""Tests for the fixer module."""

import json
import os
import tempfile
from pathlib import Path

from slopcheck.fixer import (
    _comment_lines,
    _fix_package_json,
    _fix_pyproject_toml,
    fix_directory,
    fix_file,
)


def _tmpfile(content: str, suffix: str = ".txt") -> Path:
    """Write content to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w") as f:
        f.write(content)
    return Path(f.name)


class TestCommentLines:
    def test_comments_out_bad_packages(self):
        p = _tmpfile("flask>=2.0\nbad-package==1.0\nrequests\n")
        count = _comment_lines(p, {"bad-package"})
        result = p.read_text()
        os.unlink(p)
        assert count == 1
        assert "# [slopcheck] removed:" in result
        assert "flask" in result
        assert "requests" in result

    def test_skips_already_commented(self):
        p = _tmpfile("# already commented\nflask\n")
        count = _comment_lines(p, {"flask"})
        os.unlink(p)
        assert count == 1  # flask gets commented

    def test_no_changes_when_clean(self):
        content = "flask>=2.0\nrequests\n"
        p = _tmpfile(content)
        count = _comment_lines(p, {"nonexistent"})
        result = p.read_text()
        os.unlink(p)
        assert count == 0
        assert result == content  # file unchanged

    def test_case_insensitive(self):
        p = _tmpfile("Flask>=2.0\n")
        count = _comment_lines(p, {"flask"})
        os.unlink(p)
        assert count == 1


class TestFixPackageJson:
    def test_removes_bad_deps(self):
        data = {
            "name": "myapp",
            "dependencies": {"express": "^4.0", "bad-pkg": "^1.0", "lodash": "^4.0"},
            "devDependencies": {"jest": "^29.0"},
        }
        p = _tmpfile(json.dumps(data, indent=2), suffix=".json")
        count = _fix_package_json(p, {"bad-pkg"})
        result = json.loads(p.read_text())
        os.unlink(p)
        assert count == 1
        assert "bad-pkg" not in result["dependencies"]
        assert "express" in result["dependencies"]
        assert "lodash" in result["dependencies"]

    def test_no_changes_when_clean(self):
        data = {"dependencies": {"express": "^4.0"}}
        original = json.dumps(data, indent=2)
        p = _tmpfile(original, suffix=".json")
        count = _fix_package_json(p, {"nonexistent"})
        os.unlink(p)
        assert count == 0


class TestFixPyprojectToml:
    def test_comments_out_array_deps(self):
        content = (
            '[project]\nname = "test"\n'
            "dependencies = [\n"
            '    "flask>=2.0",\n'
            '    "bad-package==1.0",\n'
            '    "requests",\n'
            "]\n"
        )
        p = _tmpfile(content, suffix=".toml")
        count = _fix_pyproject_toml(p, {"bad-package"})
        result = p.read_text()
        os.unlink(p)
        assert count == 1
        assert "# [slopcheck] removed:" in result
        assert '"flask' in result
        assert '"requests' in result


class TestFixFile:
    def test_fix_requirements_txt(self, tmp_path):
        f = tmp_path / "requirements.txt"
        f.write_text("flask\nbad-pkg\nrequests\n")
        count = fix_file(f, ["bad-pkg"])
        assert count == 1
        assert "# [slopcheck] removed:" in f.read_text()

    def test_unsupported_file_returns_zero(self, tmp_path):
        f = tmp_path / "unknown.xyz"
        f.write_text("whatever\n")
        count = fix_file(f, ["anything"])
        assert count == 0

    def test_requirements_variant_name(self, tmp_path):
        f = tmp_path / "requirements-prod.txt"
        f.write_text("flask\nbad-pkg\n")
        count = fix_file(f, ["bad-pkg"])
        assert count == 1


class TestFixDirectory:
    def test_fixes_multiple_files(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\nbad-pkg\n")
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"bad-pkg": "^1.0", "express": "^4.0"}}))
        results = fix_directory(tmp_path, ["bad-pkg"])
        assert results.get("requirements.txt", 0) == 1
        assert results.get("package.json", 0) == 1

    def test_empty_dir(self, tmp_path):
        results = fix_directory(tmp_path, ["bad-pkg"])
        assert results == {}
