"""
explore.py — 学术探索
======================

从 OpenAlex 批量拉取论文，或从本地 metadata 文件导入论文记录
（支持 ``CSV / TSV / JSON / JSONL``），再做本地嵌入 + FAISS 语义搜索 +
FTS5 关键词检索 + RRF 融合检索。主题建模、可视化、查询复用 ``topics.py``
（通过 ``papers_map`` 参数）。数据存储在 ``data/explore/<name>/``，
与主库完全隔离。

用法::

    from scholaraio.explore import fetch_explore, build_explore_vectors, build_explore_topics
    fetch_explore("jfm", issn="0022-1120")
    fetch_explore("turbulence", concept="C62520636", year_range="2020-2025")
    build_explore_vectors("jfm")
    build_explore_topics("jfm")
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import requests

from scholaraio.log import ui

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from scholaraio.config import Config

# ============================================================================
#  Config / paths
# ============================================================================

_DEFAULT_EXPLORE_DIR = Path("data/explore")


def _explore_dir(name: str, cfg: Config | None = None) -> Path:
    if cfg is not None:
        return cfg._root / "data" / "explore" / name
    return _DEFAULT_EXPLORE_DIR / name


def _papers_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "papers.jsonl"


def _db_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "explore.db"


def explore_db_path(name: str, cfg: Config | None = None) -> Path:
    """Return the SQLite DB path for an explore library.

    Args:
        name: Explore library name.
        cfg: Optional Config instance; resolved from environment if omitted.

    Returns:
        Path to ``explore.db`` inside the library directory.
    """
    return _db_path(name, cfg)


def validate_explore_name(name: str) -> bool:
    """Return True if *name* is a safe, non-traversing library identifier.

    Rejects empty strings, absolute paths, and names that contain path
    separators or ``..`` components so that callers cannot escape the
    ``data/explore/`` directory.

    Args:
        name: Candidate explore library name supplied by the user.

    Returns:
        ``True`` when the name is safe to use in path construction.
    """
    if not name:
        return False
    import os

    # Reject absolute paths and names that contain any path separator.
    if os.path.isabs(name):
        return False
    if "/" in name or "\\" in name:
        return False
    # Reject any name containing "..".
    return ".." not in name


def _meta_path(name: str, cfg: Config | None = None) -> Path:
    return _explore_dir(name, cfg) / "meta.json"


_TITLE_KEYS = ("title", "paper_title", "name", "标题", "题目", "论文标题")
_ABSTRACT_KEYS = ("abstract", "summary", "description", "摘要", "简介")
_AUTHORS_KEYS = ("authors", "author_names", "author", "creators", "作者", "作者姓名", "作者列表")
_YEAR_KEYS = ("year", "publication_year", "pub_year")
_DOI_KEYS = ("doi",)
_OPENALEX_KEYS = ("openalex_id",)
_PAPER_ID_KEYS = ("paper_id", "record_id", "source_id", "uid")
_JOURNAL_KEYS = ("journal", "venue", "source", "publication", "container_title", "container-title", "期刊", "会议")
_DOWNLOAD_URL_KEYS = (
    "download_url",
    "download_link",
    "pdf_url",
    "source_url",
    "url",
    "link",
    "下载链接",
    "OpenReview下载链接",
    "PDF链接",
)


def _pick_first(record: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalize_year(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    m = re.search(r"\b(19|20)\d{2}\b", str(value))
    return int(m.group(0)) if m else None


def _normalize_authors(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("display_name") or item.get("author")
                name = _clean_text(name)
                if name:
                    out.append(name)
            else:
                name = _clean_text(item)
                if name:
                    out.append(name)
        return out

    text = _clean_text(value)
    if not text:
        return []
    for sep in (";", "|", "\n"):
        if sep in text:
            return [part.strip() for part in text.split(sep) if part.strip()]
    if " and " in text.lower():
        return [part.strip() for part in re.split(r"\band\b", text, flags=re.IGNORECASE) if part.strip()]
    return [text]


def _paper_id(record: dict) -> str:
    doi = _clean_text(record.get("doi")).lower()
    if doi:
        return doi

    openalex_id = _clean_text(record.get("openalex_id"))
    if openalex_id:
        return openalex_id

    explicit_id = _clean_text(record.get("paper_id"))
    if explicit_id:
        return explicit_id

    title = _clean_text(record.get("title")).lower()
    authors = [_clean_text(a).lower() for a in (record.get("authors") or []) if _clean_text(a)]
    year = str(record.get("year") or "")
    download_url = _clean_text(record.get("download_url"))
    basis = json.dumps(
        {
            "title": title,
            "authors": authors[:5],
            "year": year,
            "download_url": download_url,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "local:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _normalize_local_record(raw: dict) -> dict | None:
    title = _clean_text(_pick_first(raw, _TITLE_KEYS))
    if not title:
        return None

    record = {
        "title": title,
        "abstract": _clean_text(_pick_first(raw, _ABSTRACT_KEYS)),
        "authors": _normalize_authors(_pick_first(raw, _AUTHORS_KEYS)),
        "year": _normalize_year(_pick_first(raw, _YEAR_KEYS)),
        "doi": _clean_text(_pick_first(raw, _DOI_KEYS)),
        "openalex_id": _clean_text(_pick_first(raw, _OPENALEX_KEYS)),
        "paper_id": _clean_text(_pick_first(raw, _PAPER_ID_KEYS)),
        "journal": _clean_text(_pick_first(raw, _JOURNAL_KEYS)),
        "download_url": _clean_text(_pick_first(raw, _DOWNLOAD_URL_KEYS)),
        "source": "local_import",
        "type": _clean_text(raw.get("type") or raw.get("paper_type")) or "article",
    }
    record["paper_id"] = _paper_id(record)
    return record


def _iter_local_records(input_path: Path) -> Iterator[dict]:
    suffix = input_path.suffix.lower()

    if suffix in {".jsonl", ".ndjson"}:
        with open(input_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
        return

    if suffix == ".json":
        data = json.loads(input_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item
            return
        if isinstance(data, dict):
            for key in ("papers", "records", "items", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            yield item
                    return
        raise ValueError("JSON 文件必须是对象数组，或包含 papers/records/items/data 数组")

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with open(input_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                yield dict(row)
        return

    raise ValueError(f"不支持的文件格式: {input_path.suffix}（支持 .csv/.tsv/.json/.jsonl）")


def import_explore(
    name: str,
    input_path: str | Path,
    *,
    incremental: bool = False,
    cfg: Config | None = None,
) -> int:
    """从本地 metadata 文件创建 explore 库。

    支持 ``CSV / TSV / JSON / JSONL``，记录至少包含 ``title`` 字段。
    推荐字段：``title``、``abstract``、``authors``、``year``、``doi``、
    ``download_url``。导入后写入 ``data/explore/<name>/papers.jsonl``。

    Args:
        name: 探索库名称。
        input_path: 本地数据文件路径。
        incremental: 为 ``True`` 时基于 ``paper_id`` 追加去重。
        cfg: 可选的全局配置。

    Returns:
        本次新写入的记录数。
    """
    if not validate_explore_name(name):
        raise ValueError(f"无效的 explore 库名: {name}")

    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(f"文件不存在: {src}")

    out_dir = _explore_dir(name, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    papers_file = _papers_path(name, cfg)
    meta_file = _meta_path(name, cfg)

    existing_ids: set[str] = set()
    old_count = 0
    if incremental and papers_file.exists():
        for p in iter_papers(name, cfg):
            existing_ids.add(_paper_id(p))
        old_count = len(existing_ids)

    total = 0
    skipped = 0
    tmp_file: Path | None = None
    if incremental and papers_file.exists():
        f_handle = open(papers_file, "a", encoding="utf-8")
    else:
        tmp_file = papers_file.with_suffix(".jsonl.tmp")
        f_handle = open(tmp_file, "w", encoding="utf-8")

    try:
        for raw in _iter_local_records(src):
            if not isinstance(raw, dict):
                skipped += 1
                continue
            record = _normalize_local_record(raw)
            if not record:
                skipped += 1
                continue
            pid = _paper_id(record)
            if incremental and pid in existing_ids:
                continue
            f_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            total += 1
            if incremental:
                existing_ids.add(pid)
    finally:
        f_handle.close()

    if tmp_file is not None:
        tmp_file.replace(papers_file)

    meta = {
        "name": name,
        "source": "local_import",
        "input_file": str(src),
        "count": old_count + total if incremental else total,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "incremental": incremental,
        "fields": ["paper_id", "title", "abstract", "authors", "year", "doi", "download_url"],
        "skipped": skipped,
    }
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ui(f"Done: {total} {'new ' if incremental else ''}papers -> {papers_file}")
    return total


# ============================================================================
#  Fetch from OpenAlex
# ============================================================================


def _is_boilerplate(abstract: str) -> bool:
    """Detect publisher boilerplate instead of real abstract."""
    low = abstract.lower()
    return "abstract is not available" in low or "preview has been provided" in low or "access link" in low


_OA_WORKS = "https://api.openalex.org/works"
_PER_PAGE = 200


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def _build_filter(
    *,
    issn: str | None = None,
    concept: str | None = None,
    topic: str | None = None,
    author: str | None = None,
    institution: str | None = None,
    source_type: str | None = None,
    year_range: str | None = None,
    min_citations: int | None = None,
    oa_type: str | None = None,
) -> tuple[str, dict]:
    """Build an OpenAlex filter string and extra query params.

    Returns:
        (filter_string, extra_params) — extra_params may contain ``search``.
    """
    parts: list[str] = []
    extra: dict[str, str] = {}

    if issn:
        parts.append(f"primary_location.source.issn:{issn}")
    if concept:
        parts.append(f"concepts.id:{concept}")
    if topic:
        parts.append(f"topics.id:{topic}")
    if author:
        parts.append(f"authorships.author.id:{author}")
    if institution:
        parts.append(f"authorships.institutions.id:{institution}")
    if source_type:
        parts.append(f"primary_location.source.type:{source_type}")
    if year_range:
        parts.append(f"publication_year:{year_range}")
    # OpenAlex cited_by_count filter expects a meaningful lower bound.
    # Non-positive values are treated as "no filter" to avoid invalid/odd expressions.
    if min_citations is not None and min_citations > 0:
        parts.append(f"cited_by_count:>{min_citations - 1}")
    if oa_type:
        parts.append(f"type:{oa_type}")

    return ",".join(parts), extra


def _fetch_page(
    filt: str,
    extra_params: dict | None = None,
    *,
    cursor: str = "*",
    keyword: str | None = None,
) -> tuple[list[dict], str | None]:
    """Fetch one page of results from OpenAlex.

    Args:
        filt: Pre-built OpenAlex filter string.
        extra_params: Additional query params (e.g. search).
        cursor: Cursor for pagination.
        keyword: Free-text search keyword (OpenAlex ``search`` param).
    """
    params: dict[str, str | int] = {
        "per_page": _PER_PAGE,
        "cursor": cursor,
        "select": "id,title,publication_year,doi,authorships,abstract_inverted_index,"
        "primary_location,cited_by_count,type",
        "sort": "publication_year:asc",
    }
    if filt:
        params["filter"] = filt
    if keyword:
        params["search"] = keyword
    if extra_params:
        params.update(extra_params)
    # Retry with exponential backoff for transient errors
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(_OA_WORKS, params=params, timeout=30, proxies={"http": None, "https": None})
            if resp.status_code == 429:
                wait = 2**attempt
                _log.warning("OpenAlex 429 rate limit, retrying in %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            wait = 2**attempt
            _log.warning("OpenAlex request failed (attempt %d/3): %s, retrying in %ds", attempt + 1, e, wait)
            time.sleep(wait)
    else:
        if last_exc:
            raise last_exc
        raise requests.HTTPError("OpenAlex API returned 429 after 3 retries")

    papers = []
    for item in data.get("results", []):
        doi_raw = item.get("doi") or ""
        doi = doi_raw.replace("https://doi.org/", "") if doi_raw else ""

        authors = []
        for a in item.get("authorships") or []:
            name = (a.get("author") or {}).get("display_name")
            if name:
                authors.append(name)

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))

        # Strip HTML tags from title (OpenAlex includes <b>, <scp>, <i>, etc.)
        raw_title = item.get("title") or ""
        clean_title = re.sub(r"<[^>]+>", "", raw_title)

        papers.append(
            {
                "paper_id": doi or item.get("id", ""),
                "openalex_id": item.get("id", ""),
                "doi": doi,
                "title": clean_title,
                "abstract": abstract,
                "authors": authors,
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
                "type": item.get("type", ""),
                "download_url": ((item.get("primary_location") or {}).get("landing_page_url") or ""),
            }
        )

    next_cursor = data.get("meta", {}).get("next_cursor")
    return papers, next_cursor


def fetch_explore(
    name: str,
    *,
    issn: str | None = None,
    concept: str | None = None,
    topic: str | None = None,
    author: str | None = None,
    institution: str | None = None,
    keyword: str | None = None,
    source_type: str | None = None,
    year_range: str | None = None,
    min_citations: int | None = None,
    oa_type: str | None = None,
    incremental: bool = False,
    limit: int | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 批量拉取论文（支持多维度 filter）。

    使用 cursor-based 分页遍历符合条件的所有论文，
    提取 title、abstract、authors 等字段，写入 JSONL 文件。

    Args:
        name: 探索库名称（如 ``"jfm"``），用作目录名。
        issn: 期刊 ISSN 过滤（如 ``"0022-1120"``）。
        concept: OpenAlex concept ID（如 ``"C62520636"`` = Turbulence）。
        topic: OpenAlex topic ID。
        author: OpenAlex author ID。
        institution: OpenAlex institution ID。
        keyword: 标题/摘要关键词搜索。
        source_type: 来源类型过滤（journal / conference / repository）。
        year_range: 年份过滤（如 ``"2020-2025"``）。
        min_citations: 最小引用量过滤。
        oa_type: OpenAlex work type 过滤（article / review 等）。
        incremental: 为 ``True`` 时追加到现有 JSONL，基于 DOI 去重。
        limit: 最多拉取的论文数量上限（``None`` 表示无限制）。
        cfg: 可选的全局配置。

    Returns:
        本次新拉取的论文数量。
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"limit 必须为正整数，当前为: {limit}")

    out_dir = _explore_dir(name, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    papers_file = _papers_path(name, cfg)
    meta_file = _meta_path(name, cfg)

    filt, extra_params = _build_filter(
        issn=issn,
        concept=concept,
        topic=topic,
        author=author,
        institution=institution,
        source_type=source_type,
        year_range=year_range,
        min_citations=min_citations,
        oa_type=oa_type,
    )
    if not filt and not keyword:
        raise ValueError("至少需要一个过滤条件（issn / concept / author / keyword 等）")

    # Incremental mode: load existing IDs (DOI or openalex_id) to skip duplicates
    existing_pids: set[str] = set()
    if incremental and papers_file.exists():
        for p in iter_papers(name, cfg):
            pid = _paper_id(p)
            if pid:
                existing_pids.add(pid)
        _log.info("incremental mode: %d existing papers loaded", len(existing_pids))

    from scholaraio.metrics import timer

    total = 0
    cursor: str | None = "*"

    with timer("explore.fetch", "api") as t:
        if incremental and papers_file.exists():
            f_handle = open(papers_file, "a", encoding="utf-8")
        else:
            tmp_file = papers_file.with_suffix(".jsonl.tmp")
            f_handle = open(tmp_file, "w", encoding="utf-8")

        try:
            page = 0
            while cursor:
                if limit is not None and total >= limit:
                    break
                page += 1
                papers, cursor = _fetch_page(
                    filt,
                    extra_params,
                    cursor=cursor,
                    keyword=keyword,
                )
                if not papers:
                    break
                written = 0
                for p in papers:
                    if limit is not None and total >= limit:
                        break
                    # Skip duplicates in incremental mode (by DOI or openalex_id)
                    if incremental:
                        pid = _paper_id(p)
                        if pid and pid in existing_pids:
                            continue
                    f_handle.write(json.dumps(p, ensure_ascii=False) + "\n")
                    total += 1
                    written += 1
                    if incremental:
                        pid = _paper_id(p)
                        if pid:
                            existing_pids.add(pid)
                _log.info(
                    "page %d: fetched=%d, written=%d (total %d, %.0fs)",
                    page,
                    len(papers),
                    written,
                    total,
                    t.elapsed,
                )
        finally:
            f_handle.close()

        if not incremental or not papers_file.exists():
            tmp_file.replace(papers_file)  # type: ignore[possibly-undefined]

    # Build query record for meta.json
    query_params: dict[str, str | int | None] = {}
    for key, val in [
        ("issn", issn),
        ("concept", concept),
        ("topic", topic),
        ("author", author),
        ("institution", institution),
        ("keyword", keyword),
        ("source_type", source_type),
        ("year_range", year_range),
        ("min_citations", min_citations),
        ("oa_type", oa_type),
    ]:
        if val is not None:
            query_params[key] = val

    # Update count: for incremental mode, add to existing count
    total_count = total
    if incremental and meta_file.exists():
        old_meta = json.loads(meta_file.read_text("utf-8"))
        total_count = old_meta.get("count", 0) + total

    meta = {
        "name": name,
        "source": "openalex",
        "query": query_params,
        # Keep "issn" at top level for backward compatibility
        "issn": issn or "",
        "year_range": year_range,
        "count": total_count,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_seconds": round(t.elapsed, 1),
    }
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ui(f"Done: {total} {'new ' if incremental else ''}papers, {t.elapsed:.0f}s -> {papers_file}")
    return total


def fetch_journal(
    name: str,
    issn: str,
    *,
    year_range: str | None = None,
    cfg: Config | None = None,
) -> int:
    """从 OpenAlex 拉取期刊全量论文（向后兼容别名）。

    等价于 ``fetch_explore(name, issn=issn, year_range=year_range, cfg=cfg)``。
    """
    return fetch_explore(name, issn=issn, year_range=year_range, cfg=cfg)


# ============================================================================
#  Load papers from JSONL
# ============================================================================


def iter_papers(name: str, cfg: Config | None = None) -> Iterator[dict]:
    """逐行读取 JSONL，yield 论文字典。"""
    path = _papers_path(name, cfg)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def count_papers(name: str, cfg: Config | None = None) -> int:
    """返回探索库中的论文数量。"""
    meta_file = _meta_path(name, cfg)
    if meta_file.exists():
        return json.loads(meta_file.read_text("utf-8")).get("count", 0)
    return sum(1 for _ in iter_papers(name, cfg))


# ============================================================================
#  Embedding
# ============================================================================


def build_explore_vectors(name: str, *, rebuild: bool = False, cfg: Config | None = None) -> int:
    """为探索库生成语义向量。

    复用主库的 Qwen3-Embedding 模型，向量存入探索库自己的
    ``explore.db``。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时清空重建。
        cfg: 可选的全局配置（用于模型加载）。

    Returns:
        本次新嵌入的论文数量。
    """
    from scholaraio.vectors import (
        _append_faiss_files,
        _content_hash,
        _embed_batch,
        _ensure_schema,
        _invalidate_faiss,
        _load_model,
        _pack,
    )

    _load_model(cfg)

    db = _db_path(name, cfg)
    conn = sqlite3.connect(db)
    try:
        _ensure_schema(conn)

        if rebuild:
            conn.execute("DELETE FROM paper_vectors")
            _invalidate_faiss(db)

        existing_hashes: dict[str, str] = {}
        if not rebuild:
            existing_hashes = {row[0]: row[1] for row in conn.execute("SELECT paper_id, content_hash FROM paper_vectors")}

        to_embed: list[tuple[str, str, str]] = []
        for p in iter_papers(name, cfg):
            pid = _paper_id(p)
            if not pid:
                continue
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not abstract or _is_boilerplate(abstract):
                continue
            if p.get("type") in ("paratext", "erratum", "editorial"):
                continue
            content_hash = _content_hash(title, abstract)
            if not rebuild and existing_hashes.get(pid) == content_hash:
                continue
            text = f"{title}\n\n{abstract}" if title else abstract
            to_embed.append((pid, text, content_hash))

        if not to_embed:
            return 0

        _log.info("Embedding %d papers...", len(to_embed))

        chunk_size = 256  # DB commit chunk; GPU batching is adaptive inside _embed_batch
        total = 0
        all_new_ids: list[str] = []
        all_new_vecs: list[list[float]] = []
        updated_ids: set[str] = set()
        for i in range(0, len(to_embed), chunk_size):
            chunk = to_embed[i : i + chunk_size]
            texts = [t for _, t, _ in chunk]
            vecs = _embed_batch(texts, cfg)
            for (pid, _, content_hash), vec in zip(chunk, vecs):
                blob = _pack(vec)
                conn.execute(
                    "INSERT OR REPLACE INTO paper_vectors (paper_id, embedding, content_hash) VALUES (?, ?, ?)",
                    (pid, blob, content_hash),
                )
                all_new_ids.append(pid)
                all_new_vecs.append(vec)
                if pid in existing_hashes:
                    updated_ids.add(pid)
            total += len(chunk)
            _log.info("Progress: %d/%d", total, len(to_embed))

        conn.commit()
    finally:
        conn.close()

    if rebuild or updated_ids:
        _invalidate_faiss(db)
    elif all_new_ids:
        explore_dir = _explore_dir(name, cfg)
        _append_faiss_files(
            explore_dir / "faiss.index",
            explore_dir / "faiss_ids.json",
            all_new_ids,
            all_new_vecs,
        )

    # Also build FTS5 index (cheap, ensures keyword search is available)
    build_explore_fts(name, cfg=cfg)

    return len(to_embed)


# ============================================================================
#  Topics (BERTopic) — delegates to topics.py
# ============================================================================


def build_papers_map(name: str, cfg: Config | None = None) -> dict[str, dict]:
    """从 JSONL 构建 paper_id → metadata 映射。

    Args:
        name: 探索库名称。
        cfg: 可选的全局配置。

    Returns:
        ``{paper_id: paper_dict}`` 映射。
    """
    pm: dict[str, dict] = {}
    for p in iter_papers(name, cfg):
        pid = _paper_id(p)
        if pid:
            pm[pid] = p
    return pm


def build_explore_topics(
    name: str,
    *,
    rebuild: bool = False,
    min_topic_size: int = 30,
    nr_topics: int | str | None = None,
    cfg: Config | None = None,
) -> dict:
    """对探索库运行 BERTopic 主题建模。

    复用主库的 ``build_topics()`` 流程，但参数针对大规模数据调整
    （默认 ``min_topic_size=30``）。模型以统一格式保存（bertopic_model.pkl +
    scholaraio_meta.pkl），可直接用 ``topics.load_model()`` 加载。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时重建模型。
        min_topic_size: HDBSCAN 最小聚类大小。
        nr_topics: 目标主题数。``"auto"`` 自动合并。
        cfg: 可选的全局配置。

    Returns:
        统计字典：``{"n_topics": N, "n_outliers": N, "n_papers": N}``。
    """
    from scholaraio.vectors import _load_model

    _load_model(cfg)

    model_dir = _explore_dir(name, cfg) / "topic_model"
    if model_dir.exists() and not rebuild:
        return _load_topic_info(name, cfg)

    db = _db_path(name, cfg)
    if not db.exists():
        raise FileNotFoundError(f"向量库不存在: {db}\n请先运行 explore embed --name {name}")

    papers_map = build_papers_map(name, cfg)

    from scholaraio.topics import build_topics

    # Compute explore-tuned hyperparameters
    n = len(papers_map)
    model = build_topics(
        db,
        papers_map=papers_map,
        min_topic_size=min_topic_size,
        nr_topics=nr_topics,
        save_path=model_dir,
        cfg=cfg,
        n_neighbors=min(15, max(5, n // 50)),
        n_components=min(5, max(2, n // 200)),
        min_samples=max(1, min_topic_size // 5),
        ngram_range=(1, 2),
        min_df=1,
    )

    # Write info.json for quick stats retrieval
    topics = getattr(model, "_topics", [])
    n_topics = len(set(topics)) - (1 if -1 in topics else 0)
    n_outliers = sum(1 for t in topics if t == -1)
    info = {"n_topics": n_topics, "n_outliers": n_outliers, "n_papers": len(topics)}
    (model_dir / "info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    return info


def _load_topic_info(name: str, cfg: Config | None = None) -> dict:
    info_path = _explore_dir(name, cfg) / "topic_model" / "info.json"
    if info_path.exists():
        return json.loads(info_path.read_text("utf-8"))
    return {}


def _build_faiss_index(name: str, cfg: Config | None = None):
    """Build or load a FAISS index for an explore silo."""
    from scholaraio.vectors import _build_faiss_from_db

    explore_dir = _explore_dir(name, cfg)
    return _build_faiss_from_db(
        _db_path(name, cfg),
        explore_dir / "faiss.index",
        explore_dir / "faiss_ids.json",
        empty_msg=f"向量库为空: {_db_path(name, cfg)}",
    )


def explore_vsearch(name: str, query: str, *, top_k: int = 10, cfg: Config | None = None) -> list[dict]:
    """在探索库中进行语义搜索（FAISS 加速）。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 cosine similarity 降序。
    """
    from scholaraio.vectors import _vsearch_faiss

    index, paper_ids = _build_faiss_index(name, cfg)
    hits = _vsearch_faiss(query, index, paper_ids, top_k, cfg=cfg)

    paper_map = {}
    for p in iter_papers(name, cfg):
        pid = _paper_id(p)
        if pid:
            paper_map[pid] = p

    results = []
    for pid, score in hits:
        p = paper_map.get(pid, {})
        results.append({**p, "score": score})
    return results


# ============================================================================
#  FTS5 keyword search for explore silos
# ============================================================================

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    paper_id   UNINDEXED,
    title,
    authors,
    abstract,
    year       UNINDEXED,
    tokenize='unicode61'
);
"""


