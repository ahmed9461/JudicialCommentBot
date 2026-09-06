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
    """Deterministic search over parser-verified official judgments.

    Catalog SQL/text retrieval is intentionally broad enough to discover likely
    rows.  Before a row becomes a candidate, the shared strict relevance gate is
    run over the actual indexed judgment text.  Generic legal overlap therefore
    cannot promote an unrelated private dispute into a specialist course.
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
        stats = await self.store.stats(parser_version=CATALOG_PARSER_VERSION)
        if progress is not None:
            await progress(
                f"🗂️ جاري البحث محليًا في الفهرس القضائي المتحقق…\n"
                f"الفهرس الجاهز: {stats.cases} قضية من {stats.collections} مجموعة رسمية."
            )
        if stats.cases == 0:
            raise CatalogNotReadyError(
                "Current verified catalog generation is empty; complete catalog refresh first"
            )

        terms = _subject_terms(subject)
        rows = await self.store.search(
            terms,
            preferred_source_ids=self.source_map.preferred_for(subject.slug),
            limit=max(limit * 8, 40),
            parser_version=CATALOG_PARSER_VERSION,
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
                        "مرشح من الفهرس المحلي المتحقق من مجموعة قضائية رسمية؛ "
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
                    f"✅ وجد الفهرس المحلي {len(result)} قضية اجتازت التحقق من النطاق والصلة المباشرة بالمقرر."
                )
            else:
                await progress(
                    "⚠️ توجد نتائج نصية في الفهرس، لكن لم تجتز أي قضية بوابة الصلة المباشرة بالمقرر."
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
        stats = await self.catalog.store.stats(parser_version=CATALOG_PARSER_VERSION)
        if stats.cases == 0:
            raise CatalogNotReadyError(
                "Verified official judicial catalog has not finished rebuilding on this deployment"
            )

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
                "🌐 الفهرس الرسمي المتحقق موجود لكن القضايا ذات الصلة المباشرة غير كافية؛ "
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
    """Build discovery terms without tokenizing generic suitable-case prose."""
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
