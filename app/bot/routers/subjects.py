"""Subject selection and research flow."""

import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import subjects_keyboard
from app.core.constants import CALLBACK_SEARCH_PREFIX, CALLBACK_SUBJECTS_PREFIX, SUBJECTS_PAGE_SIZE
from app.core.settings import Settings
from app.db import Database
from app.knowledge import SubjectLoader
from app.research import DeepSeekResearchProvider
from app.sources import SourceRegistry

logger = logging.getLogger(__name__)
router = Router(name="subjects")


@router.callback_query(F.data.startswith(CALLBACK_SUBJECTS_PREFIX))
async def list_subjects(callback: CallbackQuery, subject_loader: SubjectLoader) -> None:
    try:
        page = int((callback.data or "").removeprefix(CALLBACK_SUBJECTS_PREFIX))
    except ValueError:
        page = 0
    subjects = subject_loader.list_subjects()
    max_page = max((len(subjects) - 1) // SUBJECTS_PAGE_SIZE, 0)
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
            [InlineKeyboardButton(text="🔎 البحث عن قضية", callback_data=f"{CALLBACK_SEARCH_PREFIX}{slug}")],
            [InlineKeyboardButton(text="⬅️ رجوع للمواد", callback_data=f"{CALLBACK_SUBJECTS_PREFIX}0")],
        ]
    )
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CALLBACK_SEARCH_PREFIX))
async def search_cases(
    callback: CallbackQuery,
    subject_loader: SubjectLoader,
    research_provider: DeepSeekResearchProvider | None,
    database: Database,
    source_registry: SourceRegistry,
    settings: Settings,
) -> None:
    slug = (callback.data or "").removeprefix(CALLBACK_SEARCH_PREFIX)
    try:
        subject = subject_loader.get_subject(slug)
    except (KeyError, ValueError):
        await callback.answer("تعذر تحميل المادة.", show_alert=True)
        return

    if research_provider is None:
        await callback.answer("لم يتم ضبط DEEPSEEK_API_KEY بعد.", show_alert=True)
        return

    await callback.answer()
    status_message = None
    if callback.message:
        status_message = await callback.message.answer(
            f"🔎 جاري البحث عن قضايا مناسبة لمادة: {subject.name_ar}\nقد يستغرق البحث قليلاً."
        )

    excluded = await database.used_cases_for_subject(slug)
    try:
        candidates = await research_provider.search_cases(
            subject,
            excluded_cases=excluded,
            limit=settings.search_candidate_limit,
        )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.exception("Research failed for subject=%s", slug)
        if status_message:
            await status_message.edit_text(
                "❌ فشل البحث حالياً. تم تسجيل الخطأ ولن يتم اعتماد أي قضية."
            )
        return

    valid = [
        candidate
        for candidate in candidates
        if source_registry.is_https_allowed(candidate.source_url_str)
    ]
    if not valid:
        if status_message:
            await status_message.edit_text("لم يتم العثور على مرشحين صالحين حالياً.")
        return

    shown = valid[: settings.candidate_display_count]
    parts = [f"✅ نتائج أولية لمادة: {subject.name_ar}"]
    for index, candidate in enumerate(shown, start=1):
        classification = source_registry.classify(candidate.source_url_str)
        source_label = "رسمي" if classification.is_official else "اكتشاف/يحتاج تحقق"
        parts.append(
            f"\n{index}) {candidate.title}\n"
            f"المحكمة: {candidate.court_name or 'غير متوفرة'}\n"
            f"رقم القضية: {candidate.case_number or 'غير متوفر'}\n"
            f"التقييم الأولي: {candidate.estimated_score}/100\n"
            f"المصدر: {candidate.source_name} ({source_label})\n"
            f"سبب المناسبة: {candidate.suitability_reason}\n"
            f"الرابط: {candidate.source_url_str}"
        )
    parts.append("\nهذه مرشحات بحث فقط؛ لم يتم بعد التحقق من ملف PDF الأصلي أو اعتماد القضية.")
    text = "\n".join(parts)
    if status_message:
        await status_message.edit_text(text, disable_web_page_preview=True)
