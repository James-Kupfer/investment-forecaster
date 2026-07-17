"""
Unit tests for scripts/sync_prompts.py's pure parsing/versioning logic
(no DB -- sync() itself is exercised via manual/live runs, not here).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_prompts import _extract_version, _next_version


class TestExtractVersion:
    def test_top_of_file_marker(self):
        assert _extract_version("# agent\n## Version: 2.5\n\nbody") == "2.5"

    def test_bottom_of_file_marker(self):
        assert _extract_version("body\n<version>\n2.4\n</version>") == "2.4"

    def test_bottom_of_file_marker_with_v_prefix(self):
        # aggregation.md uses "v2.5" while every other file uses a bare number.
        assert _extract_version("body\n<version>\nv2.5\n</version>") == "2.5"

    def test_no_marker_returns_none(self):
        assert _extract_version("no version info here") is None

    def test_top_marker_takes_precedence_over_bottom(self):
        text = "## Version: 2.5\n\nbody\n<version>\n2.4\n</version>"
        assert _extract_version(text) == "2.5"


class TestNextVersion:
    def test_bumps_minor_version(self):
        assert _next_version("v2.4") == "v2.5"

    def test_no_current_version_defaults_to_v1_1(self):
        assert _next_version(None) == "v1.1"

    def test_unparseable_current_version_defaults_to_v1_1(self):
        assert _next_version("not-a-version") == "v1.1"
