"""Normalized research candidate models."""

from pydantic import BaseModel, Field, HttpUrl, model_validator


class CaseCandidate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    case_number: str | None = None
    court_name: str | None = None
    judgment_year: str | None = None
    source_name: str = Field(min_length=2, max_length=200)
    source_url: HttpUrl
    pdf_url: HttpUrl | None = None
    pdf_page_start: int | None = Field(default=None, ge=1)
    pdf_page_end: int | None = Field(default=None, ge=1)
    legal_issue: str = Field(min_length=3, max_length=2000)
    suitability_reason: str = Field(min_length=3, max_length=3000)
    estimated_score: int = Field(ge=0, le=100)
    subject_relevance: int | None = Field(default=None, ge=0, le=40)
    legal_issue_clarity: int | None = Field(default=None, ge=0, le=20)
    reasoning_quality: int | None = Field(default=None, ge=0, le=15)
    academic_commentary_value: int | None = Field(default=None, ge=0, le=15)

    @model_validator(mode="after")
    def validate_page_range(self) -> "CaseCandidate":
        if (self.pdf_page_start is None) != (self.pdf_page_end is None):
            raise ValueError("PDF page range must include both start and end")
        if self.pdf_page_start is not None and self.pdf_page_end is not None:
            if self.pdf_page_end < self.pdf_page_start:
                raise ValueError("PDF page range end must be >= start")
        return self

    @property
    def source_url_str(self) -> str:
        return str(self.source_url)

    @property
    def pdf_url_str(self) -> str | None:
        return str(self.pdf_url) if self.pdf_url else None

    @property
    def has_page_range(self) -> bool:
        return self.pdf_page_start is not None and self.pdf_page_end is not None
