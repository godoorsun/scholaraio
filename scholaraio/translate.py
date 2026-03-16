"""
translate.py — 论文 Markdown 自动翻译
======================================

将非目标语言的论文 Markdown 翻译为目标语言（默认中文），
保留 LaTeX 公式、代码块、图片引用和 Markdown 格式。

翻译结果保存为 ``paper_{lang}.md``（如 ``paper_zh.md``），
原文 ``paper.md`` 保持不变。

用法：
    from scholaraio.translate import translate_paper, batch_translate
    translate_paper(paper_dir, config)
    batch_translate(papers_dir, config)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scholaraio.config import Config

_log = logging.getLogger(__name__)

# Language name mapping for prompts
_LANG_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
}

# ============================================================================
#  Language detection (lightweight heuristic, no extra dependency)
# ============================================================================

# CJK Unicode ranges
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_KANA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")


def detect_language(text: str) -> str:
    """Detect the primary language of text using character-class heuristics.

    Args:
        text: Input text (first ~2000 chars are examined).

    Returns:
        ISO 639-1 code: ``"zh"``, ``"ja"``, ``"ko"``, or ``"en"`` (default).
    """
    sample = text[:2000]
    # Strip code blocks and LaTeX to avoid false positives
    sample = re.sub(r"```[\s\S]*?```", "", sample)
    sample = re.sub(r"\$\$[\s\S]*?\$\$", "", sample)
    sample = re.sub(r"\$[^$]+\$", "", sample)

    cjk_count = len(_CJK_RE.findall(sample))
    hangul_count = len(_HANGUL_RE.findall(sample))
    kana_count = len(_KANA_RE.findall(sample))

    total_alpha = sum(1 for c in sample if c.isalpha())
    if total_alpha == 0:
        return "en"

    # Japanese: kana alone (hiragana/katakana-heavy text with few kanji)
    if kana_count / total_alpha > 0.1:
        return "ja"
    if cjk_count / total_alpha > 0.15:
        # Mixed CJK+kana → Japanese; pure CJK → Chinese
        if kana_count > cjk_count * 0.1:
            return "ja"
        return "zh"
    if hangul_count / total_alpha > 0.15:
        return "ko"
    return "en"


# ============================================================================
#  Chunking (preserve markdown structure)
# ============================================================================

# Combined pattern for protected blocks (code fences, display/inline math, images).
# Order matters: display math ($$...$$) must be matched before inline math ($...$)
# to avoid consuming the opening $$ as two inline $ tokens.
_PROTECTED_RE = re.compile(
    r"(```[\s\S]*?```|\$\$[\s\S]*?\$\$|(?<!\$)\$(?!\$)(?:[^$\\]|\\.)+\$(?!\$)|!\[.*?\]\(.*?\))",
    re.MULTILINE,
)

_PLACEHOLDER_FMT = "\x00PROTECTED_{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00PROTECTED_(\d+)\x00")


def _hard_split(text: str, chunk_size: int) -> list[str]:
    """Split an oversized text block into pieces ≤ chunk_size.

    Tries sentence boundaries first (``". "``), falls back to hard cut.
    Avoids cutting through ``\\x00PROTECTED_N\\x00`` placeholder tokens.
    """
    if len(text) <= chunk_size:
        return [text]
    parts: list[str] = []
    while len(text) > chunk_size:
        cut = text.rfind(". ", 0, chunk_size)
        if cut == -1 or cut < chunk_size // 4:
            cut = chunk_size  # hard cut
        else:
            cut += 2  # include ". "
        # Ensure we don't split inside a placeholder token
        cut = _adjust_for_placeholder(text, cut)
        parts.append(text[:cut])
        text = text[cut:]
    if text:
        parts.append(text)
    return parts


def _adjust_for_placeholder(text: str, cut: int) -> int:
    """Move cut point outside any placeholder span it would bisect."""
    # Find the last placeholder start before cut
    last_start = text.rfind("\x00PROTECTED_", 0, cut)
    if last_start == -1:
        return cut
    # Find the closing NUL of that placeholder
    end = text.find("\x00", last_start + 1)
    if end == -1:
        return cut
    end += 1  # include the closing NUL
    if cut < end:
        # cut falls inside the placeholder — move past it
        return end
    return cut


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """Split markdown text into translatable chunks respecting structure.

    Protected blocks (code fences, display math, images) are replaced with
    placeholders before splitting to prevent them from being broken across
    chunks. After splitting, placeholders are restored.

    Args:
        text: Full markdown text.
        chunk_size: Target maximum chunk size in characters.

    Returns:
        List of text chunks.
    """
    # Mask protected blocks with placeholders
    protected: list[str] = []

    def _mask(m: re.Match) -> str:
        idx = len(protected)
        protected.append(m.group(0))
        return _PLACEHOLDER_FMT.format(idx)

    masked = _PROTECTED_RE.sub(_mask, text)

    # Split on paragraph boundaries
    paragraphs = re.split(r"\n{2,}", masked)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        # Oversized paragraph: flush current, then hard-split the paragraph
        if para_len > chunk_size:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            # Split on sentence boundaries or hard-cut
            for frag in _hard_split(para, chunk_size):
                chunks.append(frag)
            continue
        if current_len + para_len > chunk_size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2  # +2 for \n\n

    if current:
        chunks.append("\n\n".join(current))

    # Restore protected blocks in each chunk
    def _restore(chunk: str) -> str:
        return _PLACEHOLDER_RE.sub(lambda m: protected[int(m.group(1))], chunk)

    return [_restore(c) for c in chunks]


# ============================================================================
#  Translation via LLM
# ============================================================================

_TRANSLATE_PROMPT_HEADER = """\
翻译以下学术论文段落至{target_lang}。

