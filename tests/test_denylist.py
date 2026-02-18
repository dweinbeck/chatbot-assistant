"""Tests for the denylist file filtering service."""

import pytest

from app.services.denylist import MAX_FILE_SIZE_BYTES, is_denied


class TestDenylistDirs:
    """Files inside denied directories should be rejected."""

    @pytest.mark.parametrize(
        "path",
        [
            "node_modules/react/index.js",
            "dist/bundle.js",
            "build/output.css",
            ".git/config",
            "vendor/lib/foo.go",
            "__pycache__/mod.pyc",
            ".tox/py312/lib/site.py",
            ".venv/bin/activate",
            ".mypy_cache/3.12/app.json",
            ".planning/research/SUMMARY.md",
            ".gsd/checkpoint.json",
        ],
    )
    def test_denied_directories(self, path: str) -> None:
        assert is_denied(path) is True

    def test_deeply_nested_denied_dir(self) -> None:
        assert is_denied("deep/nested/node_modules/pkg/file.js") is True

    def test_build_nested_in_project(self) -> None:
        assert is_denied("project/build/output.js") is True


class TestDenylistExtensions:
    """Files with denied extensions should be rejected."""

    @pytest.mark.parametrize(
        "path",
        [
            "logo.png",
            "photo.jpg",
            "icon.jpeg",
            "anim.gif",
            "icon.svg",
            "favicon.ico",
            "doc.pdf",
            "font.woff",
            "font.woff2",
            "font.ttf",
            "font.eot",
            "song.mp3",
            "video.mp4",
            "archive.zip",
            "archive.tar.gz",
            "program.exe",
            "library.dll",
            "library.so",
            "library.dylib",
        ],
    )
    def test_denied_binary_extensions(self, path: str) -> None:
        assert is_denied(path) is True

    def test_minified_js(self) -> None:
        assert is_denied("bundle.min.js") is True

    def test_minified_css(self) -> None:
        assert is_denied("styles.min.css") is True

    def test_sourcemap_file(self) -> None:
        assert is_denied("app.map") is True


class TestDenylistExactFiles:
    """Exact filename matches should be rejected."""

    @pytest.mark.parametrize(
        "path",
        [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "Cargo.lock",
            "poetry.lock",
            "Pipfile.lock",
            "go.sum",
            "composer.lock",
        ],
    )
    def test_denied_lock_files(self, path: str) -> None:
        assert is_denied(path) is True

    def test_nested_lock_file(self) -> None:
        assert is_denied("subdir/package-lock.json") is True


class TestDenylistSize:
    """Files exceeding the size threshold should be rejected."""

    def test_over_size_limit(self) -> None:
        assert is_denied("src/big.py", size_bytes=600_000) is True

    def test_exactly_at_limit(self) -> None:
        assert is_denied("src/exact.py", size_bytes=MAX_FILE_SIZE_BYTES) is False

    def test_over_limit_by_one(self) -> None:
        assert is_denied("src/exact.py", size_bytes=MAX_FILE_SIZE_BYTES + 1) is True

    def test_under_size_limit(self) -> None:
        assert is_denied("src/small.py", size_bytes=1000) is False

    def test_no_size_provided(self) -> None:
        assert is_denied("src/any.py") is False


class TestDenylistCleanPaths:
    """Files that should NOT be denied."""

    @pytest.mark.parametrize(
        "path",
        [
            "src/main.py",
            "README.md",
            "src/utils.ts",
            "docs/guide.md",
            "app/config.py",
            "lib/helper.go",
            "src/Component.tsx",
        ],
    )
    def test_allowed_files(self, path: str) -> None:
        assert is_denied(path) is False
