"""Stable application constants.

Deploy-specific configuration belongs in environment variables, not here.
"""

SUBJECTS_PAGE_SIZE = 8
MAX_ALLOWED_USERS_DISPLAY = 100

CALLBACK_HOME = "menu:home"
CALLBACK_SUBJECTS_PREFIX = "subjects:page:"
CALLBACK_SUBJECT_PREFIX = "subject:"
CALLBACK_SEARCH_PREFIX = "case_search:"

UNAUTHORIZED_MESSAGE = "⛔ هذا البوت خاص ولا تملك صلاحية استخدامه."

FORBIDDEN_OUTPUT_MARKERS = (
    "##",
    "**",
    "```",
    "ChatGPT",
    "DeepSeek",
    "ذكاء اصطناعي",
    "Artificial Intelligence",
)