重要事项：
- 保留所有 markdown 格式（#, **, ``, [links]、表格等）
- 保留 LaTeX 公式（$...$, $$...$$）不翻译
- 保留代码块（```...```）不翻译
- 保留图片引用（![...](...)）不翻译
- 保留作者姓名和引用格式（如 [Smith et al., 2023]）"""

_TRANSLATE_PROMPT_FOOTER = """\
- 只返回翻译文本，不要任何解释

原文：
{text}"""

# Terminology annotation rules per target language
_TERMINOLOGY_RULES: dict[str, str] = {
    "zh": "- 对于专业术语，在首次出现时用「英文 (中文翻译)」格式",
    "ja": "- 専門用語は初出時に「英語 (日本語訳)」の形式で記載すること",
    "ko": "- 전문 용어는 처음 등장할 때 「영어 (한국어 번역)」 형식을 사용",
}


def _build_translate_prompt(text: str, target_lang: str, lang_name: str) -> str:
    """Build the translation prompt with language-appropriate terminology rule."""
    header = _TRANSLATE_PROMPT_HEADER.format(target_lang=lang_name)
    rule = _TERMINOLOGY_RULES.get(target_lang)
    parts = [header]
    if rule:
        parts.append(rule)
    parts.append(_TRANSLATE_PROMPT_FOOTER.format(text=text))
    return "\n".join(parts)


def _translate_chunk(text: str, target_lang: str, config: Config, timeout: int | None = None) -> str:
    """Translate a single chunk via LLM.

    Args:
        text: Text chunk to translate.
        target_lang: Target language code.
        config: Global config for LLM access.
        timeout: Optional timeout override.

    Returns:
        Translated text.
    """
    from scholaraio.metrics import call_llm

    lang_name = _LANG_NAMES.get(target_lang, target_lang)
    prompt = _build_translate_prompt(text, target_lang, lang_name)
    result = call_llm(
        prompt,
        config,
        json_mode=False,
        timeout=timeout or config.llm.timeout_clean,
        purpose="translate",
    )
    return result.content.strip()


# ============================================================================
#  Public API
# ============================================================================


# Skip reason constants for translate_paper
SKIP_NO_MD = "no_paper_md"
SKIP_ALREADY_EXISTS = "already_exists"
SKIP_EMPTY = "empty_source"
SKIP_SAME_LANG = "same_language"


def translate_paper(
    paper_dir: Path,
    config: Config,
    *,
    target_lang: str | None = None,
    force: bool = False,
) -> Path | None:
    """Translate a paper's markdown to the target language.

    The translation is saved as ``paper_{lang}.md`` in the same directory.
    Original ``paper.md`` is preserved.

    Sets ``translate_paper.skip_reason`` to a constant string when returning
    ``None``, so callers can distinguish the cause (e.g. ``SKIP_NO_MD``,
    ``SKIP_SAME_LANG``).

    Args:
        paper_dir: Paper directory containing ``paper.md``.
        config: Global config.
        target_lang: Target language code, defaults to ``config.translate.target_lang``.
        force: Re-translate even if translation file already exists.

    Returns:
        Path to the translated file, or ``None`` if skipped/failed.
    """
    lang = target_lang or config.translate.target_lang
    md_path = paper_dir / "paper.md"
    out_path = paper_dir / f"paper_{lang}.md"

    if not md_path.exists():
        _log.debug("no paper.md in %s, skipping", paper_dir.name)
        translate_paper.skip_reason = SKIP_NO_MD  # type: ignore[attr-defined]
        return None

    if out_path.exists() and not force:
        _log.debug("translation already exists: %s", out_path.name)
        translate_paper.skip_reason = SKIP_ALREADY_EXISTS  # type: ignore[attr-defined]
        return None

    text = md_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        translate_paper.skip_reason = SKIP_EMPTY  # type: ignore[attr-defined]
        return None

    # Detect source language — skip if already target
    src_lang = detect_language(text)
    if src_lang == lang:
        _log.debug("paper already in target language (%s), skipping", lang)
        translate_paper.skip_reason = SKIP_SAME_LANG  # type: ignore[attr-defined]
        return None

    # Chunk and translate
    chunk_size = config.translate.chunk_size
    chunks = _split_into_chunks(text, chunk_size)
    _log.debug("translating %s: %d chunks, target=%s", paper_dir.name, len(chunks), lang)

    translated_chunks: list[str] = []
    for i, chunk in enumerate(chunks):
        try:
            translated = _translate_chunk(chunk, lang, config)
            translated_chunks.append(translated)
            _log.debug("  chunk %d/%d done (%d chars)", i + 1, len(chunks), len(translated))
        except Exception as e:
            _log.error("  chunk %d/%d failed: %s", i + 1, len(chunks), e)
            translated_chunks.append(chunk)  # keep original on failure

    result = "\n\n".join(translated_chunks)
    out_path.write_text(result, encoding="utf-8")
    _log.debug("translation saved: %s (%d chars)", out_path.name, len(result))

    # Record translation metadata in meta.json
    _record_translation_meta(paper_dir, lang, src_lang, config)

    return out_path


def batch_translate(
    papers_dir: Path,
    config: Config,
    *,
    target_lang: str | None = None,
    force: bool = False,
    paper_ids: set[str] | None = None,
) -> dict[str, int]:
    """Batch translate all papers in the library.

    Args:
        papers_dir: Papers directory.
        config: Global config.
        target_lang: Target language code.
        force: Re-translate existing translations.
        paper_ids: Optional set of paper UUIDs to limit translation scope.

    Returns:
        Stats dict with ``translated``, ``skipped``, ``failed`` counts.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from scholaraio.papers import iter_paper_dirs, read_meta

    lang = target_lang or config.translate.target_lang
    workers = config.translate.concurrency
    stats = {"translated": 0, "skipped": 0, "failed": 0}

    dirs = list(iter_paper_dirs(papers_dir))
    if paper_ids:
        filtered = []
        for d in dirs:
            try:
                meta = read_meta(d)
                if meta.get("id") in paper_ids:
                    filtered.append(d)
            except Exception as e:
                _log.debug("failed to read meta for %s: %s", d.name, e)
        dirs = filtered

    def _do_one(pdir: Path) -> str:
        try:
            result = translate_paper(pdir, config, target_lang=lang, force=force)
            if result is None:
                return "skipped"
            return "translated"
        except Exception as e:
            _log.error("translation failed for %s: %s", pdir.name, e)
            return "failed"

    if workers > 1 and len(dirs) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(dirs))) as pool:
            futures = {pool.submit(_do_one, d): d for d in dirs}
            for fut in as_completed(futures):
                status = fut.result()
                stats[status] = stats.get(status, 0) + 1
    else:
        for pdir in dirs:
            status = _do_one(pdir)
            stats[status] = stats.get(status, 0) + 1

    return stats


def _record_translation_meta(paper_dir: Path, target_lang: str, src_lang: str, config: Config) -> None:
    """Record translation info in meta.json."""
    from scholaraio.papers import read_meta, write_meta

    try:
        data = read_meta(paper_dir)
        translations = data.get("translations", {})
        translations[target_lang] = {
            "file": f"paper_{target_lang}.md",
            "source_lang": src_lang,
            "translated_at": datetime.now().isoformat(timespec="seconds"),
            "model": config.llm.model,
        }
        data["translations"] = translations
        write_meta(paper_dir, data)
    except Exception as e:
        _log.debug("failed to record translation meta: %s", e)
