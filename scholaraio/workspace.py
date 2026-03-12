"""
workspace.py — 工作区论文子集管理
===================================

每个工作区是 ``workspace/<name>/`` 目录，内含 ``papers.json`` 索引文件
指向 ``data/papers/`` 中的论文。工作区内可自由存放笔记、代码、草稿等。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


# ============================================================================
#  Internal helpers
# ============================================================================

def _papers_json(ws_dir: Path) -> Path:
    return ws_dir / "papers.json"


def _read(ws_dir: Path) -> list[dict]:
    pj = _papers_json(ws_dir)
    if not pj.exists():
        return []
    try:
        raw = json.loads(pj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"papers.json 格式损坏，操作中止: {pj}") from e
    if not isinstance(raw, list):
        raise RuntimeError(f"papers.json 格式异常（期望 list，实际 {type(raw).__name__}）: {pj}")
    # Filter out malformed entries missing required "id" field
    valid = [e for e in raw if isinstance(e, dict) and "id" in e]
    if len(valid) < len(raw):
        _log.warning("papers.json 中有 %d 条缺少 id 的记录已跳过 (%s)", len(raw) - len(valid), pj)
    return valid


def _write(ws_dir: Path, entries: list[dict]) -> None:
    pj = _papers_json(ws_dir)
    tmp = pj.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(pj)


# ============================================================================
#  Public API
# ============================================================================

def create(ws_dir: Path) -> Path:
    """创建工作区目录并初始化空 papers.json。

    Args:
        ws_dir: 工作区目录路径。

    Returns:
        papers.json 文件路径。
    """
    ws_dir.mkdir(parents=True, exist_ok=True)
    pj = _papers_json(ws_dir)
    if not pj.exists():
        _write(ws_dir, [])
    return pj


def add(ws_dir: Path, paper_refs: list[str], db_path: Path) -> list[dict]:
    """添加论文到工作区。

    通过 UUID、目录名或 DOI 解析论文，去重后追加到 papers.json。

    Args:
        ws_dir: 工作区目录路径。
        paper_refs: 论文引用列表（UUID / 目录名 / DOI）。
        db_path: index.db 路径，用于 lookup_paper。

    Returns:
        新增条目列表。
    """
    from scholaraio.index import lookup_paper

    entries = _read(ws_dir)
    existing_ids = {e["id"] for e in entries}
    added: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for ref in paper_refs:
        record = lookup_paper(db_path, ref)
        if record is None:
            _log.warning("无法解析论文引用: %s", ref)
            continue
        uid = record["id"]
        if uid in existing_ids:
            _log.debug("已存在，跳过: %s", ref)
            continue
        entry = {"id": uid, "dir_name": record["dir_name"], "added_at": now}
        entries.append(entry)
        existing_ids.add(uid)
        added.append(entry)

    if added:
        _write(ws_dir, entries)
    return added


def remove(ws_dir: Path, paper_refs: list[str], db_path: Path) -> list[dict]:
    """从工作区移除论文。

    Args:
        ws_dir: 工作区目录路径。
        paper_refs: 论文引用列表（UUID / 目录名 / DOI）。
        db_path: index.db 路径。

    Returns:
        被移除的条目列表。
    """
    from scholaraio.index import lookup_paper

    entries = _read(ws_dir)
    remove_ids: set[str] = set()
    for ref in paper_refs:
        record = lookup_paper(db_path, ref)
        if record:
            remove_ids.add(record["id"])
        else:
            # Try direct UUID match
            remove_ids.add(ref)

    removed = [e for e in entries if e["id"] in remove_ids]
    if removed:
        entries = [e for e in entries if e["id"] not in remove_ids]
        _write(ws_dir, entries)
    return removed


def list_workspaces(ws_root: Path) -> list[str]:
    """列出所有含 papers.json 的工作区。

    Args:
        ws_root: workspace/ 根目录。

    Returns:
        工作区名称列表（排序）。
    """
    if not ws_root.is_dir():
        return []
    return sorted(
        d.name for d in ws_root.iterdir()
        if d.is_dir() and _papers_json(d).exists()
    )


def show(ws_dir: Path, db_path: Path) -> list[dict]:
    """查看工作区论文列表，刷新过期的 dir_name。

    Args:
        ws_dir: 工作区目录路径。
        db_path: index.db 路径。

    Returns:
        论文条目列表（含最新 dir_name）。
    """
    from scholaraio.index import lookup_paper

    entries = _read(ws_dir)
    changed = False
    for e in entries:
        record = lookup_paper(db_path, e["id"])
        if record and record["dir_name"] != e.get("dir_name"):
            e["dir_name"] = record["dir_name"]
            changed = True
    if changed:
        _write(ws_dir, entries)
    return entries


def read_paper_ids(ws_dir: Path) -> set[str]:
    """返回工作区中所有论文的 UUID 集合。

    Args:
        ws_dir: 工作区目录路径。

    Returns:
        UUID 字符串集合，用于搜索过滤。
    """
    return {e["id"] for e in _read(ws_dir)}


def read_dir_names(ws_dir: Path, db_path: Path) -> set[str]:
    """返回工作区中所有论文的当前目录名集合。

    从 papers_registry 查找最新 dir_name（处理 rename 后的情况）。

    Args:
        ws_dir: 工作区目录路径。
        db_path: index.db 路径。

    Returns:
        目录名字符串集合，用于导出过滤。
    """
    from scholaraio.index import lookup_paper

    names: set[str] = set()
    for e in _read(ws_dir):
        record = lookup_paper(db_path, e["id"])
        if record:
            names.add(record["dir_name"])
        elif e.get("dir_name"):
            names.add(e["dir_name"])
    return names
