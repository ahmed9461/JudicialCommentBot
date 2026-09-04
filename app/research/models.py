"""Normalized research candidate models."""

from pydantic import BaseModel, Field, HttpUrl


class CaseCandidate(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    case_number: str | None = None
    court_name: str | None = None
    judgment_year: str | None = None
    source_name: str = Field(min_length=2, max_length=200)
    source_url: HttpUrl
    pdf_url: HttpUrl | None = None
    legal_issue: str = Field(min_length=3, max_length=2000)
    suitability_reason: str = Field(min_length=3, max_length=3000)
    estimated_score: int = Field(ge=0, le=100)

    @property
    def source_url_str(self) -> str:
        return str(self.source_url)

    @property
    def pdf_url_str(self) -> str | None:
        return str(self.pdf_url) if self.pdf_url else None
