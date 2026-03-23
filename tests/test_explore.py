"""Tests for explore filter construction and name validation."""

from __future__ import annotations

import csv
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from scholaraio.explore import _build_filter, build_explore_vectors, explore_search, fetch_explore, import_explore, iter_papers


def _make_cfg(tmp_path):
    cfg = MagicMock()
    cfg._root = tmp_path
    return cfg


class TestBuildFilter:
    def test_min_citations_positive_adds_filter(self):
        filt, _ = _build_filter(min_citations=10)
        assert "cited_by_count:>9" in filt

    def test_min_citations_zero_or_negative_ignored(self):
        filt_zero, _ = _build_filter(min_citations=0)
        filt_negative, _ = _build_filter(min_citations=-3)
        assert "cited_by_count" not in filt_zero
        assert "cited_by_count" not in filt_negative


class TestFetchExploreLimit:
    def test_limit_must_be_positive(self):
        with pytest.raises(ValueError, match="limit 必须为正整数"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=0)

        with pytest.raises(ValueError, match="limit 必须为正整数"):
            fetch_explore("tmp-limit-check", issn="0022-1120", limit=-1)


class TestImportExplore:
    def test_import_csv_creates_local_explore_library(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        csv_path = tmp_path / "ideas.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["title", "abstract", "authors", "download_url"])
            writer.writeheader()
            writer.writerow(
                {
                    "title": "Interactive Storytelling for Climate Data",
                    "abstract": "We study storytelling interfaces for climate communication.",
                    "authors": "Alice Smith; Bob Lee",
                    "download_url": "https://example.com/p1.pdf",
                }
            )
            writer.writerow(
                {
                    "title": "Visual Analytics for Scientific Workflows",
                    "abstract": "This paper presents a workflow analytics system.",
                    "authors": "Carol Chen",
                    "download_url": "https://example.com/p2.pdf",
                }
            )

        count = import_explore("idea-archive", csv_path, cfg=cfg)

        assert count == 2
        records = list(iter_papers("idea-archive", cfg))
        assert len(records) == 2
        assert records[0]["paper_id"].startswith("local:")
        assert records[0]["download_url"] == "https://example.com/p1.pdf"

    def test_local_records_without_doi_can_build_vectors_and_search(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        csv_path = tmp_path / "ideas.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["title", "abstract", "authors"])
            writer.writeheader()
            writer.writerow(
                {
                    "title": "Chart Understanding with Language Models",
                    "abstract": "Language models can reason about charts and tables.",
                    "authors": "Alice Smith",
                }
            )
            writer.writerow(
                {
                    "title": "Immersive Analytics for Collaboration",
                    "abstract": "We explore immersive collaboration around complex data.",
                    "authors": "Bob Lee",
                }
            )

        import_explore("local-metadata", csv_path, cfg=cfg)

        with (
            patch("scholaraio.vectors._load_model", return_value=None),
            patch("scholaraio.vectors._embed_batch", return_value=[[1.0, 0.0], [0.0, 1.0]]),
        ):
            embedded = build_explore_vectors("local-metadata", cfg=cfg)

        assert embedded == 2
        with sqlite3.connect(str(tmp_path / "data" / "explore" / "local-metadata" / "explore.db")) as conn:
            rows = conn.execute("SELECT paper_id FROM paper_vectors ORDER BY paper_id").fetchall()
        assert len(rows) == 2
        assert rows[0][0].startswith("local:")

        results = explore_search("local-metadata", "language", cfg=cfg)
        assert results
        assert results[0]["title"] == "Chart Understanding with Language Models"
