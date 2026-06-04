import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Verdict(str, enum.Enum):
    MATCH = "match"  # ◯
    MISMATCH = "mismatch"  # ☓
    UNAVAILABLE = "unavailable"  # △


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(1024))
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    citations: Mapped[list["CitationCheck"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class CitationCheck(Base):
    __tablename__ = "citation_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    ref_number: Mapped[int] = mapped_column(Integer)
    reference_text: Mapped[str] = mapped_column(Text)
    body_excerpt: Mapped[str] = mapped_column(Text, default="")
    source_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    verdict: Mapped[str] = mapped_column(String(32), default=Verdict.UNAVAILABLE.value)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence_main: Mapped[str] = mapped_column(Text, default="")
    evidence_source: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    paper: Mapped["Paper"] = relationship(back_populates="citations")
