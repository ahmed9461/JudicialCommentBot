"""Normalized research candidate models."""

from pydantic import BaseModel, Field, HttpUrl, model_validator


class CaseCandidate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    case_number: str | None = None
    court_name: str | None = None
    judgment_year: str | None = None
    decision_number: str | None = None
    decision_date: str | None = None
    appeal_court_name: str | None = None
    source_name: str = Field(min_length=2, max_length=200)
    source_url: HttpUrl
    pdf_url: HttpUrl | None = None
    pdf_page_start: int | None = Field(default=None, ge=1)
    pdf_page_end: int | None = Field(default=None, ge=1)

    # Provenance populated only by the deterministic official catalog.  A
    # verified range is reusable only while the downloaded official collection
    # still has the same SHA-256 that was indexed.
    catalog_key: str | None = None
    catalog_pdf_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    catalog_range_verified: bool = False

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
        if self.catalog_range_verified:
            if not self.catalog_key or not self.catalog_pdf_sha256 or not self.has_page_range:
                raise ValueError(
                    "Verified catalog provenance requires catalog key, PDF SHA-256 and exact page range"
                )
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