def _ensure_fts(db_path: Path) -> None:
    """Create FTS5 table in explore.db if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_FTS_SCHEMA)
    conn.close()


def build_explore_fts(name: str, *, rebuild: bool = False, cfg: Config | None = None) -> int:
    """为探索库构建 FTS5 全文索引。

    Args:
        name: 探索库名称。
        rebuild: 为 ``True`` 时清空重建。
        cfg: 可选的全局配置。

    Returns:
        索引的论文数量。
    """
    db = _db_path(name, cfg)
    _ensure_fts(db)
    conn = sqlite3.connect(db)
    try:
        if rebuild:
            conn.execute("DELETE FROM papers_fts")
            conn.commit()

        count = 0
        for p in iter_papers(name, cfg):
            pid = _paper_id(p)
            if not pid:
                continue
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not title:
                continue
            authors = ", ".join(p.get("authors") or [])
            year = str(p.get("year") or "")
            conn.execute("DELETE FROM papers_fts WHERE paper_id = ?", (pid,))
            conn.execute(
                "INSERT INTO papers_fts (paper_id, title, authors, abstract, year) VALUES (?, ?, ?, ?, ?)",
                (pid, title, authors, abstract, year),
            )
            count += 1

        conn.commit()
    finally:
        conn.close()

    _log.info("FTS5 index: %d papers indexed for %s", count, name)
    return count


def explore_search(name: str, query: str, *, top_k: int = 20, cfg: Config | None = None) -> list[dict]:
    """在探索库中进行 FTS5 关键词搜索。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 BM25 排名。
    """
    db = _db_path(name, cfg)
    if not db.exists():
        return []

    _ensure_fts(db)

    # Auto-build if FTS table is empty
    conn = sqlite3.connect(db)
    try:
        fts_count = conn.execute("SELECT COUNT(*) FROM papers_fts").fetchone()[0]
    finally:
        conn.close()

    if fts_count == 0:
        build_explore_fts(name, cfg=cfg)

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT paper_id, rank FROM papers_fts WHERE papers_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, top_k),
        ).fetchall()
    except Exception:
        # FTS query syntax error — try quoting
        safe_query = '"' + query.replace('"', "") + '"'
        try:
            rows = conn.execute(
                "SELECT paper_id, rank FROM papers_fts WHERE papers_fts MATCH ? ORDER BY rank LIMIT ?",
                (safe_query, top_k),
            ).fetchall()
        except Exception:
            rows = []
    finally:
        conn.close()

    if not rows:
        return []

    paper_map = build_papers_map(name, cfg)
    results = []
    for pid, rank in rows:
        p = paper_map.get(pid, {})
        results.append({**p, "score": -rank, "match": "fts"})
    return results


def explore_unified_search(name: str, query: str, *, top_k: int = 20, cfg: Config | None = None) -> list[dict]:
    """探索库融合检索：FTS5 关键词 + FAISS 语义，RRF 合并排序。

    Args:
        name: 探索库名称。
        query: 查询文本。
        top_k: 返回条数。
        cfg: 可选的全局配置。

    Returns:
        论文列表，按 RRF 综合得分降序。
    """
    fts_results = explore_search(name, query, top_k=top_k, cfg=cfg)

    vec_results: list[dict] = []
    try:
        vec_results = explore_vsearch(name, query, top_k=top_k, cfg=cfg)
    except (FileNotFoundError, ImportError):
        pass

    # RRF merge (k=60, same as main library)
    rrf_k = 60
    merged: dict[str, dict] = {}

    for rank, r in enumerate(fts_results):
        pid = _paper_id(r)
        if not pid:
            continue
        merged[pid] = {**r, "score": 1.0 / (rrf_k + rank + 1), "match": "fts"}

    for rank, r in enumerate(vec_results):
        pid = _paper_id(r)
        if not pid:
            continue
        rrf_score = 1.0 / (rrf_k + rank + 1)
        if pid in merged:
            merged[pid]["score"] += rrf_score
            merged[pid]["match"] = "both"
        else:
            merged[pid] = {**r, "score": rrf_score, "match": "vec"}

    results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def list_explore_libs(cfg: Config | None = None) -> list[str]:
    """列出所有探索库名称。"""
    if cfg is not None:
        root = cfg._root / "data" / "explore"
    else:
        root = _DEFAULT_EXPLORE_DIR
    if not root.exists():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and (d / "papers.jsonl").exists())
