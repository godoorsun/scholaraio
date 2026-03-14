"""Shared arXiv Atom API helper used by both CLI and MCP server."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

_log = logging.getLogger(__name__)

_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_USER_AGENT = "scholaraio/1.0 (https://github.com/ZimoLiao/scholaraio)"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def search_arxiv(query: str, top_k: int = 10) -> list[dict]:
    """Query the arXiv Atom API and return a list of simplified paper dicts.

    Args:
        query: Free-text search query.
        top_k: Maximum number of results to return.

    Returns:
        List of dicts with keys: title, authors, year, abstract, arxiv_id, doi.
        Returns an empty list on network failure or XML parse error.
    """
    import requests

    params = {"search_query": f"all:{query}", "max_results": top_k, "sortBy": "relevance"}
    try:
        resp = requests.get(_ARXIV_API_URL, params=params, headers={"User-Agent": _USER_AGENT}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        _log.warning("arXiv API 不可用: %s", e)
        return []

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        _log.warning("arXiv XML 解析失败: %s", e)
        return []

    results = []
    for entry in root.findall("atom:entry", _NS):
        title_el = entry.find("atom:title", _NS)
        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""

        summary_el = entry.find("atom:summary", _NS)
        abstract = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""

        year = ""
        pub_el = entry.find("atom:published", _NS)
        if pub_el is not None and pub_el.text:
            year = pub_el.text[:4]

        authors: list[str] = []
        for author_el in entry.findall("atom:author", _NS):
            name_el = author_el.find("atom:name", _NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text)

        arxiv_id = ""
        id_el = entry.find("atom:id", _NS)
        if id_el is not None and id_el.text:
            arxiv_id = id_el.text.strip().split("/abs/")[-1]

        doi = ""
        doi_el = entry.find("arxiv:doi", _NS)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()

        results.append(
            {
                "title": title,
                "authors": authors,
                "year": year,
                "abstract": abstract,
                "arxiv_id": arxiv_id,
                "doi": doi,
            }
        )
    return results
