"""Research providers backed by the local official judicial catalog."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.knowledge import SubjectProfile
from app.research.models import CaseCandidate
from app.research.provider import ResearchProgressCallback, ResearchProvider

from .store import CatalogStore
from .text import normalize_arabic

logger = logging.getLogger(__name__)


class SubjectSourceMap:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(__file__).resolve().parents[2]
        self.path = path or root / "config" / "subject_source_map.yaml"
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self._mapping = {
            str(slug): tuple(map(str, source_ids or []))
            for slug, source_ids in (data.get("subjects") or {}).items()
        }

    def preferred_for(self, subject_slug: str) -> tuple[str, ...]:
        return self._mapping.get(subject_slug, ())


class CatalogResearchProvider:
    """Deterministic search over already-indexed official judgments.

    The same implementation serves every course. Course-specific behavior comes
    from the existing YAML knowledge files and the separate source-preference
    map, so there is no course-specific branching in application code.
    """

    def __init__(self, store: CatalogStore, source_map: SubjectSourceMap | None = None) -> None:
        self.store = store
        self.source_map = source_map or SubjectSourceMap()

    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
        progress: ResearchProgressCallback | None = None,
    ) -> list[CaseCandidate]:
        stats = await self.store.stats()
        if progress is not None:
            await progress(
                f"🗂️ جاري البحث محليًا في فهرس الأحكام الرسمية…\n"
                f"الفهرس الحالي: {stats.cases} قضية من {stats.collections} مجموعة."
            )
        if stats.cases == 0:
            return []

        terms = _subject_terms(subject)
        rows = await self.store.search(
            terms,
            preferred_source_ids=self.source_map.preferred_for(subject.slug),
            limit=max(limit * 3, 12),
        )
        excluded = {
            (_norm_identity(item.get("case_number")), _norm_identity(item.get("court_name")))
            for item in excluded_cases
            if item.get("case_number") and item.get("court_name")
        }
        avoid_terms = [normalize_arabic(value) for value in subject.avoid_case_patterns if value]
        result: list[CaseCandidate] = []
        for row in rows:
            identity = (_norm_identity(row.get("case_number")), _norm_identity(row.get("court_name")))
            if identity in excluded:
                continue
            haystack = str(row["normalized_text"])
            if avoid_terms and all(term in haystack for term in avoid_terms if term):
                continue

            match_score = int(row.get("catalog_match_score") or 0)
            relevance = min(40, 18 + match_score // 3)
            clarity = 18 if row.get("case_number") else 14
            reasoning = 13 if len(str(row.get("extracted_text") or "")) >= 1800 else 10
            commentary = min(15, 9 + match_score // 15)
            estimated = min(96, relevance + clarity + reasoning + commentary + 10)
            matched_topics = [
                term for term in subject.priority_topics
                if normalize_arabic(term) and normalize_arabic(term) in haystack
            ][:3]
            topic_text = "، ".join(matched_topics or subject.priority_topics[:2])
            result.append(
                CaseCandidate(
                    title=str(row["title"]),
                    case_number=str(row["case_number"]) if row.get("case_number") else None,
                    court_name=str(row["court_name"]) if row.get("court_name") else None,
                    judgment_year=str(row["judgment_year"]) if row.get("judgment_year") else None,
                    source_name=str(row["source_name"]),
                    source_url=str(row["source_url"]),
                    pdf_url=str(row["pdf_url"]),
                    pdf_page_start=int(row["page_start"]),
                    pdf_page_end=int(row["page_end"]),
                    legal_issue=f"حكم منشور يتصل بمحاور المقرر: {topic_text}",
                    suitability_reason=(
                        "مرشح من الفهرس المحلي المبني مباشرة من مجموعة قضائية رسمية؛ "
                        f"درجة المطابقة النصية {match_score}."
                    ),
                    estimated_score=estimated,
                    subject_relevance=relevance,
                    legal_issue_clarity=clarity,
                    reasoning_quality=reasoning,
                    academic_commentary_value=commentary,
                )
            )
            if len(result) >= limit:
                break

        if progress is not None and result:
            await progress(
                f"✅ وجد الفهرس المحلي {len(result)} قضية مرشحة من مصادر رسمية دون بحث ويب مدفوع."
            )
        return result


class CatalogFirstResearchProvider:
    """Use the official local catalog first; call web research only as fallback."""

    def __init__(
        self,
        *,
        catalog: CatalogResearchProvider,
        fallback: ResearchProvider | None,
        min_catalog_candidates: int = 3,
        fallback_enabled: bool = True,
    ) -> None:
        self.catalog = catalog
        self.fallback = fallback
        self.min_catalog_candidates = max(1, int(min_catalog_candidates))
        self.fallback_enabled = bool(fallback_enabled)

    async def search_cases(
        self,
        subject: SubjectProfile,
        *,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
        progress: ResearchProgressCallback | None = None,
    ) -> list[CaseCandidate]:
        local = await self.catalog.search_cases(
            subject,
            excluded_cases=excluded_cases,
            limit=limit,
            progress=progress,
        )
        if len(local) >= min(limit, self.min_catalog_candidates):
            return local[:limit]
        if not self.fallback_enabled or self.fallback is None:
            return local[:limit]

        if progress is not None:
            await progress(
                "🌐 الفهرس المحلي لا يحتوي عددًا كافيًا من المرشحين؛ "
                "سيُستخدم البحث عبر الويب كخيار احتياطي فقط."
            )
        try:
            remote = await self.fallback.search_cases(
                subject,
                excluded_cases=excluded_cases,
                limit=max(1, limit - len(local)),
                progress=progress,
            )
        except Exception:
            if local:
                logger.exception("Web fallback failed; continuing with local catalog candidates")
                return local[:limit]
            raise

        merged: list[CaseCandidate] = []
        seen: set[tuple[str, str, str]] = set()
        for item in [*local, *remote]:
            key = (
                _norm_identity(item.case_number),
                _norm_identity(item.court_name),
                item.pdf_url_str or item.source_url_str,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= limit:
                break
        return merged


def _subject_terms(subject: SubjectProfile) -> list[str]:
    values = [
        *subject.priority_topics,
        *subject.search_keywords,
        *subject.secondary_topics,
        *subject.suitable_case_patterns,
    ]
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result[:32]


def _norm_identity(value: object) -> str:
    return normalize_arabic(str(value or "")).replace(" ", "")
