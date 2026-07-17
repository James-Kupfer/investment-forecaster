"""
Unit tests for scripts/sync_prompts.py's pure content-hashing logic
(no DB -- sync() itself is exercised via manual/live runs, not here).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_prompts import _content_version


class TestContentVersion:
    def test_deterministic_for_identical_content(self):
        assert _content_version("some prompt text") == _content_version("some prompt text")

    def test_differs_for_different_content(self):
        assert _content_version("prompt A") != _content_version("prompt B")

    def test_sensitive_to_whitespace_only_changes(self):
        # A version marker can be re-bumped without the author noticing it
        # didn't actually change; a content hash must not have that gap --
        # even a whitespace-only edit should produce a different label.
        assert _content_version("line one\nline two") != _content_version("line one\n\nline two")

    def test_fits_prompt_version_column_width(self):
        # prompt_registry.prompt_version is VARCHAR(20).
        assert len(_content_version("anything")) <= 20

    def test_starts_with_hash_prefix(self):
        assert _content_version("anything").startswith("h-")
