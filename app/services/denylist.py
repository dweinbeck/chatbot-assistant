"""Denylist filter for files that should not be indexed.

Filters out binary files, junk directories, lock files, and oversized files
before they reach the chunking and indexing pipeline.
"""

import fnmatch

# Directory path segments that indicate junk/non-indexable content.
# Matching is done by checking if the segment appears anywhere in the path.
DENYLIST_DIRS: list[str] = [
    "node_modules/",
    "dist/",
    "build/",
    ".git/",
    "vendor/",
    "__pycache__/",
    ".tox/",
    ".venv/",
    ".mypy_cache/",
]

# Glob patterns for file extensions that should never be indexed.
DENYLIST_EXTENSIONS: list[str] = [
    "*.lock",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.ico",
    "*.pdf",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    "*.mp3",
    "*.mp4",
    "*.zip",
    "*.tar.gz",
    "*.exe",
    "*.dll",
    "*.so",
    "*.dylib",
    "*.min.js",
    "*.min.css",
    "*.map",
]

# Exact filenames that should be rejected regardless of directory.
DENYLIST_FILES: list[str] = [
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "go.sum",
    "composer.lock",
]

# Files larger than this threshold (in bytes) are rejected.
MAX_FILE_SIZE_BYTES: int = 500_000  # 500 KB


def is_denied(path: str, size_bytes: int | None = None) -> bool:
    """Check whether a file path should be excluded from indexing.

    Args:
        path: Relative file path (e.g. "src/main.py" or "node_modules/react/index.js").
        size_bytes: Optional file size in bytes. If provided and exceeds the
            threshold, the file is denied.

    Returns:
        True if the file should be skipped, False if it should be indexed.
    """
    # Normalise path to always have a leading slash for consistent matching
    normalised = f"/{path}"

    # Check directory patterns
    for dir_pattern in DENYLIST_DIRS:
        if f"/{dir_pattern}" in normalised:
            return True

    # Check extension patterns against the filename only
    filename = path.rsplit("/", maxsplit=1)[-1]
    for ext_pattern in DENYLIST_EXTENSIONS:
        if fnmatch.fnmatch(filename, ext_pattern):
            return True

    # Check exact filename matches
    if filename in DENYLIST_FILES:
        return True

    # Check file size threshold
    return size_bytes is not None and size_bytes > MAX_FILE_SIZE_BYTES
