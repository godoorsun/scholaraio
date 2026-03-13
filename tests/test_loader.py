"""Contract tests for the L1-L2 layer loading system.

Verifies: each layer returns the documented fields from well-formed data.
Does NOT test: internal JSON parsing details, LLM enrichment paths, or L3/L4
layers that require LLM enrichment or full-text paper files.
"""

from __future__ import annotations

import json
from typing import cast

from scholaraio.config import Config
from scholaraio.loader import L3_SKIP_TYPES, enrich_l3, load_l1, load_l2

# enrich_l3 requires a Config argument but the skip-by-type branch
# returns before it is used.  We use a typed sentinel so mypy is happy.
_UNUSED_CONFIG = cast(Config, None)


class TestLoadL1:
    """L1 contract: returns metadata dict with documented keys."""

    def test_returns_expected_keys(self, tmp_papers):
        json_path = tmp_papers / "Smith-2023-Turbulence" / "meta.json"
        result = load_l1(json_path)

        assert result["paper_id"] == "aaaa-1111"
        assert result["title"] == "Turbulence modeling in boundary layers"
        assert isinstance(result["authors"], list)
        assert result["year"] == 2023
        assert result["journal"] == "Journal of Fluid Mechanics"
        assert result["doi"] == "10.1234/jfm.2023.001"

    def test_missing_fields_have_safe_defaults(self, tmp_path):
        """Minimal JSON should not crash — missing fields get defaults."""
        d = tmp_path / "Bare-2000-Minimal"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"id": "min-id"}))

        result = load_l1(d / "meta.json")
        assert result["paper_id"] == "min-id"
        assert result["title"] == ""
        assert result["authors"] == []
        assert result["year"] is None


class TestLoadL2:
    """L2 contract: returns abstract string."""

    def test_returns_abstract(self, tmp_papers):
        json_path = tmp_papers / "Smith-2023-Turbulence" / "meta.json"
        assert "novel turbulence model" in load_l2(json_path)

    def test_missing_abstract_returns_placeholder(self, tmp_path):
        d = tmp_path / "NoAbstract"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": "x"}))

        result = load_l2(d / "meta.json")
        assert "No abstract" in result


class TestEnrichL3Skip:
    """enrich_l3 skips non-article paper types and writes a marker."""

    def test_skips_thesis(self, tmp_papers):
        """Thesis paper_type should be skipped without any LLM call."""
        json_path = tmp_papers / "Wang-2024-DeepLearning" / "meta.json"
        md_path = json_path.parent / "paper.md"

        # config=_UNUSED_CONFIG is fine because the skip happens before config is used
        result = enrich_l3(json_path, md_path, config=_UNUSED_CONFIG)

        assert result is True
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["l3_extraction_method"] == "skipped"
        assert "l3_extracted_at" in data
        assert "l3_conclusion" not in data

    def test_skips_book(self, tmp_path):
        """Book paper_type should be skipped."""
        d = tmp_path / "Author-2020-Handbook"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(
            json.dumps({"id": "book-1", "paper_type": "book"}),
            encoding="utf-8",
        )
        (d / "paper.md").write_text("# Handbook\n\nContent.", encoding="utf-8")

        result = enrich_l3(d / "meta.json", d / "paper.md", config=_UNUSED_CONFIG)

        assert result is True
        data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        assert data["l3_extraction_method"] == "skipped"

    def test_skip_types_coverage(self):
        """All documented skip types are present in the set."""
        for t in ("thesis", "book", "monograph", "document", "dissertation"):
            assert t in L3_SKIP_TYPES
