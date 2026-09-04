"""Stable application constants."""

SUBJECTS_PAGE_SIZE = 8
MAX_ALLOWED_USERS_DISPLAY = 100

CALLBACK_HOME = "menu:home"
CALLBACK_SUBJECTS_PREFIX = "subjects:page:"
CALLBACK_SUBJECT_PREFIX = "subject:"
CALLBACK_SEARCH_PREFIX = "case_search:"
CALLBACK_PICK_PREFIX = "case_pick:"
CALLBACK_REGENERATE_PREFIX = "case_regen:"
CALLBACK_NEW_CASE_PREFIX = "case_new:"

UNAUTHORIZED_MESSAGE = "⛔ هذا البوت خاص ولا تملك صلاحية استخدامه."

FORBIDDEN_OUTPUT_MARKERS = (
    "##", "**", "```", "ChatGPT", "DeepSeek", "ذكاء اصطناعي",
    "Artificial Intelligence", "Telegram", "البوت", "كمساعد", "تم إنشاء",
    "بناء على طلب المستخدم",
)
