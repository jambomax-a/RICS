from datetime import datetime

from pydantic import BaseModel


class CitationCheckOut(BaseModel):
    id: int
    ref_number: int
    reference_text: str
    body_excerpt: str
    source_title: str | None
    source_url: str | None
    verdict: str
    reason: str
    evidence_main: str
    evidence_source: str
    has_manual_upload: bool

    model_config = {"from_attributes": True}


class PaperSummary(BaseModel):
    id: int
    title: str
    filename: str
    created_at: datetime
    citation_count: int
    match_count: int
    mismatch_count: int
    unavailable_count: int


class PaperDetail(BaseModel):
    id: int
    title: str
    filename: str
    created_at: datetime
    citations: list[CitationCheckOut]


class PaperTitleUpdate(BaseModel):
    title: str
