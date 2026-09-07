"""Deterministic quality gates for activating a catalog generation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.knowledge import SubjectLoader

from .provider import CatalogResearchProvider
from .store import CatalogStore


@dataclass(frozen=True, slots=True)
class CatalogQualityReport:
    passed: bool
    cases: int
    collections: int
    sources: int
    documents_seen: int
    documents_failed: int
    failure_ratio: float
    covered_subjects: int
    total_subjects: int
    required_subjects: int
    missing_subjects: tuple[str, ...]
    thin_subjects: tuple[str, ...]
    reason: str | None = None


async def evaluate_generation(
    *,
    store: CatalogStore,
    provider: CatalogResearchProvider,
    subject_loader: SubjectLoader,
    generation_id: str,
    documents_seen: int,
    documents_failed: int,
    min_cases: int,
    min_candidates_per_subject: int,
    required_subject_coverage_percent: int,
    max_document_failure_ratio: float,
) -> CatalogQualityReport:
    """Validate one staging snapshot before atomic promotion.

    The gate is intentionally deterministic and free of LLM calls.  It proves
    that the snapshot is structurally substantial and that every required course
    has direct, locally-verifiable candidate coverage before runtime can see it.
    """
    stats = await store.stats(generation_id=generation_id)
    total_docs = max(0, int(documents_seen))
    failed_docs = max(0, int(documents_failed))
    failure_ratio = (failed_docs / total_docs) if total_docs else 1.0

    subjects = subject_loader.list_subjects()
    minimum = max(1, int(min_candidates_per_subject))
    missing: list[str] = []
    thin: list[str] = []
    covered = 0

    for item in subjects:
        subject = subject_loader.get_subject(item.slug)
        candidates = await provider.search_generation_cases(
            subject,
            generation_id=generation_id,
            excluded_cases=[],
            limit=minimum,
        )
        count = len(candidates)
        if count >= minimum:
            covered += 1
        elif count == 0:
            missing.append(item.slug)
        else:
            thin.append(item.slug)

    total_subjects = len(subjects)
    required_subjects = math.ceil(total_subjects * max(1, min(100, required_subject_coverage_percent)) / 100)

    reasons: list[str] = []
    if stats.cases < max(1, int(min_cases)):
        reasons.append(f"cases {stats.cases} < required {min_cases}")
    if total_docs <= 0:
        reasons.append("no official documents were discovered")
    if failure_ratio > float(max_document_failure_ratio):
        reasons.append(
            f"document failure ratio {failure_ratio:.2%} exceeds {max_document_failure_ratio:.2%}"
        )
    if covered < required_subjects:
        reasons.append(
            f"course coverage {covered}/{total_subjects} < required {required_subjects}/{total_subjects}"
        )

    return CatalogQualityReport(
        passed=not reasons,
        cases=stats.cases,
        collections=stats.collections,
        sources=stats.sources,
        documents_seen=total_docs,
        documents_failed=failed_docs,
        failure_ratio=failure_ratio,
        covered_subjects=covered,
        total_subjects=total_subjects,
        required_subjects=required_subjects,
        missing_subjects=tuple(missing),
        thin_subjects=tuple(thin),
        reason="; ".join(reasons) if reasons else None,
    )
