"""Deterministic subject relevance assessment over verified judgment text.

The catalog search may use broad lexical expansion to find candidates, but a
candidate is not allowed to survive merely because generic legal words matched.
This module performs a second, stricter assessment on the actual verified
judgment text.  It is shared by catalog retrieval and runtime verification for
all subjects.
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


@dataclass(frozen=True, slots=True)
class SubjectRelevanceAssessment:
    score: int
    accepted: bool
    direct_keyword_hits: int
    priority_hits: int
    avoid_hits: int
    matched_terms: tuple[str, ...]


def assess_subject_relevance(subject: SubjectProfile, text: str) -> SubjectRelevanceAssessment:
    """Score direct relation to a course using its editable knowledge file.

    Acceptance requires at least one distinctive search-keyword concept (or two
    priority-topic concepts for broad courses) in the *verified judgment text*.
    This prevents a generic private dispute from receiving a high score for a
    course such as constitutional law merely because words like "court",
    "jurisdiction" or "right" appear somewhere in it.
    """
    haystack = _normalize(text)
    keyword_hits = [term for term in subject.search_keywords if _concept_hit(term, haystack)]
    priority_hits = [term for term in subject.priority_topics if _concept_hit(term, haystack)]
    avoid_hits = [term for term in subject.avoid_case_patterns if _concept_hit(term, haystack)]

    direct = len(keyword_hits)
    priority = len(priority_hits)
    avoid = len(avoid_hits)

    # Relevance is the 40-point component used by final scoring.  A direct
    # subject keyword is intentionally worth much more than generic lexical
    # overlap; avoid-pattern hits reduce but do not by themselves reject.
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


def _concept_hit(phrase: str, normalized_haystack: str) -> bool:
    normalized_phrase = _normalize(phrase)
    if not normalized_phrase:
        return False

    # Exact phrase first; useful for strong concepts such as "مبدأ المشروعية",
    # "شركة التأمين", "القصد الجنائي" or "الملكية الفكرية".
    if normalized_phrase in normalized_haystack:
        meaningful = _meaningful_tokens(phrase)
        return bool(meaningful)

    tokens = _meaningful_tokens(phrase)
    if not tokens:
        return False
    if len(tokens) == 1:
        token = tokens[0]
        return len(token) >= 5 and token in normalized_haystack

    # Arabic judgments often vary connectors/definite articles. Requiring two
    # distinctive tokens from the same configured concept tolerates wording
    # variation without reducing relevance to bag-of-generic-words matching.
    needed = 2 if len(tokens) >= 2 else 1
    return sum(1 for token in tokens if token in normalized_haystack) >= needed


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
