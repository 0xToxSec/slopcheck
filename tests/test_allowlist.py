"""Tests for the allowlist module."""

from slopcheck.allowlist import _find_allowlist, add, load, remove


class TestFindAllowlist:
    def test_finds_existing_file(self, tmp_path):
        (tmp_path / ".slopcheck").write_text("# allowlist\nmy-pkg\n")
        result = _find_allowlist(tmp_path)
        assert result == tmp_path / ".slopcheck"
        assert result.exists()

    def test_walks_up_to_git_boundary(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".slopcheck").write_text("# allowlist\n")
        sub = tmp_path / "src" / "app"
        sub.mkdir(parents=True)
        result = _find_allowlist(sub)
        assert result == tmp_path / ".slopcheck"

    def test_defaults_to_start_dir_not_root(self, tmp_path):
        """Without .git boundary, should NOT escape to filesystem root."""
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)
        result = _find_allowlist(sub)
        assert str(result).startswith(str(sub))

    def test_git_boundary_without_file(self, tmp_path):
        """Returns repo root path even if .slopcheck doesn't exist yet."""
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "src"
        sub.mkdir()
        result = _find_allowlist(sub)
        assert result == tmp_path / ".slopcheck"
        assert not result.exists()


class TestLoad:
    def test_loads_names(self, tmp_path):
        (tmp_path / ".slopcheck").write_text("# comment\nmy-pkg\nother-pkg\n")
        (tmp_path / ".git").mkdir()
        result = load(tmp_path)
        assert result == {"my-pkg", "other-pkg"}

    def test_empty_file(self, tmp_path):
        (tmp_path / ".slopcheck").write_text("# just comments\n")
        (tmp_path / ".git").mkdir()
        result = load(tmp_path)
        assert result == set()

    def test_no_file(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = load(tmp_path)
        assert result == set()

    def test_case_normalized(self, tmp_path):
        (tmp_path / ".slopcheck").write_text("My-Package\n")
        (tmp_path / ".git").mkdir()
        result = load(tmp_path)
        assert "my-package" in result


class TestAdd:
    def test_adds_package(self, tmp_path):
        (tmp_path / ".git").mkdir()
        path = add("my-new-pkg", tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "my-new-pkg" in content

    def test_creates_file_with_header(self, tmp_path):
        (tmp_path / ".git").mkdir()
        path = add("first-pkg", tmp_path)
        content = path.read_text()
        assert "# slopcheck allowlist" in content
        assert "first-pkg" in content

    def test_no_duplicate(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".slopcheck").write_text("# header\nexisting-pkg\n")
        add("existing-pkg", tmp_path)
        content = (tmp_path / ".slopcheck").read_text()
        assert content.count("existing-pkg") == 1


class TestRemove:
    def test_removes_package(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".slopcheck").write_text("# header\nmy-pkg\nother-pkg\n")
        result = remove("my-pkg", tmp_path)
        assert result is True
        content = (tmp_path / ".slopcheck").read_text()
        assert "my-pkg" not in content
        assert "other-pkg" in content

    def test_returns_false_if_not_found(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".slopcheck").write_text("# header\n")
        result = remove("nonexistent", tmp_path)
        assert result is False

    def test_returns_false_if_no_file(self, tmp_path):
        (tmp_path / ".git").mkdir()
        result = remove("anything", tmp_path)
        assert result is False
