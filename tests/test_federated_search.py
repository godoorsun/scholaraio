"""Contract tests for the federated_search MCP tool.

Stubs out unified_search, explore_unified_search, and search_arxiv so tests
run without any index files, network access, or external dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAIN_PAPER = {"title": "Attention Is All You Need", "doi": "10.1234/attn", "score": 0.9}
_EXPLORE_PAPER = {"title": "BERT Pre-training", "doi": "10.5678/bert", "score": 0.8}
_ARXIV_PAPER = {
    "title": "New Transformer",
    "authors": ["Alice"],
    "year": "2024",
    "abstract": "...",
    "arxiv_id": "2401.00001",
    "doi": "10.9999/new",
}


def _make_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.index_db = tmp_path / "index.db"
    cfg.papers_dir = tmp_path / "papers"
    return cfg


# ---------------------------------------------------------------------------
# Tests: main scope
# ---------------------------------------------------------------------------


class TestFederatedSearchMain:
    def test_main_returns_results(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.index.unified_search", return_value=[_MAIN_PAPER]) as mock_us,
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("attention", scope="main", top_k=5))

        assert "main" in result
        assert result["main"][0]["title"] == "Attention Is All You Need"
        mock_us.assert_called_once()

    def test_main_index_not_found(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.index.unified_search", side_effect=FileNotFoundError),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("attention", scope="main"))

        assert result["main"] == [{"error": "index_not_found"}]

    def test_main_generic_error(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.index.unified_search", side_effect=RuntimeError("boom")),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("attention", scope="main"))

        assert result["main"][0]["error"] == "boom"


# ---------------------------------------------------------------------------
# Tests: explore scope
# ---------------------------------------------------------------------------


class TestFederatedSearchExplore:
    def test_explore_named_silo(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        fake_db = tmp_path / "explore.db"
        fake_db.touch()

        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.explore._db_path", return_value=fake_db),
            patch("scholaraio.explore.explore_unified_search", return_value=[_EXPLORE_PAPER]),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("bert", scope="explore:my-silo"))

        assert "explore:my-silo" in result
        assert result["explore:my-silo"][0]["title"] == "BERT Pre-training"

    def test_explore_db_not_found(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        missing_db = tmp_path / "missing.db"  # does NOT exist

        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.explore._db_path", return_value=missing_db),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("bert", scope="explore:ghost"))

        assert result["explore:ghost"] == [{"error": "db_not_found"}]


# ---------------------------------------------------------------------------
# Tests: arxiv scope
# ---------------------------------------------------------------------------


class TestFederatedSearchArxiv:
    def test_arxiv_results_annotated_not_in_library(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        # index_db does not exist → no in-library annotation possible
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.sources.arxiv.search_arxiv", return_value=[dict(_ARXIV_PAPER)]),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("transformer", scope="arxiv"))

        assert len(result["arxiv"]) == 1
        paper = result["arxiv"][0]
        assert paper["title"] == "New Transformer"
        assert paper["in_main_library"] is False

    def test_arxiv_results_annotated_in_library(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        # Create a real SQLite DB with the DOI present
        import sqlite3

        db = tmp_path / "index.db"
        with sqlite3.connect(str(db)) as conn:
            conn.execute("CREATE TABLE papers_registry (doi TEXT)")
            conn.execute("INSERT INTO papers_registry VALUES (?)", ("10.9999/new",))
        cfg.index_db = db

        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.sources.arxiv.search_arxiv", return_value=[dict(_ARXIV_PAPER)]),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("transformer", scope="arxiv"))

        assert result["arxiv"][0]["in_main_library"] is True

    def test_arxiv_empty_results(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.sources.arxiv.search_arxiv", return_value=[]),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("transformer", scope="arxiv"))

        assert result["arxiv"] == []


# ---------------------------------------------------------------------------
# Tests: multi-scope and JSON structure
# ---------------------------------------------------------------------------


class TestFederatedSearchMultiScope:
    def test_multi_scope_keys_present(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.index.unified_search", return_value=[_MAIN_PAPER]),
            patch("scholaraio.sources.arxiv.search_arxiv", return_value=[dict(_ARXIV_PAPER)]),
        ):
            from scholaraio.mcp_server import federated_search

            result = json.loads(federated_search("transformer", scope="main,arxiv"))

        assert "main" in result
        assert "arxiv" in result

    def test_output_is_valid_json(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        with (
            patch("scholaraio.mcp_server._get_cfg", return_value=cfg),
            patch("scholaraio.index.unified_search", return_value=[_MAIN_PAPER]),
        ):
            from scholaraio.mcp_server import federated_search

            raw = federated_search("attention", scope="main")

        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
