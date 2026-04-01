"""Tests for CLI helpers (non-network, non-subprocess)."""

import io
import sys

from slopcheck import __version__
from slopcheck.cli import (
    C,
    _status_badge,
    _severity_color,
    print_verdict,
    print_summary,
)
from slopcheck.detect import Flag, Verdict


class TestStatusBadge:
    def test_slop(self):
        badge = _status_badge("SLOP")
        assert "SLOP" in badge

    def test_sus(self):
        badge = _status_badge("SUS")
        assert "SUS" in badge

    def test_error(self):
        badge = _status_badge("ERROR")
        assert "ERR" in badge

    def test_ok(self):
        badge = _status_badge("OK")
        assert "OK" in badge


class TestSeverityColor:
    def test_critical(self):
        assert _severity_color("critical") == C.RED

    def test_warning(self):
        assert _severity_color("warning") == C.YELLOW

    def test_error(self):
        assert _severity_color("error") == C.YELLOW

    def test_info(self):
        assert _severity_color("info") == C.DIM


class TestPrintVerdict:
    def test_output_contains_all_parts(self):
        """print_verdict should emit package name, flags, and suggestion."""
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        v = Verdict(
            package="test-pkg",
            ecosystem="pypi",
            status="SLOP",
            flags=[Flag("NOT_FOUND", "critical", "Does not exist on pypi")],
            suggestion="test",
        )
        print_verdict(v)
        sys.stdout = old_stdout
        output = buf.getvalue()
        assert "test-pkg" in output
        assert "SLOP" in output
        assert "Does not exist" in output
        assert "test" in output

    def test_no_suggestion(self):
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        v = Verdict(
            package="clean",
            ecosystem="npm",
            status="OK",
            flags=[],
        )
        print_verdict(v)
        sys.stdout = old_stdout
        output = buf.getvalue()
        assert "clean" in output
        assert "Did you mean" not in output


class TestVersion:
    def test_version_string(self):
        assert __version__ == "0.5.0"
