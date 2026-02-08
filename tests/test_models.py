"""Unit tests for SQLAlchemy ORM model metadata.

These tests inspect model table definitions, columns, indexes, and computed
expressions without requiring a database connection.
"""

from sqlalchemy import Computed

from app.db.models import KBChunk, KBFile, Repo


class TestTableNames:
    """Verify each model maps to the expected table name."""

    def test_repo_table_name(self) -> None:
        assert Repo.__tablename__ == "repos"

    def test_kb_file_table_name(self) -> None:
        assert KBFile.__tablename__ == "kb_files"

    def test_kb_chunk_table_name(self) -> None:
        assert KBChunk.__tablename__ == "kb_chunks"


class TestRepoColumns:
    """Verify Repo model has the expected columns."""

    def test_has_expected_columns(self) -> None:
        column_names = {c.name for c in Repo.__table__.columns}
        expected = {"id", "owner", "name", "default_branch", "updated_at"}
        assert column_names == expected


class TestKBFileColumns:
    """Verify KBFile model has the expected columns."""

    def test_has_expected_columns(self) -> None:
        column_names = {c.name for c in KBFile.__table__.columns}
        expected = {"id", "repo_id", "path", "commit_sha", "sha256", "updated_at"}
        assert column_names == expected


class TestKBChunkColumns:
    """Verify KBChunk model has the expected columns."""

    def test_has_expected_columns(self) -> None:
        column_names = {c.name for c in KBChunk.__table__.columns}
        expected = {
            "id",
            "repo_id",
            "file_id",
            "path",
            "commit_sha",
            "start_line",
            "end_line",
            "content",
            "content_tsv",
            "updated_at",
        }
        assert column_names == expected

    def test_content_tsv_is_computed(self) -> None:
        col = KBChunk.__table__.c.content_tsv
        assert isinstance(col.computed, Computed)

    def test_content_tsv_expression_uses_english_tsvector(self) -> None:
        col = KBChunk.__table__.c.content_tsv
        expr_text = str(col.computed.sqltext)
        assert "to_tsvector('english', content)" in expr_text


class TestIndexes:
    """Verify expected GIN indexes exist on models."""

    def test_kb_file_path_trgm_index(self) -> None:
        index_names = {idx.name for idx in KBFile.__table__.indexes}
        assert "ix_kb_files_path_trgm" in index_names

    def test_kb_chunk_content_tsv_index(self) -> None:
        index_names = {idx.name for idx in KBChunk.__table__.indexes}
        assert "ix_kb_chunks_content_tsv" in index_names
