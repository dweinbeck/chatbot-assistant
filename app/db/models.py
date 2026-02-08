"""SQLAlchemy ORM models for the knowledge base schema."""

from datetime import datetime

from sqlalchemy import (
    Computed,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class Repo(Base):
    """A GitHub repository tracked for knowledge base indexing."""

    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repos_owner_name"),)


class KBFile(Base):
    """A file within a tracked repository."""

    __tablename__ = "kb_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1024))
    commit_sha: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ix_kb_files_path_trgm",
            "path",
            postgresql_using="gin",
            postgresql_ops={"path": "gin_trgm_ops"},
        ),
        UniqueConstraint("repo_id", "path", name="uq_kb_files_repo_path"),
    )


class KBChunk(Base):
    """A searchable chunk of content from a knowledge base file."""

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"))
    file_id: Mapped[int] = mapped_column(ForeignKey("kb_files.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1024))
    commit_sha: Mapped[str] = mapped_column(String(40))
    start_line: Mapped[int]
    end_line: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_kb_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )
