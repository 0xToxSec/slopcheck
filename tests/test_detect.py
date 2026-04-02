"""Tests for the detection engine."""

from datetime import datetime, timedelta, timezone

from slopcheck.detect import (
    Verdict,
    _check_hallucination_pattern,
    _find_similar,
    _levenshtein,
    analyze,
)
from slopcheck.registries import PackageInfo

# ---------------------------------------------------------------------------
# Levenshtein distance
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("flask", "flask") == 0

    def test_one_edit(self):
        assert _levenshtein("numpy", "numpi") == 1

    def test_two_edits(self):
        assert _levenshtein("requests", "reqeusts") == 2

    def test_empty(self):
        assert _levenshtein("", "hello") == 5

    def test_both_empty(self):
        assert _levenshtein("", "") == 0

    def test_symmetric(self):
        assert _levenshtein("abc", "xyz") == _levenshtein("xyz", "abc")


# ---------------------------------------------------------------------------
# Hallucination pattern detection
# ---------------------------------------------------------------------------


class TestHallucinationPattern:
    def test_suffix_helper(self):
        result = _check_hallucination_pattern("flask-helper")
        assert result is not None
        assert "-helper" in result

    def test_prefix_py(self):
        result = _check_hallucination_pattern("py-requests")
        assert result is not None
        assert "py-" in result

    def test_prefix_easy(self):
        result = _check_hallucination_pattern("easy-abc")
        assert result is not None

    def test_short_remainder_skipped(self):
        """Remainder must be >2 chars to trigger."""
        assert _check_hallucination_pattern("easy-ab") is None
        assert _check_hallucination_pattern("easy-a") is None

    def test_no_pattern(self):
        assert _check_hallucination_pattern("requests") is None
        assert _check_hallucination_pattern("flask") is None

    def test_case_insensitive(self):
        result = _check_hallucination_pattern("Flask-Helper")
        assert result is not None


# ---------------------------------------------------------------------------
# Typosquat / similar package detection
# ---------------------------------------------------------------------------


class TestFindSimilar:
    def test_reqeusts(self):
        assert _find_similar("reqeusts", "pypi") == "requests"

    def test_flak(self):
        assert _find_similar("flak", "pypi") == "flask"

    def test_expresss(self):
        assert _find_similar("expresss", "npm") == "express"

    def test_exact_match_ignored(self):
        """Distance 0 (self) should not be returned, but close neighbors can be."""
        result = _find_similar("flask", "pypi")
        # flask itself (dist 0) is skipped, but "black" (dist 2) is a valid match
        assert result != "flask"

    def test_too_far(self):
        assert _find_similar("zzzzzzzzz", "pypi") is None

    def test_unknown_ecosystem(self):
        assert _find_similar("anything", "unknown") is None


# ---------------------------------------------------------------------------
# Verdict analysis
# ---------------------------------------------------------------------------


class TestAnalyze:
    """Test the full analyze() pipeline."""

    def test_network_error_returns_error_status(self):
        """Network failures must NOT be classified as SLOP."""
        info = PackageInfo(
            name="requests",
            ecosystem="pypi",
            exists=False,
            error="Connection timed out",
        )
        v = analyze(info)
        assert v.status == "ERROR"
        assert v.flags[0].signal == "REGISTRY_ERROR"

    def test_nonexistent_package_is_slop(self):
        info = PackageInfo(name="fake-pkg", ecosystem="pypi", exists=False)
        v = analyze(info)
        assert v.status == "SLOP"
        assert any(f.signal == "NOT_FOUND" for f in v.flags)

    def test_nonexistent_with_hallucination_pattern(self):
        info = PackageInfo(
            name="flask-gpt-helper",
            ecosystem="pypi",
            exists=False,
        )
        v = analyze(info)
        assert v.status == "SLOP"
        assert any(f.signal == "NOT_FOUND" for f in v.flags)
        assert any(f.signal == "HALLUCINATION_PATTERN" for f in v.flags)

    def test_brand_new_package_is_slop(self):
        info = PackageInfo(
            name="sketchy-pkg",
            ecosystem="pypi",
            exists=True,
            created=datetime.now(timezone.utc) - timedelta(days=3),
            downloads=50,
            repo_url=None,
        )
        v = analyze(info)
        assert v.status == "SLOP"
        assert any(f.signal == "BRAND_NEW" for f in v.flags)

    def test_established_package_with_pattern_is_ok(self):
        info = PackageInfo(
            name="python-dateutil",
            ecosystem="pypi",
            exists=True,
            created=datetime.now(timezone.utc) - timedelta(days=3650),
            downloads=50_000_000,
            repo_url="https://github.com/dateutil/dateutil",
        )
        v = analyze(info)
        assert v.status == "OK"

    def test_clean_popular_package_is_ok(self):
        info = PackageInfo(
            name="requests",
            ecosystem="pypi",
            exists=True,
            created=datetime.now(timezone.utc) - timedelta(days=5000),
            downloads=200_000_000,
            repo_url="https://github.com/psf/requests",
        )
        v = analyze(info)
        assert v.status == "OK"
        assert len(v.flags) == 0

    def test_low_downloads_is_sus(self):
        info = PackageInfo(
            name="weird-thing",
            ecosystem="pypi",
            exists=True,
            created=None,
            downloads=50,
            repo_url="https://github.com/x/y",
        )
        v = analyze(info)
        assert v.status == "SUS"
        assert any(f.signal == "GHOST_TOWN" for f in v.flags)

    def test_single_warning_is_sus(self):
        """One warning alone should be SUS, not OK."""
        info = PackageInfo(
            name="weird-thing",
            ecosystem="pypi",
            exists=True,
            created=None,
            downloads=50,
            repo_url="https://github.com/x/y",
        )
        v = analyze(info)
        assert v.status == "SUS"

    def test_suggestion_on_nonexistent_typosquat(self):
        info = PackageInfo(name="reqeusts", ecosystem="pypi", exists=False)
        v = analyze(info)
        assert v.suggestion == "requests"

    def test_no_suggestion_on_clean_package(self):
        info = PackageInfo(
            name="requests",
            ecosystem="pypi",
            exists=True,
            created=datetime.now(timezone.utc) - timedelta(days=5000),
            downloads=200_000_000,
            repo_url="https://github.com/psf/requests",
        )
        v = analyze(info)
        assert v.suggestion is None

    def test_is_bad_property(self):
        slop = Verdict(package="x", ecosystem="pypi", status="SLOP")
        sus = Verdict(package="x", ecosystem="pypi", status="SUS")
        ok = Verdict(package="x", ecosystem="pypi", status="OK")
        err = Verdict(package="x", ecosystem="pypi", status="ERROR")
        assert slop.is_bad is True
        assert sus.is_bad is True
        assert ok.is_bad is False
        assert err.is_bad is False
