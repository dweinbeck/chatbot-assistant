"""Content chunking engine for splitting files at semantic boundaries.

Splits markdown files at ATX heading boundaries and code files at
function/class boundaries. Falls back to line-based chunking when
no semantic boundaries are detected.
"""

import os
import re

# Regex patterns for detecting function/class boundaries per language.
# Each pattern matches lines that typically start a new logical block.
BOUNDARY_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(
        r"^(?:class |def |async def )", re.MULTILINE
    ),
    ".js": re.compile(
        r"^(?:function |class |const \w+ = (?:async )?\(|export (?:default )?(?:function|class))",
        re.MULTILINE,
    ),
    ".ts": re.compile(
        r"^(?:function |class |const \w+ = (?:async )?\("
        r"|export (?:default )?(?:function|class)|interface |type )",
        re.MULTILINE,
    ),
    ".tsx": re.compile(
        r"^(?:function |class |const \w+ = (?:async )?\("
        r"|export (?:default )?(?:function|class)|interface |type )",
        re.MULTILINE,
    ),
    ".go": re.compile(r"^(?:func |type \w+ struct)", re.MULTILINE),
    ".rs": re.compile(
        r"^(?:fn |pub fn |impl |struct |enum |trait )", re.MULTILINE
    ),
    ".java": re.compile(
        r"^(?:\s*(?:public|private|protected)?\s*(?:static\s+)?(?:class |interface ))",
        re.MULTILINE,
    ),
}

# ATX heading pattern for markdown splitting.
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)


def chunk_markdown(content: str) -> list[tuple[int, int, str]]:
    """Split markdown content at ATX heading boundaries.

    Each heading starts a new chunk. Content before the first heading
    becomes its own chunk. Returns an empty list for empty content.

    Args:
        content: Raw markdown text.

    Returns:
        List of (start_line, end_line, chunk_text) tuples with 1-indexed lines.
    """
    if not content or not content.strip():
        return []

    lines = content.split("\n")
    chunks: list[tuple[int, int, str]] = []
    current_start = 0  # 0-indexed

    for i, line in enumerate(lines):
        if _HEADING_PATTERN.match(line) and i > 0:
            chunk_text = "\n".join(lines[current_start:i])
            if chunk_text.strip():
                chunks.append((current_start + 1, i, chunk_text))
            current_start = i

    # Final chunk from last boundary to end of file
    chunk_text = "\n".join(lines[current_start:])
    if chunk_text.strip():
        chunks.append((current_start + 1, len(lines), chunk_text))

    return chunks


def chunk_code(
    content: str,
    ext: str,
    min_lines: int = 200,
    max_lines: int = 400,
) -> list[tuple[int, int, str]]:
    """Split code content at function/class boundaries with fallback.

    For supported languages, detects function/class definition boundaries
    and splits there. Merges small chunks and sub-splits large ones.
    Falls back to fixed-size line-based splitting for unknown extensions
    or when no boundaries are found.

    Args:
        content: Raw source code text.
        ext: File extension including the dot (e.g. ".py", ".js").
        min_lines: Minimum desired chunk size in lines (for merging).
        max_lines: Maximum chunk size in lines (for splitting).

    Returns:
        List of (start_line, end_line, chunk_text) tuples with 1-indexed lines.
    """
    lines = content.split("\n")
    total = len(lines)

    if total == 0:
        return []

    # Small files: return as single chunk regardless of boundaries
    if total <= max_lines:
        return [(1, total, content)]

    pattern = BOUNDARY_PATTERNS.get(ext)

    # Find boundary line numbers (0-indexed)
    boundary_indices: list[int] = []
    if pattern is not None:
        for match in pattern.finditer(content):
            pos = match.start()
            line_num = content[:pos].count("\n")
            boundary_indices.append(line_num)

    # No boundaries found or unknown extension: fall back to line-based chunks
    if not boundary_indices:
        return _fallback_chunks(lines, max_lines)

    # Build raw chunks from boundary positions
    raw_chunks = _split_at_boundaries(boundary_indices, total)

    # Merge small chunks and sub-split large chunks
    merged = _merge_and_split(raw_chunks, min_lines, max_lines, total)

    # Convert to output format with text content
    result: list[tuple[int, int, str]] = []
    for start_idx, end_idx in merged:
        chunk_text = "\n".join(lines[start_idx:end_idx])
        result.append((start_idx + 1, end_idx, chunk_text))

    return result


def chunk_file(
    content: str,
    path: str,
    min_lines: int = 200,
    max_lines: int = 400,
) -> list[tuple[int, int, str]]:
    """Dispatch to the correct chunker based on file extension.

    Routes .md and .mdx files to chunk_markdown, everything else
    to chunk_code.

    Args:
        content: Raw file content.
        path: File path used to determine extension.
        min_lines: Minimum chunk size for code files.
        max_lines: Maximum chunk size for code files.

    Returns:
        List of (start_line, end_line, chunk_text) tuples with 1-indexed lines.
    """
    _, ext = os.path.splitext(path)
    ext_lower = ext.lower()

    if ext_lower in (".md", ".mdx"):
        return chunk_markdown(content)

    return chunk_code(content, ext_lower, min_lines=min_lines, max_lines=max_lines)


def _fallback_chunks(
    lines: list[str], max_lines: int
) -> list[tuple[int, int, str]]:
    """Split lines into fixed-size chunks of max_lines each.

    The last chunk contains the remainder and may be smaller than max_lines.

    Returns:
        List of (start_line, end_line, chunk_text) tuples with 1-indexed lines.
    """
    total = len(lines)
    chunks: list[tuple[int, int, str]] = []
    for i in range(0, total, max_lines):
        end = min(i + max_lines, total)
        chunk_text = "\n".join(lines[i:end])
        chunks.append((i + 1, end, chunk_text))
    return chunks


def _split_at_boundaries(
    boundary_indices: list[int], total_lines: int
) -> list[tuple[int, int]]:
    """Create (start, end) index pairs from boundary positions.

    Boundaries are 0-indexed line numbers. Returns 0-indexed half-open
    intervals [start, end) suitable for slicing.
    """
    # Ensure boundaries are sorted and deduplicated
    boundaries = sorted(set(boundary_indices))

    chunks: list[tuple[int, int]] = []

    # Content before first boundary (if first boundary is not at line 0)
    if boundaries[0] > 0:
        chunks.append((0, boundaries[0]))

    # Chunks between consecutive boundaries
    for i in range(len(boundaries)):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else total_lines
        chunks.append((start, end))

    return chunks


def _merge_and_split(
    chunks: list[tuple[int, int]],
    min_lines: int,
    max_lines: int,
    total_lines: int,
) -> list[tuple[int, int]]:
    """Merge chunks smaller than min_lines, split those larger than max_lines.

    Operates on 0-indexed half-open intervals [start, end).
    """
    # Phase 1: Merge small chunks with their successor
    merged: list[tuple[int, int]] = []
    i = 0
    while i < len(chunks):
        start, end = chunks[i]
        size = end - start

        # Merge forward while the current accumulated chunk is below min_lines
        while size < min_lines and i + 1 < len(chunks):
            i += 1
            _, end = chunks[i]
            size = end - start

        merged.append((start, end))
        i += 1

    # Phase 2: Sub-split any chunk that exceeds max_lines
    result: list[tuple[int, int]] = []
    for start, end in merged:
        size = end - start
        if size <= max_lines:
            result.append((start, end))
        else:
            # Split into max_lines-sized sub-chunks
            for sub_start in range(start, end, max_lines):
                sub_end = min(sub_start + max_lines, end)
                result.append((sub_start, sub_end))

    return result
