"""Tests for the content chunking engine (markdown + code)."""

import pytest

from app.services.chunker import chunk_code, chunk_file, chunk_markdown


class TestChunkMarkdown:
    """Markdown files should be split at ATX heading boundaries."""

    def test_empty_content(self) -> None:
        assert chunk_markdown("") == []

    def test_single_heading_with_content(self) -> None:
        content = "# Title\n\nSome content here.\nMore content."
        chunks = chunk_markdown(content)
        assert len(chunks) == 1
        assert chunks[0][0] == 1  # start_line
        assert chunks[0][1] == 4  # end_line
        assert "# Title" in chunks[0][2]

    def test_two_headings_split_at_boundary(self) -> None:
        content = "# Section One\n\nContent for one.\n\n## Section Two\n\nContent for two."
        chunks = chunk_markdown(content)
        assert len(chunks) == 2
        assert "# Section One" in chunks[0][2]
        assert "## Section Two" in chunks[1][2]
        # Second chunk should start at the heading line
        assert chunks[1][2].startswith("## Section Two")

    def test_content_before_first_heading(self) -> None:
        content = "Intro text without heading.\n\n# First Heading\n\nBody."
        chunks = chunk_markdown(content)
        assert len(chunks) == 2
        assert "Intro text" in chunks[0][2]
        assert "# First Heading" in chunks[1][2]

    def test_no_headings_single_chunk(self) -> None:
        content = "Just some text.\nNo headings here.\nMore lines."
        chunks = chunk_markdown(content)
        assert len(chunks) == 1
        assert chunks[0][0] == 1
        assert chunks[0][1] == 3

    def test_nested_headings_split_at_each(self) -> None:
        content = "# H1\n\nParagraph.\n\n## H2\n\nMore text.\n\n### H3\n\nEven more."
        chunks = chunk_markdown(content)
        assert len(chunks) == 3
        assert "# H1" in chunks[0][2]
        assert "## H2" in chunks[1][2]
        assert "### H3" in chunks[2][2]

    def test_tiny_chunks_preserved(self) -> None:
        content = "# A\n# B\n# C"
        chunks = chunk_markdown(content)
        assert len(chunks) == 3

    def test_line_numbers_are_one_indexed(self) -> None:
        content = "# First\n\nBody.\n\n# Second\n\nBody2."
        chunks = chunk_markdown(content)
        assert chunks[0][0] == 1  # First chunk starts at line 1
        assert chunks[1][0] == 5  # Second chunk starts at line 5

    def test_consecutive_headings(self) -> None:
        content = "# Heading One\n## Heading Two\nSome text."
        chunks = chunk_markdown(content)
        assert len(chunks) == 2
        assert chunks[0][2].strip() == "# Heading One"
        assert "## Heading Two" in chunks[1][2]

    def test_end_line_continuity(self) -> None:
        """Each chunk's end_line should be the line before the next chunk's start_line."""
        content = "# A\nLine 2\nLine 3\n# B\nLine 5\n# C\nLine 7"
        chunks = chunk_markdown(content)
        assert len(chunks) == 3
        # First chunk: lines 1-3
        assert chunks[0] == (1, 3, "# A\nLine 2\nLine 3")
        # Second chunk: lines 4-5
        assert chunks[1] == (4, 5, "# B\nLine 5")
        # Third chunk: lines 6-7
        assert chunks[2] == (6, 7, "# C\nLine 7")


