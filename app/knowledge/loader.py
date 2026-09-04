"""Load the editable YAML knowledge files for all legal subjects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    slug: str
    name_ar: str


@dataclass(frozen=True, slots=True)
class SubjectProfile:
    slug: str
    name_ar: str
    verification_status: str = "unknown"
    source_notes: str = ""
    priority_topics: tuple[str, ...] = field(default_factory=tuple)
    secondary_topics: tuple[str, ...] = field(default_factory=tuple)
    suitable_case_patterns: tuple[str, ...] = field(default_factory=tuple)
    avoid_case_patterns: tuple[str, ...] = field(default_factory=tuple)
    search_keywords: tuple[str, ...] = field(default_factory=tuple)
    commentary_focus: tuple[str, ...] = field(default_factory=tuple)


class SubjectLoader:
    def __init__(self, subjects_dir: Path | None = None) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self.subjects_dir = subjects_dir or repo_root / "knowledge" / "subjects"
        self._summaries: tuple[SubjectSummary, ...] | None = None
        self._profiles: dict[str, SubjectProfile] = {}

    def list_subjects(self) -> tuple[SubjectSummary, ...]:
        if self._summaries is None:
            index_path = self.subjects_dir / "index.yaml"
            data = self._load_yaml(index_path)
            items = data.get("subjects") or []
            self._summaries = tuple(
                SubjectSummary(slug=str(item["slug"]), name_ar=str(item["name_ar"]))
                for item in items
            )
        return self._summaries

    def get_subject(self, slug: str) -> SubjectProfile:
        if slug in self._profiles:
            return self._profiles[slug]

        known = {item.slug for item in self.list_subjects()}
        if slug not in known:
            raise KeyError(f"Unknown subject slug: {slug}")

        data = self._load_yaml(self.subjects_dir / f"{slug}.yaml")
        profile = SubjectProfile(
            slug=str(data["slug"]),
            name_ar=str(data["name_ar"]),
            verification_status=str(data.get("verification_status", "unknown")),
            source_notes=str(data.get("source_notes", "")),
            priority_topics=tuple(map(str, data.get("priority_topics") or [])),
            secondary_topics=tuple(map(str, data.get("secondary_topics") or [])),
            suitable_case_patterns=tuple(
                map(str, data.get("suitable_case_patterns") or [])
            ),
            avoid_case_patterns=tuple(map(str, data.get("avoid_case_patterns") or [])),
            search_keywords=tuple(map(str, data.get("search_keywords") or [])),
            commentary_focus=tuple(map(str, data.get("commentary_focus") or [])),
        )
        if profile.slug != slug:
            raise ValueError(f"Subject slug mismatch in {slug}.yaml")
        self._profiles[slug] = profile
        return profile

    def validate_all(self) -> None:
        summaries = self.list_subjects()
        if not summaries:
            raise ValueError("No subjects found in knowledge/subjects/index.yaml")
        seen: set[str] = set()
        for summary in summaries:
            if summary.slug in seen:
                raise ValueError(f"Duplicate subject slug: {summary.slug}")
            seen.add(summary.slug)
            self.get_subject(summary.slug)

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        if not path.is_file():
            raise FileNotFoundError(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected YAML mapping in {path}")
        return data
