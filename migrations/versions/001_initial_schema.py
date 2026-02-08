"""Initial schema: repos, kb_files, kb_chunks with GIN indexes.

Revision ID: 001
Revises:
Create Date: 2026-02-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create repos, kb_files, and kb_chunks tables with indexes."""
    # Enable pg_trgm extension for trigram similarity searches
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # --- repos table ---
    op.create_table(
        "repos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("default_branch", sa.String(255), nullable=False, server_default="main"),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("owner", "name", name="uq_repos_owner_name"),
    )

    # --- kb_files table ---
    op.create_table(
        "kb_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "repo_id",
            sa.Integer,
            sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("repo_id", "path", name="uq_kb_files_repo_path"),
    )

    # Trigram GIN index for fuzzy filename search (DB-05)
    op.create_index(
        "ix_kb_files_path_trgm",
        "kb_files",
        ["path"],
        postgresql_using="gin",
        postgresql_ops={"path": "gin_trgm_ops"},
    )

    # --- kb_chunks table ---
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "repo_id",
            sa.Integer,
            sa.ForeignKey("repos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("kb_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("start_line", sa.Integer, nullable=False),
        sa.Column("end_line", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "content_tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # GIN index on tsvector column for full-text search (DB-04)
    op.create_index(
        "ix_kb_chunks_content_tsv",
        "kb_chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Drop all tables and pg_trgm extension."""
    op.drop_table("kb_chunks")
    op.drop_table("kb_files")
    op.drop_table("repos")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")
