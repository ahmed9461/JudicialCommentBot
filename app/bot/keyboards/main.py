"""Inline keyboards for the primary Telegram flow."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.constants import CALLBACK_HOME, CALLBACK_SUBJECTS_PREFIX, SUBJECTS_PAGE_SIZE
from app.knowledge import SubjectSummary


def main_menu_keyboard(is_owner: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📚 اختيار المادة", callback_data=f"{CALLBACK_SUBJECTS_PREFIX}0")
    if is_owner:
        builder.button(text="👥 إدارة المستخدمين", callback_data="admin:help")
    builder.adjust(1)
    return builder.as_markup()


def subjects_keyboard(
    subjects: tuple[SubjectSummary, ...], page: int
) -> InlineKeyboardMarkup:
    page = max(page, 0)
    start = page * SUBJECTS_PAGE_SIZE
    end = start + SUBJECTS_PAGE_SIZE
    visible = subjects[start:end]

    builder = InlineKeyboardBuilder()
    for item in visible:
        builder.button(text=item.name_ar, callback_data=f"subject:{item.slug}")
    builder.adjust(2)

    nav = InlineKeyboardBuilder()
    if page > 0:
        nav.button(text="⬅️ السابق", callback_data=f"{CALLBACK_SUBJECTS_PREFIX}{page - 1}")
    if end < len(subjects):
        nav.button(text="التالي ➡️", callback_data=f"{CALLBACK_SUBJECTS_PREFIX}{page + 1}")
    nav.button(text="🏠 الرئيسية", callback_data=CALLBACK_HOME)
    nav.adjust(2, 1)
    builder.attach(nav)
    return builder.as_markup()
