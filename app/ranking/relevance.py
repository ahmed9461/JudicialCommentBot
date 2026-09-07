"""Deterministic course suitability assessment over verified judgment text.

Most law courses require a judgment whose substantive legal issue directly
matches the course. A small number of methodological courses instead teach how
to analyse, structure and document legal research. Treating those two kinds of
course as if they had identical lexical relevance would either reject every
methodology case or force fake keyword matches. The knowledge profile therefore
selects one explicit relevance mode and this module evaluates each mode without
LLM calls.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.knowledge import SubjectProfile

_GENERIC = {
    "القانون", "القانوني", "القانونية", "الحكم", "قضية", "القضية", "الدعوى",
    "المحكمة", "المحاكم", "المقرر", "المادة", "المواد", "الحق", "الحقوق",
    "الاختصاص", "النظام", "النظامية", "المبدأ", "مبدأ", "المبادئ", "العام",
    "العامة", "عامة", "تنظيم", "تنظيمية", "تطبيق", "تطبيقات", "مسألة", "المسألة",
    "أثر", "اثر", "بيان", "مدى", "حكم", "نزاع", "يتناول", "يرتبط", "يتعلق",
    "في", "من", "على", "عن", "إلى", "الى", "مع", "أو", "او", "بين", "عند",
}

_METHOD_FACTS = ("الوقائع", "وقائع", "المدعي", "المدعى عليه", "طلب المدعي", "أقام دعواه")
_METHOD_REASONING = ("الأسباب", "حيث", "ولما", "لما كان", "ثبت", "التسبيب", "مستند الحكم")
_METHOD_DISPOSITION = ("حكمت", "فحكمت", "قررت", "لذلك", "منطوق الحكم", "الحكم")
_METHOD_SOURCE = ("رقم القضية", "رقم الدعوى", "رقم الصك", "رقم القرار", "محكمة الاستئناف")


@dataclass(frozen=True, slots=True)
class SubjectRelevanceAssessment:
    score: int
    accepted: bool
    direct_keyword_hits: int
    priority_hits: int
    avoid_hits: int
    matched_terms: tuple[str, ...]


def assess_subject_relevance(subject: SubjectProfile, text: str) -> SubjectRelevanceAssessment:
    """Assess whether one *verified* judgment is suitable for the selected course."""
    if subject.relevance_mode == "methodological":
        return _assess_methodological(subject, text)
    return _assess_direct(subject, text)


def _assess_direct(subject: SubjectProfile, text: str) -> SubjectRelevanceAssessment:
    haystack = _normalize(text)
    keyword_hits = [term for term in subject.search_keywords if _concept_hit(term, haystack)]
    priority_hits = [term for term in subject.priority_topics if _concept_hit(term, haystack)]
    avoid_hits = [term for term in subject.avoid_case_patterns if _concept_hit(term, haystack)]

    direct = len(keyword_hits)
    priority = len(priority_hits)
    avoid = len(avoid_hits)
    score = min(40, 8 + direct * 11 + priority * 5)
    score = max(0, score - avoid * 8)
    accepted = (direct >= 1 or priority >= 2) and score >= 18
    matched = tuple(dict.fromkeys([*keyword_hits, *priority_hits]))[:8]
    return SubjectRelevanceAssessment(
        score=score,
        accepted=accepted,
        direct_keyword_hits=direct,
        priority_hits=priority,
        avoid_hits=avoid,
        matched_terms=matched,
    )


def _assess_methodological(subject: SubjectProfile, text: str) -> SubjectRelevanceAssessment:
    """Score analyzability/traceability instead of pretending a research-method
    course has a substantive judicial topic.

    A suitable judgment must expose enough of the case lifecycle to let a
    student separate facts, legal reasoning and disposition and must have enough
    text to support source-grounded analysis. Generic short orders do not pass.
    """
    haystack = _normalize(text)
    categories: list[str] = []
    if _any_phrase(_METHOD_FACTS, haystack):
        categories.append("وقائع واضحة")
    if _any_phrase(_METHOD_REASONING, haystack):
        categories.append("تسبيب قابل للتحليل")
    if _any_phrase(_METHOD_DISPOSITION, haystack):
        categories.append("منطوق أو نتيجة واضحة")
    if _any_phrase(_METHOD_SOURCE, haystack):
        categories.append("بيانات رسمية قابلة للتوثيق")

    avoid_hits = [term for term in subject.avoid_case_patterns if _concept_hit(term, haystack)]
    length_score = 0
    if len(text) >= 1200:
        length_score = 6
    if len(text) >= 2500:
        length_score = 10
    if len(text) >= 5000:
        length_score = 13

    score = min(40, 9 + len(categories) * 5 + length_score)
    score = max(0, score - len(avoid_hits) * 8)
    accepted = len(categories) >= 3 and len(text) >= 1200 and score >= 24
    return SubjectRelevanceAssessment(
        score=score,
        accepted=accepted,
        direct_keyword_hits=len(categories),
        priority_hits=0,
        avoid_hits=len(avoid_hits),
        matched_terms=tuple(categories),
    )


def _any_phrase(phrases: tuple[str, ...], normalized_haystack: str) -> bool:
    return any(_normalize(phrase) in normalized_haystack for phrase in phrases)


def _concept_hit(phrase: str, normalized_haystack: str) -> bool:
    normalized_phrase = _normalize(phrase)
    if not normalized_phrase:
        return False
    if normalized_phrase in normalized_haystack:
        meaningful = _meaningful_tokens(phrase)
        return bool(meaningful)

    tokens = _meaningful_tokens(phrase)
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        return len(token) >= 5 and token in normalized_haystack
    return sum(1 for token in tokens if token in normalized_haystack) >= 2


def _meaningful_tokens(value: str) -> tuple[str, ...]:
    normalized = _normalize(value)
    tokens = []
    for token in normalized.split():
        if len(token) < 3 or token in _GENERIC or token.isdigit():
            continue
        if token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().replace("ـ", "")
    for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"), ("ة", "ه")):
        text = text.replace(source, target)
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return re.sub(r"[^0-9a-z\u0600-\u06ff]+", " ", text).strip()