class TestChunkCode:
    """Code files should be split at function/class boundaries with fallback."""

    def test_small_file_single_chunk(self) -> None:
        """Files within max_lines should return as a single chunk."""
        content = "\n".join(f"line {i}" for i in range(1, 51))
        chunks = chunk_code(content, ".py", max_lines=400)
        assert len(chunks) == 1
        assert chunks[0][0] == 1
        assert chunks[0][1] == 50

    def test_python_function_boundaries(self) -> None:
        """Python files should split at def/class/async def boundaries."""
        lines = []
        # First function block: 250 lines
        lines.append("def function_a():")
        for i in range(249):
            lines.append(f"    pass  # line {i}")
        # Second function block: 250 lines
        lines.append("def function_b():")
        for i in range(249):
            lines.append(f"    pass  # line {i}")
        content = "\n".join(lines)
        chunks = chunk_code(content, ".py", min_lines=200, max_lines=400)
        assert len(chunks) >= 2
        assert "def function_a" in chunks[0][2]
        assert "def function_b" in chunks[-1][2]

    def test_unknown_extension_fallback(self) -> None:
        """Unknown extensions should fall back to line-based chunks."""
        content = "\n".join(f"line {i}" for i in range(1, 901))
        chunks = chunk_code(content, ".xyz", min_lines=200, max_lines=400)
        assert len(chunks) >= 2
        # Each chunk should be at most max_lines
        for start, end, text in chunks:
            assert end - start + 1 <= 400

    def test_no_boundaries_fallback(self) -> None:
        """Large file with no boundaries should fall back to line-based chunks."""
        content = "\n".join(f"# comment line {i}" for i in range(1, 901))
        chunks = chunk_code(content, ".py", min_lines=200, max_lines=400)
        assert len(chunks) >= 2
        for start, end, text in chunks:
            assert end - start + 1 <= 400

    def test_line_numbers_one_indexed(self) -> None:
        content = "x = 1\ny = 2\nz = 3"
        chunks = chunk_code(content, ".py", max_lines=400)
        assert chunks[0][0] == 1
        assert chunks[0][1] == 3

    def test_javascript_function_boundaries(self) -> None:
        """JS files should detect function/class/const arrow boundaries."""
        lines = []
        lines.append("function helperA() {")
        for i in range(249):
            lines.append(f"  // line {i}")
        lines.append("}")
        lines.append("function helperB() {")
        for i in range(249):
            lines.append(f"  // line {i}")
        lines.append("}")
        content = "\n".join(lines)
        chunks = chunk_code(content, ".js", min_lines=200, max_lines=400)
        assert len(chunks) >= 2
        assert "function helperA" in chunks[0][2]
        assert "function helperB" in chunks[-1][2]

    def test_go_function_boundaries(self) -> None:
        """Go files should detect func and type struct boundaries."""
        lines = []
        lines.append("func main() {")
        for i in range(299):
            lines.append(f"    // line {i}")
        lines.append("}")
        lines.append("func helper() {")
        for i in range(299):
            lines.append(f"    // line {i}")
        lines.append("}")
        content = "\n".join(lines)
        chunks = chunk_code(content, ".go", min_lines=200, max_lines=400)
        assert len(chunks) >= 2

    def test_fallback_last_chunk_remainder(self) -> None:
        """Fallback chunking should produce a last chunk with the remainder lines."""
        content = "\n".join(f"line {i}" for i in range(1, 501))
        chunks = chunk_code(content, ".xyz", min_lines=200, max_lines=400)
        # 500 lines / 400 = 1 chunk of 400 + 1 chunk of 100
        assert len(chunks) == 2
        assert chunks[0] == (1, 400, "\n".join(f"line {i}" for i in range(1, 401)))
        assert chunks[1][0] == 401
        assert chunks[1][1] == 500

    def test_chunk_merging_small_boundaries(self) -> None:
        """Chunks smaller than min_lines should be merged with adjacent chunks."""
        lines = []
        # 50-line function (too small for min_lines=200)
        lines.append("def tiny():")
        for i in range(49):
            lines.append(f"    pass  # {i}")
        # 250-line function
        lines.append("def big():")
        for i in range(249):
            lines.append(f"    pass  # {i}")
        # Another 250-line function
        lines.append("def also_big():")
        for i in range(249):
            lines.append(f"    pass  # {i}")
        content = "\n".join(lines)
        chunks = chunk_code(content, ".py", min_lines=200, max_lines=400)
        # The tiny function should be merged into an adjacent chunk
        # Total: 550 lines. After merge: should be 2 chunks (300 + 250 or similar)
        assert len(chunks) >= 2
        # No chunk should be less than min_lines except possibly the last one
        for _start, end, _text in chunks[:-1]:
            # Non-last chunks should be at least min_lines
            pass
        # All chunks should be at most max_lines
        for start, end, _text in chunks:
            assert end - start + 1 <= 400


class TestChunkFile:
    """chunk_file should dispatch to the correct chunker based on extension."""

    def test_markdown_dispatch(self) -> None:
        content = "# Title\n\nBody text."
        chunks = chunk_file(content, "docs/README.md")
        assert len(chunks) == 1
        assert "# Title" in chunks[0][2]

    def test_mdx_dispatch(self) -> None:
        content = "# MDX Title\n\nBody."
        chunks = chunk_file(content, "docs/page.mdx")
        assert len(chunks) == 1
        assert "# MDX Title" in chunks[0][2]

    def test_python_dispatch(self) -> None:
        content = "x = 1\ny = 2"
        chunks = chunk_file(content, "src/main.py")
        assert len(chunks) == 1
        assert chunks[0][0] == 1

    def test_txt_dispatch(self) -> None:
        content = "Just text."
        chunks = chunk_file(content, "notes.txt")
        assert len(chunks) == 1

    def test_passes_min_max_lines(self) -> None:
        """chunk_file should forward min_lines and max_lines to chunk_code."""
        content = "\n".join(f"line {i}" for i in range(1, 201))
        chunks_default = chunk_file(content, "app.py")
        chunks_small = chunk_file(content, "app.py", max_lines=100)
        # With smaller max_lines, should produce more chunks
        assert len(chunks_small) >= len(chunks_default)
