"""Structured academic commentary model."""

from pydantic import BaseModel, Field


class CommentaryDraft(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    facts_and_course_link: str = Field(min_length=80, max_length=12000)
    legal_issue: str = Field(min_length=50, max_length=8000)
    court_reasoning: str = Field(min_length=80, max_length=12000)
    comment_and_opinion: str = Field(min_length=80, max_length=12000)
    references: list[str] = Field(default_factory=list, max_length=12)
