"""Project defaults that are not secrets.

Deploy-specific values belong in environment variables/settings, not here.
"""

AUTO_ACCEPT_SCORE_DEFAULT = 90
CANDIDATE_DISPLAY_COUNT_DEFAULT = 3
SEARCH_CANDIDATE_LIMIT_DEFAULT = 8

SOURCE_PRIORITY = (
    "ministry_of_justice",
    "board_of_grievances",
    "official_quasi_judicial",
    "tashree_discovery",
    "other_trusted",
)

ALLOWED_PDF_ORIGIN_TYPES = {
    "direct_official_pdf",
    "official_compilation_extract",
}

FORBIDDEN_COMMENTARY_TOKENS = (
    "##",
    "**",
    "ChatGPT",
    "DeepSeek",
    "ذكاء اصطناعي",
    "كذكاء اصطناعي",
    "تم إنشاء هذا التعليق",
    "بناءً على طلب المستخدم",
    "كمساعد",
)

COMMENTARY_SECTIONS = (
    "facts_and_course_link",
    "legal_issue",
    "court_reasoning",
    "comment_and_opinion",
)
