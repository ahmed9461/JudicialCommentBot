"""Subject selection flow backed by the YAML knowledge base."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import subjects_keyboard
from app.core.constants import CALLBACK_SEARCH_PREFIX, CALLBACK_SUBJECTS_PREFIX
from app.knowledge import SubjectLoader

router = Router(name="subjects")


@router.callback_query(F.data.startswith(CALLBACK_SUBJECTS_PREFIX))
async def list_subjects(callback: CallbackQuery, subject_loader: SubjectLoader) -> None:
    try:
        page = int((callback.data or "").removeprefix(CALLBACK_SUBJECTS_PREFIX))
    except ValueError:
        page = 0
    subjects = subject_loader.list_subjects()
    max_page = max((len(subjects) - 1) // 8, 0)
    page = min(max(page, 0), max_page)
    if callback.message:
        await callback.message.edit_text(
            "📚 اختر المادة:",
            reply_markup=subjects_keyboard(subjects, page),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("subject:"))
async def subject_details(callback: CallbackQuery, subject_loader: SubjectLoader) -> None:
    slug = (callback.data or "").removeprefix("subject:")
    try:
        subject = subject_loader.get_subject(slug)
    except (KeyError, ValueError):
        await callback.answer("تعذر تحميل بيانات المادة.", show_alert=True)
        return

    topics = "\n".join(f"• {topic}" for topic in subject.priority_topics[:6])
    text = (
        f"📘 {subject.name_ar}\n\n"
        "المحاور ذات الأولوية لاختيار القضية:\n"
        f"{topics}\n\n"
        "سيُستخدم ملف المعرفة الخاص بالمادة في البحث والتقييم."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 البحث عن قضية", callback_data=f"{CALLBACK_SEARCH_PREFIX}{slug}"
                )
            ],
            [InlineKeyboardButton(text="⬅️ رجوع للمواد", callback_data=f"{CALLBACK_SUBJECTS_PREFIX}0")],
        ]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CALLBACK_SEARCH_PREFIX))
async def search_placeholder(callback: CallbackQuery, subject_loader: SubjectLoader) -> None:
    slug = (callback.data or "").removeprefix(CALLBACK_SEARCH_PREFIX)
    try:
        subject = subject_loader.get_subject(slug)
    except (KeyError, ValueError):
        await callback.answer("تعذر تحميل المادة.", show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            f"✅ تم اختيار: {subject.name_ar}\n"
            "محرك البحث عن القضايا هو المرحلة التالية في التنفيذ."
        )
