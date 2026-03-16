"""Tests for translate.py — language detection, chunk splitting, and prompt building.

Covers pure-function logic that doesn't require LLM calls.
"""

from __future__ import annotations

from scholaraio.translate import (
    _build_translate_prompt,
    _split_into_chunks,
    detect_language,
)


class TestDetectLanguage:
    """Language detection heuristics."""

    def test_english_text(self):
        assert detect_language("This is an English sentence about turbulence modeling.") == "en"

    def test_chinese_text(self):
        assert detect_language("本文提出了一种新型湍流模型，用于边界层流动的数值模拟。") == "zh"

    def test_japanese_mixed_kanji_kana(self):
        assert detect_language("この論文では境界層の乱流モデルについて述べる。") == "ja"

    def test_japanese_kana_only(self):
        """Kana-dominant text (few/no kanji) should still be detected as Japanese."""
        assert detect_language("これはテストです。すべてひらがなとカタカナで書かれています。") == "ja"

    def test_korean_text(self):
        assert detect_language("이 논문은 경계층 난류 모델에 대해 설명합니다.") == "ko"

    def test_empty_text_defaults_to_english(self):
        assert detect_language("") == "en"

    def test_math_only_defaults_to_english(self):
        assert detect_language("$$E = mc^2$$  $\\alpha + \\beta$") == "en"

    def test_code_blocks_stripped(self):
        """Code blocks should not influence language detection."""
        text = "这是中文文本。\n```python\nprint('hello world')\n```\n继续中文。"
        assert detect_language(text) == "zh"


class TestSplitIntoChunks:
    """Chunk splitting with placeholder protection."""

    def test_small_text_single_chunk(self):
        text = "Hello world.\n\nSecond paragraph."
        chunks = _split_into_chunks(text, chunk_size=1000)
        assert len(chunks) == 1
        assert "Hello world." in chunks[0]
        assert "Second paragraph." in chunks[0]

    def test_respects_chunk_size(self):
        text = "A" * 100 + "\n\n" + "B" * 100
        chunks = _split_into_chunks(text, chunk_size=120)
        assert len(chunks) == 2

    def test_code_block_preserved_intact(self):
        code = "```python\nfor i in range(10):\n    print(i)\n```"
        text = f"Before code.\n\n{code}\n\nAfter code."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert code in full

    def test_display_math_preserved_intact(self):
        math = "$$\\int_0^\\infty e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}$$"
        text = f"Some text.\n\n{math}\n\nMore text."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert math in full

    def test_inline_math_preserved_intact(self):
        text = "The result is $\\alpha + \\beta = \\gamma$ which is important."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert "$\\alpha + \\beta = \\gamma$" in full

    def test_inline_math_not_split_across_chunks(self):
        """Inline math should not be broken when hard-splitting oversized text."""
        formula = "$E = mc^2$"
        big_text = "Word. " * 80 + formula + " " + "Word. " * 80
        chunks = _split_into_chunks(big_text, chunk_size=200)
        # The formula should appear complete in exactly one chunk
        found = [c for c in chunks if formula in c]
        assert len(found) == 1

    def test_image_preserved_intact(self):
        img = "![Figure 1](images/fig1.png)"
        text = f"Caption above.\n\n{img}\n\nCaption below."
        chunks = _split_into_chunks(text, chunk_size=5000)
        full = "\n\n".join(chunks)
        assert img in full

    def test_protected_blocks_not_split_across_chunks(self):
        """A code block should stay in one chunk even when splitting."""
        code = "```\n" + "x\n" * 50 + "```"
        text = "Intro.\n\n" + code + "\n\nEnd."
        chunks = _split_into_chunks(text, chunk_size=80)
        # The code block should appear completely in exactly one chunk
        found = [c for c in chunks if "```" in c]
        assert len(found) >= 1
        for c in found:
            assert c.count("```") % 2 == 0, "Code fence should not be split"

    def test_oversized_paragraph_gets_secondary_split(self):
        """A single paragraph larger than chunk_size is further split."""
        big_para = "Word. " * 500  # ~3000 chars, no double-newlines
        chunks = _split_into_chunks(big_para, chunk_size=500)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 600  # allow some margin

    def test_order_preserved(self):
        paragraphs = [f"Paragraph {i}." for i in range(5)]
        text = "\n\n".join(paragraphs)
        chunks = _split_into_chunks(text, chunk_size=30)
        rejoined = "\n\n".join(chunks)
        for p in paragraphs:
            assert p in rejoined


class TestBuildTranslatePrompt:
    """Prompt construction with terminology rules."""

    def test_chinese_includes_terminology_rule(self):
        prompt = _build_translate_prompt("Hello", "zh", "中文")
        assert "「英文 (中文翻译)」" in prompt

    def test_japanese_includes_terminology_rule(self):
        prompt = _build_translate_prompt("Hello", "ja", "日本語")
        assert "英語 (日本語訳)" in prompt

    def test_english_has_no_terminology_rule(self):
        prompt = _build_translate_prompt("Hello", "en", "English")
        # Should not contain any CJK terminology format
        assert "「" not in prompt

    def test_prompt_contains_source_text(self):
        prompt = _build_translate_prompt("Test input text", "zh", "中文")
        assert "Test input text" in prompt

    def test_prompt_contains_target_language(self):
        prompt = _build_translate_prompt("text", "de", "Deutsch")
        assert "Deutsch" in prompt
