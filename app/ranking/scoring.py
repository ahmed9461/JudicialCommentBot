"""Deterministic final scoring after the original PDF has been verified."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from app.research import CaseCandidate


@dataclass(frozen=True, slots=True)
class ScoreResult:
    subject_relevance: int
    legal_issue_clarity: int
    reasoning_quality: int
    academic_commentary_value: int
    source_pdf_quality: int

    @property
    def total(self) -> int:
        return min(
            100,
            self.subject_relevance
            + self.legal_issue_clarity
            + self.reasoning_quality
            + self.academic_commentary_value
            + self.source_pdf_quality,
        )


class ScoringPolicy:
    def __init__(self, config_path: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.config_path = config_path or root / "config" / "scoring.yaml"
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        weights = data.get("weights") or {}
        selection = data.get("selection") or {}
        self.weights = {
            "subject_relevance": int(weights.get("subject_relevance", 40)),
            "legal_issue_clarity": int(weights.get("legal_issue_clarity", 20)),
            "reasoning_quality": int(weights.get("reasoning_quality", 15)),
            "academic_commentary_value": int(weights.get("academic_commentary_value", 15)),
            "source_pdf_quality": int(weights.get("source_pdf_quality", 10)),
        }
        self.min_auto_accept_margin = int(selection.get("min_auto_accept_margin", 5))
        self.require_score_margin = bool(
            selection.get("require_score_margin_for_auto_accept", True)
        )

    def score(self, candidate: CaseCandidate, *, pdf_is_official: bool) -> ScoreResult:
        estimated = candidate.estimated_score

        def component(value: int | None, key: str, fallback_ratio: float) -> int:
            maximum = self.weights[key]
            if value is None:
                value = round(maximum * max(0, min(100, estimated)) / 100 * fallback_ratio)
            return max(0, min(maximum, int(value)))

        return ScoreResult(
            subject_relevance=component(candidate.subject_relevance, "subject_relevance", 1.0),
            legal_issue_clarity=component(candidate.legal_issue_clarity, "legal_issue_clarity", 1.0),
            reasoning_quality=component(candidate.reasoning_quality, "reasoning_quality", 1.0),
            academic_commentary_value=component(
                candidate.academic_commentary_value, "academic_commentary_value", 1.0
            ),
            source_pdf_quality=self.weights["source_pdf_quality"] if pdf_is_official else 0,
        )
