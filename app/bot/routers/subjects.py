"""Subject selection and full assignment workflow."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards import subjects_keyboard
from app.bot.progress import StatusTicker
from app.commentary import CommentaryValidationError
from app.core.constants import (
    CALLBACK_NEW_CASE_PREFIX, CALLBACK_PICK_PREFIX, CALLBACK_REGENERATE_PREFIX,
    CALLBACK_SEARCH_PREFIX, CALLBACK_SUBJECTS_PREFIX, SUBJECTS_PAGE_SIZE,
)
from app.core.settings import Settings
from app.deepseek import DeepSeekStreamError
from app.knowledge import SubjectLoader
from app.research import ResearchServiceError
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
async def search_cases(
    callback: CallbackQuery,
    workflow_service: CaseWorkflowService | None,
    assignment_service: AssignmentService | None,
    subject_loader: SubjectLoader,
    settings: Settings,
) -> None:
    await _start_search(
        callback,
        (callback.data or "").removeprefix(CALLBACK_SEARCH_PREFIX),
        workflow_service,
        assignment_service,
        subject_loader,
        settings,
    )


@router.callback_query(F.data.startswith(CALLBACK_NEW_CASE_PREFIX))
async def new_case(
    callback: CallbackQuery,
    workflow_service: CaseWorkflowService | None,
    assignment_service: AssignmentService | None,
    subject_loader: SubjectLoader,
    settings: Settings,
) -> None:
    await _start_search(
        callback,
        (callback.data or "").removeprefix(CALLBACK_NEW_CASE_PREFIX),
        workflow_service,
        assignment_service,
        subject_loader,
        settings,
    )


async def _start_search(
    callback: CallbackQuery,
    slug: str,
    workflow_service: CaseWorkflowService | None,
    assignment_service: AssignmentService | None,
    subject_loader: SubjectLoader,
    settings: Settings,
) -> None:
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
        f"⚙️ جاري تهيئة البحث لمادة: {subject.name_ar}…"
    )
    progress = StatusTicker(
        status,
        initial_phase=f"⚙️ جاري تهيئة البحث لمادة: {subject.name_ar}…",
        interval_seconds=settings.progress_update_interval_seconds,
    )
    await progress.start()

    try:
        batch = await workflow_service.prepare(
            callback.from_user.id,
            slug,
            progress=progress.set_phase,
        )
    except ResearchServiceError as exc:
        logger.exception(
            "Research service failure subject=%s code=%s detail=%s",
            slug,
            exc.code,
            exc.detail,
        )
        await progress.stop(f"{exc.user_message}\n\nرمز التشخيص: {exc.code}")
        return
    except NoSuitableCasesError:
        await progress.stop(
            "❌ انتهى البحث دون العثور على قضية مناسبة بملف PDF أصلي قابل للتحقق.\nلم يتم اعتماد أي قضية."
        )
        return
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.exception("Case preparation failed subject=%s", slug)
        await progress.stop(
            f"❌ تعذر إكمال البحث والتحقق حالياً. لم يتم اعتماد أي قضية.\n\nرمز التشخيص: {type(exc).__name__}"
        )
        return
    except Exception as exc:
        logger.exception("Unexpected case preparation failure subject=%s", slug)
        await progress.stop(
            f"❌ حدث خطأ غير متوقع أثناء البحث. لم يتم اعتماد أي قضية.\n\nرمز التشخيص: {type(exc).__name__}"
        )
        return

    if batch.decision.is_auto:
        selected = workflow_service.selected(callback.from_user.id)
        await progress.set_phase(
            f"✅ تم العثور على قضية موثقة واختيارها تلقائياً ({selected.final_score}/100).\n✍️ جاري إعداد التعليق والملفات…",
            immediate=True,
        )
        await _send_assignment(
            callback,
            selected.token,
            workflow_service,
            assignment_service,
            subject_loader,
            progress=progress,
        )
        return

    await progress.stop()
    rows: list[list[InlineKeyboardButton]] = []
    parts = [f"✅ تم التحقق من {len(batch.cases)} قضايا مناسبة. اختر واحدة:"]
    for index, item in enumerate(batch.cases, start=1):
        parts.append(
            f"\n{index}) {item.candidate.title}\n"
            f"المحكمة: {item.candidate.court_name or 'غير متوفرة'}\n"
            f"رقم القضية: {item.candidate.case_number or 'غير متوفر'}\n"
            f"التقييم النهائي: {item.final_score}/100\n"
            f"سبب المناسبة: {item.candidate.suitability_reason}"
        )
        rows.append([
            InlineKeyboardButton(
                text=f"اعتماد القضية {index}",
                callback_data=f"{CALLBACK_PICK_PREFIX}{item.token}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔄 بحث جديد",
            callback_data=f"{CALLBACK_NEW_CASE_PREFIX}{slug}",
        )
    ])
    await status.edit_text(
        "\n".join(parts),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith(CALLBACK_PICK_PREFIX))
async def pick_case(
    callback: CallbackQuery,
    workflow_service: CaseWorkflowService | None,
    assignment_service: AssignmentService | None,
    subject_loader: SubjectLoader,
    settings: Settings,
) -> None:
    if workflow_service is None or assignment_service is None:
        await callback.answer("الخدمة غير جاهزة.", show_alert=True)
        return
    token = (callback.data or "").removeprefix(CALLBACK_PICK_PREFIX)
    try:
        await workflow_service.select(callback.from_user.id, token)
    except KeyError:
        await callback.answer("انتهت جلسة الاختيار. ابدأ بحثاً جديداً.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return
    status = await callback.message.answer("✍️ تم اعتماد القضية. جاري إعداد التعليق…")
    progress = StatusTicker(
        status,
        initial_phase="✍️ تم اعتماد القضية. جاري إعداد التعليق القانوني…",
        interval_seconds=settings.progress_update_interval_seconds,
    )
    await progress.start()
    await _send_assignment(
        callback,
        token,
        workflow_service,
        assignment_service,
        subject_loader,
        progress=progress,
    )


async def _send_assignment(
    callback: CallbackQuery,
    token: str,
    workflow_service: CaseWorkflowService,
    assignment_service: AssignmentService,
    subject_loader: SubjectLoader,
    *,
    progress: StatusTicker | None = None,
) -> None:
    if not callback.message:
        if progress:
            await progress.stop()
        return
    try:
        selected = await workflow_service.select(callback.from_user.id, token)
        subject = subject_loader.get_subject(
            workflow_service.session_subject(callback.from_user.id)
        )
    except KeyError:
        if progress:
            await progress.stop("❌ انتهت الجلسة. ابدأ بحثاً جديداً.")
        else:
            await callback.message.answer("انتهت الجلسة. ابدأ بحثاً جديداً.")
        return

    docx_path: Path | None = None
    pdf_sent = False
    try:
        docx_path = await assignment_service.generate_docx(
            selected,
            subject,
            progress=(progress.set_phase if progress else None),
        )
        if not selected.artifact.path.exists():
            raise FileNotFoundError("Verified PDF was removed before send")

        if progress:
            await progress.set_phase("📤 جاري إرسال ملف الحكم القضائي الأصلي…", immediate=True)

        case_number = selected.candidate.case_number or "قضية"
        pdf_name = f"حكم قضائي - {case_number} - {subject.name_ar}.pdf"
        docx_name = f"التعليق على حكم قضائي - {case_number} - {subject.name_ar}.docx"
        pdf_caption = "ملف الحكم القضائي الأصلي من المصدر الرسمي."
        if selected.artifact_kind == "official_compilation_extract":
            pdf_caption = "صفحات الحكم الأصلية فقط، مستخرجة من مجموعة أحكام رسمية دون إعادة إنشاء المحتوى."

        await callback.message.answer_document(
            FSInputFile(selected.artifact.path, filename=pdf_name),
            caption=pdf_caption,
        )
        pdf_sent = True

        if progress:
            await progress.set_phase("📤 تم إرسال الحكم. جاري إرسال ملف التعليق الأكاديمي…", immediate=True)

        await callback.message.answer_document(
            FSInputFile(docx_path, filename=docx_name),
            caption="ملف التعليق الأكاديمي المطابق لبيانات الحكم الموثقة.",
        )
        await workflow_service.record_sent(callback.from_user.id)
        actions = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="♻️ إعادة توليد التعليق",
                    callback_data=f"{CALLBACK_REGENERATE_PREFIX}{token}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔎 قضية أخرى",
                    callback_data=f"{CALLBACK_NEW_CASE_PREFIX}{subject.slug}",
                )
            ],
        ])
        await callback.message.answer(
            f"✅ اكتمل التكليف.\n"
            f"رقم القضية: {case_number}\n"
            f"التقييم: {selected.final_score}/100\n"
            f"المصدر الأصلي: {selected.artifact.source_url}",
            reply_markup=actions,
            disable_web_page_preview=True,
        )
        if progress:
            await progress.stop("✅ تم إنشاء الملفات والتحقق منها وإرسالها بنجاح.")
    except Exception as exc:
        logger.exception(
            "Assignment generation/send failed code=%s case=%s",
            _assignment_failure_code(exc),
            selected.candidate.case_number,
        )
        code = _assignment_failure_code(exc)
        message = _assignment_failure_message(code, pdf_sent=pdf_sent)
        if progress:
            await progress.stop(f"{message}\n\nرمز التشخيص: {code}")
        else:
            await callback.message.answer(f"{message}\n\nرمز التشخيص: {code}")

        # Keep the verified judgment/session reserved. A drafting or Telegram
        # failure must never force another search/download or lose the chosen case.
        retry_prefix = CALLBACK_REGENERATE_PREFIX if pdf_sent else CALLBACK_PICK_PREFIX
        retry_text = "🔁 إعادة إرسال التعليق" if pdf_sent else "🔁 إعادة المحاولة على نفس القضية"
        retry_actions = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=retry_text, callback_data=f"{retry_prefix}{token}")],
            [
                InlineKeyboardButton(
                    text="🔎 اختيار قضية أخرى",
                    callback_data=f"{CALLBACK_NEW_CASE_PREFIX}{subject.slug}",
                )
            ],
        ])
        await callback.message.answer(
            "القضية الموثقة ما زالت محفوظة في الجلسة؛ لا حاجة لإعادة البحث أو تنزيل الحكم.",
            reply_markup=retry_actions,
        )
    finally:
        if docx_path is not None:
            docx_path.unlink(missing_ok=True)


@router.callback_query(F.data.startswith(CALLBACK_REGENERATE_PREFIX))
async def regenerate(
    callback: CallbackQuery,
    workflow_service: CaseWorkflowService | None,
    assignment_service: AssignmentService | None,
    subject_loader: SubjectLoader,
    settings: Settings,
) -> None:
    if workflow_service is None or assignment_service is None:
        await callback.answer("الخدمة غير جاهزة.", show_alert=True)
        return
    token = (callback.data or "").removeprefix(CALLBACK_REGENERATE_PREFIX)
    try:
        selected = await workflow_service.select(callback.from_user.id, token)
        subject = subject_loader.get_subject(
            workflow_service.session_subject(callback.from_user.id)
        )
    except KeyError:
        await callback.answer("انتهت الجلسة. أعد البحث عن القضية.", show_alert=True)
        return
    await callback.answer()
    if not callback.message:
        return

    status = await callback.message.answer(
        "♻️ جاري إعادة صياغة التعليق مع بقاء القضية والوقائع نفسها…"
    )
    progress = StatusTicker(
        status,
        initial_phase="♻️ جاري إعادة صياغة التعليق مع بقاء القضية والوقائع نفسها…",
        interval_seconds=settings.progress_update_interval_seconds,
    )
    await progress.start()
    path: Path | None = None
    try:
        path = await assignment_service.generate_docx(
            selected,
            subject,
            regeneration=True,
            progress=progress.set_phase,
        )
        await progress.set_phase("📤 جاري إرسال النسخة البديلة من التعليق…", immediate=True)
        case_number = selected.candidate.case_number or "قضية"
        await callback.message.answer_document(
            FSInputFile(
                path,
                filename=f"التعليق على حكم قضائي - {case_number} - {subject.name_ar} - بديل.docx",
            ),
            caption="نسخة بديلة من التعليق على نفس القضية.",
        )
        # Idempotent: records the case only if the original full delivery had not
        # already completed. This also finishes a partial delivery where PDF sent
        # successfully but the DOCX send previously failed.
        await workflow_service.record_sent(callback.from_user.id)
        await progress.stop("✅ تم إرسال النسخة البديلة. لم تُسجل القضية أكثر من مرة.")
    except Exception as exc:
        code = _assignment_failure_code(exc)
        logger.exception("Commentary regeneration failed code=%s", code)
        await progress.stop(
            f"{_assignment_failure_message(code, pdf_sent=True)}\n\nرمز التشخيص: {code}"
        )
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def _assignment_failure_code(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "commentary_timeout"
    if isinstance(exc, DeepSeekStreamError):
        return "commentary_stream"
    if isinstance(exc, CommentaryValidationError):
        return "commentary_validation"
    if isinstance(exc, TelegramAPIError):
        return "telegram_send"
    if isinstance(exc, FileNotFoundError):
        return "artifact_missing"
    if isinstance(exc, ValueError):
        return "commentary_output"
    return type(exc).__name__.lower()


def _assignment_failure_message(code: str, *, pdf_sent: bool) -> str:
    if code == "commentary_timeout":
        return (
            "⏳ توقف بث كتابة التعليق مدة أطول من الحد الآمن. "
            "لم تُفقد القضية ويمكن إعادة المحاولة عليها مباشرة."
        )
    if code == "commentary_stream":
        return (
            "🧩 انتهى بث كتابة التعليق قبل وصول نتيجة مكتملة. "
            "القضية الموثقة محفوظة ويمكن إعادة المحاولة دون بحث جديد."
        )
    if code == "commentary_validation":
        return (
            "🛡️ المسودة لم تجتز التحقق القانوني النهائي حتى بعد محاولة التصحيح، "
            "ولذلك لم يرسل النظام ملفاً غير موثوق."
        )
    if code == "commentary_output":
        return (
            "🧾 لم تصل مخرجات التعليق بالصيغة المنظمة المطلوبة. "
            "القضية محفوظة ويمكن إعادة المحاولة دون إعادة البحث."
        )
    if code == "telegram_send":
        return (
            "📡 تم تجهيز الملفات لكن تعذر إرسال أحدها عبر Telegram حالياً. "
            + ("ملف الحكم أُرسل بالفعل؛ يمكنك إعادة إرسال التعليق فقط." if pdf_sent else "يمكن إعادة الإرسال على نفس القضية.")
        )
    if code == "artifact_missing":
        return "📁 ملف الحكم الموثق لم يعد موجوداً وقت الإرسال؛ لم تُسجل القضية كمستخدمة."
    return "❌ تعذر إكمال إنشاء أو إرسال الملفات حالياً. القضية الموثقة ما زالت محفوظة لإعادة المحاولة."
