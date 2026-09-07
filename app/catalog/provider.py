"""Research providers backed by the local official judicial catalog."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.knowledge import SubjectProfile
from app.ranking import assess_subject_relevance
from app.research.models import CaseCandidate
from app.research.provider import ResearchProgressCallback, ResearchProvider

from .errors import CatalogNotReadyError
from .indexer import CATALOG_PARSER_VERSION
from .store import CatalogStore
from .text import normalize_arabic

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "القانون", "القانوني", "القانونية", "القضية", "قضية", "حكم", "الحكم",
    "المقرر", "المادة", "المحكمة", "المحاكم", "مناسب", "مناسبة", "يظهر",
    "بيان", "تحليل", "صلة", "موضوع", "موضوعات", "مفهوم", "مفاهيم", "تطبيق",
    "تطبيقات", "أثر", "اثر", "مدى", "حالة", "حالات", "يناقش", "تصلح",
    "يمكن", "فيها", "عليه", "عنها", "هذه", "ذلك", "التي", "الذي", "على",
    "إلى", "الى", "عن", "من", "في", "مع", "أو", "او", "بين",
    "الحق", "الحقوق", "الاختصاص", "النظام", "العامة", "العام", "تنظيم",
}


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
    """Deterministic search over one immutable verified generation."""

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
        active = await self.store.active_generation_state()
        if active is None or not active.is_ready or active.parser_version != CATALOG_PARSER_VERSION:
            latest = await self.store.latest_generation_state(CATALOG_PARSER_VERSION)
            detail = "no active generation for current parser"
            if latest is not None:
                detail = f"latest generation={latest.generation_id} status={latest.status}"
            raise CatalogNotReadyError(detail)

        if progress is not None:
            stats = await self.store.stats(generation_id=active.generation_id)
            await progress(
                f"🗂️ جاري البحث في النسخة القضائية النشطة والمتكاملة…\n"
                f"النسخة: {(active.generation_id or '')[:8]} | {stats.cases} قضية من {stats.collections} مجموعة رسمية."
            )

        return await self.search_generation_cases(
            subject,
            generation_id=active.generation_id or "",
            excluded_cases=excluded_cases,
            limit=limit,
            progress=progress,
        )

    async def search_generation_cases(
        self,
        subject: SubjectProfile,
        *,
        generation_id: str,
        excluded_cases: list[dict[str, str | None]],
        limit: int,
        progress: ResearchProgressCallback | None = None,
    ) -> list[CaseCandidate]:
        if not generation_id:
            return []
        terms = _subject_terms(subject)
        rows = await self.store.search(
            terms,
            preferred_source_ids=self.source_map.preferred_for(subject.slug),
            limit=max(limit * 8, 40),
            generation_id=generation_id,
        )
        excluded = {
            (_norm_identity(item.get("case_number")), _norm_identity(item.get("court_name")))
            for item in excluded_cases
            if item.get("case_number") and item.get("court_name")
        }
        result: list[CaseCandidate] = []
        for row in rows:
            identity = (_norm_identity(row.get("case_number")), _norm_identity(row.get("court_name")))
            if identity in excluded:
                continue

            judgment_text = str(row.get("extracted_text") or "")
            relevance = assess_subject_relevance(subject, judgment_text)
            if not relevance.accepted:
                continue

            match_score = int(row.get("catalog_match_score") or 0)
            clarity = 18 if row.get("case_number") else 14
            reasoning = 13 if len(judgment_text) >= 1800 else 10
            commentary = min(15, 9 + len(relevance.matched_terms) * 2 + match_score // 30)
            estimated = min(96, relevance.score + clarity + reasoning + commentary + 10)
            topic_text = "، ".join(relevance.matched_terms[:3])
            pdf_sha = str(row.get("pdf_sha256") or "")
            if len(pdf_sha) != 64:
                continue

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
                    catalog_key=str(row["catalog_key"]),
                    catalog_pdf_sha256=pdf_sha,
                    catalog_range_verified=True,
                    legal_issue=(
                        f"حكم منشور ذو صلة مباشرة بالمقرر عبر: {topic_text}"
                        if topic_text else "حكم منشور اجتاز بوابة الصلة المباشرة بالمقرر"
                    ),
                    suitability_reason=(
                        "مرشح من النسخة القضائية الرسمية النشطة؛ "
                        f"صلة مباشرة {relevance.score}/40، ومطابقة استرجاع {match_score}."
                    ),
                    estimated_score=estimated,
                    subject_relevance=relevance.score,
                    legal_issue_clarity=clarity,
                    reasoning_quality=reasoning,
                    academic_commentary_value=commentary,
                )
            )
            if len(result) >= limit:
                break

        if progress is not None:
            if result:
                await progress(
                    f"✅ وجد الفهرس {len(result)} قضية اجتازت التحقق من النطاق والصلة المباشرة بالمقرر."
                )
            else:
                await progress(
                    "⚠️ النسخة النشطة لا تحتوي قضية تجتاز بوابة الصلة المباشرة لهذا المقرر."
                )
        return result


class CatalogFirstResearchProvider:
    """Use the active official generation first; call web research only as fallback."""

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
                "🌐 النسخة القضائية النشطة مكتملة لكن عدد القضايا المباشرة لهذا المقرر غير كافٍ؛ "
                "سيُستخدم البحث عبر الويب كخيار احتياطي محدود."
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
                logger.exception("Web fallback failed; continuing with active catalog candidates")
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
    phrases = [
        *subject.search_keywords,
        *subject.priority_topics,
        *subject.secondary_topics,
    ]
    result: list[str] = []
    seen_normalized: set[str] = set()

    def add(value: str) -> None:
        cleaned = value.strip()
        normalized = normalize_arabic(cleaned)
        if len(normalized) >= 2 and normalized not in seen_normalized:
            seen_normalized.add(normalized)
            result.append(cleaned)

    for phrase in phrases:
        add(phrase)
    for phrase in [*subject.search_keywords, *subject.priority_topics]:
        for token in normalize_arabic(phrase).split():
            if len(token) < 4 or token in _STOPWORDS or token.isdigit():
                continue
            add(token)
    return result[:40]


def _norm_identity(value: object) -> str:
    return normalize_arabic(str(value or "")).replace(" ", "")
