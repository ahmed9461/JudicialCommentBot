"""Subject selection and full assignment workflow."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import subjects_keyboard
from app.core.constants import (
    CALLBACK_NEW_CASE_PREFIX, CALLBACK_PICK_PREFIX, CALLBACK_REGENERATE_PREFIX,
    CALLBACK_SEARCH_PREFIX, CALLBACK_SUBJECTS_PREFIX, SUBJECTS_PAGE_SIZE,
)
from app.knowledge import SubjectLoader
from app.services import AssignmentService, CaseWorkflowService, NoSuitableCasesError

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
        await callback.message.edit_text("📚 اختر المادة:", reply_markup=subjects_keyboard(subjects, page))
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
    text = f"📘 {subject.name_ar}\n\nالمحاور ذات الأولوية لاختيار القضية:\n{topics}\n\nسيبحث النظام عن حكم أصلي مناسب ويتحقق منه قبل الاعتماد."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 البحث عن قضية", callback_data=f"{CALLBACK_SEARCH_PREFIX}{slug}")],
        [InlineKeyboardButton(text="⬅️ رجوع للمواد", callback_data=f"{CALLBACK_SUBJECTS_PREFIX}0")],
    ])
    if callback.message:
        await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith(CALLBACK_SEARCH_PREFIX))
async def search_cases(callback: CallbackQuery, workflow_service: CaseWorkflowService | None,
                       assignment_service: AssignmentService | None,
                       subject_loader: SubjectLoader) -> None:
    slug = (callback.data or "").removeprefix(CALLBACK_SEARCH_PREFIX)
    await _start_search(callback, slug, workflow_service, assignment_service, subject_loader)


@router.callback_query(F.data.startswith(CALLBACK_NEW_CASE_PREFIX))
async def new_case(callback: CallbackQuery, workflow_service: CaseWorkflowService | None,
                   assignment_service: AssignmentService | None,
                   subject_loader: SubjectLoader) -> None:
    slug = (callback.data or "").removeprefix(CALLBACK_NEW_CASE_PREFIX)
    await _start_search(callback, slug, workflow_service, assignment_service, subject_loader)


async def _start_search(callback: CallbackQuery, slug: str,
                        workflow_service: CaseWorkflowService | None,
                        assignment_service: AssignmentService | None,
                        subject_loader: SubjectLoader) -> None:
    if workflow_service is None or assignment_service is None:
        await callback.answer("لم يتم ضبط خدمة DeepSeek بعد.", show_alert=True)
        return
    try:
        subject = subject_loader.get_subject(slug)
    except (KeyError, ValueError):
        await callback.answer("تعذر تحميل المادة.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    status = await callback.message.answer(
        f"🔎 جاري البحث والتحقق من ملفات الأحكام لمادة: {subject.name_ar}"
    )
    try:
        batch = await workflow_service.prepare(callback.from_user.id, slug)
    except NoSuitableCasesError:
        await status.edit_text("لم أعثر حالياً على قضية مناسبة بملف PDF أصلي قابل للتحقق. جرب البحث لاحقاً.")
        return
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.exception("Case preparation failed subject=%s", slug)
        await status.edit_text("❌ تعذر إكمال البحث والتحقق حالياً. لم يتم اعتماد أي قضية.")
        return

    if batch.decision.is_auto:
        selected = workflow_service.selected(callback.from_user.id)
        await status.edit_text(
            f"✅ تم اختيار القضية الأعلى تقييماً تلقائياً ({selected.final_score}/100).\n"
            f"{selected.candidate.title}\n\nجاري إعداد الملفات..."
        )
        await _send_assignment(callback, selected.token, workflow_service, assignment_service, subject_loader, status_message=status)
        return

    rows: list[list[InlineKeyboardButton]] = []
    parts = [f"وجدت {len(batch.cases)} قضايا موثقة مناسبة. اختر واحدة:"]
    for index, item in enumerate(batch.cases, start=1):
        parts.append(
            f"\n{index}) {item.candidate.title}\n"
            f"المحكمة: {item.candidate.court_name or 'غير متوفرة'}\n"
            f"رقم القضية: {item.candidate.case_number or 'غير متوفر'}\n"
            f"التقييم النهائي: {item.final_score}/100\n"
            f"سبب المناسبة: {item.candidate.suitability_reason}"
        )
        rows.append([InlineKeyboardButton(text=f"اعتماد القضية {index}", callback_data=f"{CALLBACK_PICK_PREFIX}{item.token}")])
    rows.append([InlineKeyboardButton(text="🔄 بحث جديد", callback_data=f"{CALLBACK_NEW_CASE_PREFIX}{slug}")])
    await status.edit_text("\n".join(parts), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), disable_web_page_preview=True)


@router.callback_query(F.data.startswith(CALLBACK_PICK_PREFIX))
async def pick_case(callback: CallbackQuery, workflow_service: CaseWorkflowService | None,
                    assignment_service: AssignmentService | None,
                    subject_loader: SubjectLoader) -> None:
    if workflow_service is None or assignment_service is None:
        await callback.answer("الخدمة غير جاهزة.", show_alert=True)
        return
    token = (callback.data or "").removeprefix(CALLBACK_PICK_PREFIX)
    try:
        workflow_service.select(callback.from_user.id, token)
    except KeyError:
        await callback.answer("انتهت جلسة الاختيار. ابدأ بحثاً جديداً.", show_alert=True)
        return
    await callback.answer()
    status = await callback.message.answer("✍️ تم اعتماد القضية. جاري إنشاء التعليق والتحقق منه...") if callback.message else None
    await _send_assignment(callback, token, workflow_service, assignment_service, subject_loader, status_message=status)


async def _send_assignment(callback: CallbackQuery, token: str,
                           workflow_service: CaseWorkflowService,
                           assignment_service: AssignmentService,
                           subject_loader: SubjectLoader,
                           status_message=None) -> None:
    if not callback.message:
        return
    try:
        selected = workflow_service.select(callback.from_user.id, token)
        subject = subject_loader.get_subject(workflow_service.session_subject(callback.from_user.id))
    except KeyError:
        await callback.message.answer("انتهت الجلسة. ابدأ بحثاً جديداً.")
        return

    docx_path: Path | None = None
    try:
        docx_path = await assignment_service.generate_docx(selected, subject)
        if not selected.artifact.path.exists():
            raise FileNotFoundError("Verified PDF was removed before send")
        pdf_name = f"حكم قضائي - {selected.candidate.case_number or 'قضية'}.pdf"
        docx_name = f"التعليق على حكم قضائي - {subject.name_ar}.docx"
        await callback.message.answer_document(
            FSInputFile(selected.artifact.path, filename=pdf_name),
            caption="ملف الحكم القضائي الأصلي من المصدر الرسمي.",
        )
        await callback.message.answer_document(
            FSInputFile(docx_path, filename=docx_name),
            caption="ملف التعليق الأكاديمي.",
        )
        await workflow_service.record_sent(callback.from_user.id)
        actions = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="♻️ إعادة توليد التعليق", callback_data=f"{CALLBACK_REGENERATE_PREFIX}{token}")],
            [InlineKeyboardButton(text="🔎 قضية أخرى", callback_data=f"{CALLBACK_NEW_CASE_PREFIX}{subject.slug}")],
        ])
        await callback.message.answer(
            f"✅ اكتمل التكليف.\nالتقييم: {selected.final_score}/100\nالمصدر الأصلي: {selected.artifact.source_url}",
            reply_markup=actions,
            disable_web_page_preview=True,
        )
        if status_message:
            await status_message.edit_text("✅ تم إنشاء الملفات وإرسالها بنجاح.")
    except Exception:
        logger.exception("Assignment generation/send failed")
        if status_message:
            await status_message.edit_text("❌ فشل إنشاء أو إرسال الملفات. لم تُسجل القضية كمستخدمة.")
        else:
            await callback.message.answer("❌ فشل إنشاء أو إرسال الملفات. لم تُسجل القضية كمستخدمة.")
    finally:
        if docx_path is not None:
            docx_path.unlink(missing_ok=True)


@router.callback_query(F.data.startswith(CALLBACK_REGENERATE_PREFIX))
async def regenerate(callback: CallbackQuery, workflow_service: CaseWorkflowService | None,
                     assignment_service: AssignmentService | None,
                     subject_loader: SubjectLoader) -> None:
    if workflow_service is None or assignment_service is None:
        await callback.answer("الخدمة غير جاهزة.", show_alert=True)
        return
    token = (callback.data or "").removeprefix(CALLBACK_REGENERATE_PREFIX)
    try:
        selected = workflow_service.select(callback.from_user.id, token)
        subject = subject_loader.get_subject(workflow_service.session_subject(callback.from_user.id))
    except KeyError:
        await callback.answer("انتهت الجلسة. أعد البحث عن القضية.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    status = await callback.message.answer("♻️ جاري إعادة صياغة التعليق مع بقاء القضية والوقائع نفسها...")
    path: Path | None = None
    try:
        path = await assignment_service.generate_docx(selected, subject, regeneration=True)
        await callback.message.answer_document(
            FSInputFile(path, filename=f"التعليق على حكم قضائي - {subject.name_ar} - بديل.docx"),
            caption="نسخة بديلة من التعليق على نفس القضية.",
        )
        await status.edit_text("✅ تم إرسال النسخة البديلة. لم تُسجل القضية مرة أخرى.")
    except Exception:
        logger.exception("Commentary regeneration failed")
        await status.edit_text("❌ تعذرت إعادة توليد التعليق حالياً.")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
