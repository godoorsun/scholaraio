"""Unit tests for scholaraio/sources/arxiv.py — search_arxiv() XML parsing.

All tests stub requests.get so no network access is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Sample Atom XML fixtures
# ---------------------------------------------------------------------------

_ATOM_FULL = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Attention Is All You Need Again</title>
    <summary>We propose a new transformer variant.</summary>
    <published>2024-01-15T00:00:00Z</published>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <arxiv:doi>10.1234/attn2</arxiv:doi>
  </entry>
</feed>
"""

_ATOM_MISSING_OPTIONAL = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2402.99999v1</id>
    <title>Minimal Entry</title>
    <!-- no summary, no published, no arxiv:doi -->
  </entry>
</feed>
"""

_ATOM_EMPTY_TEXT = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2403.12345v2</id>
    <title></title>
    <summary></summary>
    <published>2024-03-01T00:00:00Z</published>
  </entry>
</feed>
"""

_ATOM_MULTI = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Paper One</title>
    <summary>Abstract one.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Alice</name></author>
    <arxiv:doi>10.1111/one</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Paper Two</title>
    <summary>Abstract two.</summary>
    <published>2024-01-02T00:00:00Z</published>
    <author><name>Bob</name></author>
  </entry>
</feed>
"""


def _mock_response(xml_text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = xml_text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchArxivParsing:
    def test_full_entry_fields(self):
        with patch("requests.get", return_value=_mock_response(_ATOM_FULL)):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("attention", top_k=1)

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Attention Is All You Need Again"
        assert r["abstract"] == "We propose a new transformer variant."
        assert r["year"] == "2024"
        assert r["authors"] == ["Alice Smith", "Bob Jones"]
        assert r["arxiv_id"] == "2401.00001v1"
        assert r["doi"] == "10.1234/attn2"

    def test_missing_optional_fields(self):
        with patch("requests.get", return_value=_mock_response(_ATOM_MISSING_OPTIONAL)):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("minimal")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == "Minimal Entry"
        assert r["abstract"] == ""
        assert r["year"] == ""
        assert r["authors"] == []
        assert r["doi"] == ""
        assert r["arxiv_id"] == "2402.99999v1"

    def test_empty_title_and_abstract(self):
        with patch("requests.get", return_value=_mock_response(_ATOM_EMPTY_TEXT)):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("empty")

        assert len(results) == 1
        r = results[0]
        assert r["title"] == ""
        assert r["abstract"] == ""
        assert r["year"] == "2024"

    def test_multiple_entries(self):
        with patch("requests.get", return_value=_mock_response(_ATOM_MULTI)):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("papers", top_k=5)

        assert len(results) == 2
        assert results[0]["title"] == "Paper One"
        assert results[0]["doi"] == "10.1111/one"
        assert results[1]["title"] == "Paper Two"
        assert results[1]["doi"] == ""

    def test_network_error_returns_empty(self):
        with patch("requests.get", side_effect=ConnectionError("timeout")):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("anything")

        assert results == []

    def test_http_error_returns_empty(self):
        import requests

        resp = _mock_response("", status_code=403)
        resp.raise_for_status.side_effect = requests.HTTPError("403")
        with patch("requests.get", return_value=resp):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("anything")

        assert results == []

    def test_malformed_xml_returns_empty(self):
        with patch("requests.get", return_value=_mock_response("<not valid xml<<")):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("anything")

        assert results == []

    def test_arxiv_id_extracted_from_url(self):
        with patch("requests.get", return_value=_mock_response(_ATOM_FULL)):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("attention")

        assert results[0]["arxiv_id"] == "2401.00001v1"

    def test_multiline_title_normalized(self):
        xml = _ATOM_FULL.replace("Attention Is All You Need Again", "Attention\nIs All\nYou Need")
        with patch("requests.get", return_value=_mock_response(xml)):
            from scholaraio.sources.arxiv import search_arxiv

            results = search_arxiv("attention")

        assert "\n" not in results[0]["title"]
